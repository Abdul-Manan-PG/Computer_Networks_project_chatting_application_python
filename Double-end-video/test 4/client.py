#!/usr/bin/env python3
"""
Reliable TCP client for chat + call signaling + media streaming.

(Protocol definitions are the same)
"""

import socket
import threading
import json
import struct
import time
import sys
import cv2
import numpy as np
import pyaudio
from flask import Flask, Response

# ---------------- CONFIG ----------------
SERVER_IP = "127.0.0.1" # MUST match server IP
SERVER_PORT = 5000

VIDEO_FPS = 20
VIDEO_QUALITY = 80  
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
FLASK_PORT = 5001  # Unique local web UI port
# ----------------------------------------

app = Flask(__name__)

# Shared state
tcp_sock = None
tcp_lock = threading.Lock()
username = None

running = threading.Event()
running.set()

in_call = threading.Event()
partner = None

# Local port information
my_ip = None
video_listen_port = None
audio_listen_port = None
ports_ready = threading.Event()

# For local preview
latest_frame = None
frame_lock = threading.Lock()

# pyaudio output stream (set up later)
pyaudio_inst = pyaudio.PyAudio()
audio_out_stream = None

# ------------------ Networking utils ------------------
def safe_send(sock: socket.socket, obj: dict):
    """Send newline-terminated JSON safely."""
    try:
        data = (json.dumps(obj) + "\n").encode("utf-8")
        with tcp_lock:
            sock.sendall(data)
    except Exception as e:
        print(f"[WARN] safe_send failed: {e}")

# This is the robust replacement for safe_recv_line/recv_line_from_socket
def recv_packet_line(sock: socket.socket, timeout=None):
    """Receive a single newline-terminated JSON line. Returns str or None."""
    sock.settimeout(timeout)
    buffer = getattr(sock, 'leftover', b'')
    
    try:
        while running.is_set():
            if b"\n" in buffer:
                line, rest = buffer.split(b"\n", 1)
                sock.leftover = rest
                return line.decode("utf-8")

            chunk = sock.recv(4096)
            if not chunk:
                return None
            buffer += chunk

    except socket.timeout:
        sock.leftover = buffer
        return None
    except Exception as e:
        print(f"[WARN] recv_packet_line error: {e}")
        sock.leftover = b''
        return None


# ------------------ Media framing utils ------------------
def send_framed(conn: socket.socket, raw_bytes: bytes):
    # ... (content remains the same) ...
    try:
        header = struct.pack("!I", len(raw_bytes))
        conn.sendall(header + raw_bytes)
    except Exception as e:
        print(f"[ERROR] send_framed: {e}")

def recv_framed(conn: socket.socket):
    # ... (content remains the same) ...
    try:
        header = b""
        while len(header) < 4:
            chunk = conn.recv(4 - len(header))
            if not chunk:
                return None
            header += chunk
            
        (size,) = struct.unpack("!I", header)
        
        data = b""
        while len(data) < size:
            chunk = conn.recv(min(65536, size - len(data)))
            if not chunk:
                return None
            data += chunk
        return data
        
    except Exception:
        return None

# ------------------ Utility ------------------
def get_free_port():
    # ... (content remains the same) ...
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port

def get_my_ip():
    # ... (content remains the same) ...
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)) 
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"


# ------------------ Flask preview (Rest of client.py remains the same) ------------------
def generate_video():
    global latest_frame
    while running.is_set():
        with frame_lock:
            if latest_frame is not None:
                ok, jpg = cv2.imencode(".jpg", latest_frame, [int(cv2.IMWRITE_JPEG_QUALITY), VIDEO_QUALITY])
                if ok:
                    frame = jpg.tobytes()
                    yield (b"--frame\r\n"
                           b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
        time.sleep(1.0 / VIDEO_FPS)

@app.route("/")
def index():
    return f"<h3>Local Preview for {username}</h3><img src='/video' width='320' height='240' />"

@app.route("/video")
def video_feed():
    return Response(generate_video(), mimetype="multipart/x-mixed-replace; boundary=frame")


# ------------------ Media sender threads (Rest of client.py remains the same) ------------------
def video_send_thread(target_ip, target_port, stop_event: threading.Event):
    # ... (content remains the same) ...
    cap = None
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((target_ip, target_port))
        sock.settimeout(None)
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("[ERROR] Camera not available. Stopping video send.")
            return
            
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        
        print(f"[VIDEO SEND] connected -> {target_ip}:{target_port}")
        while running.is_set() and not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue
            
            ok, enc = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), VIDEO_QUALITY])
            if not ok:
                continue
            payload = enc.tobytes()
            send_framed(sock, payload)
            time.sleep(1.0 / VIDEO_FPS)
            
    except Exception as e:
        print(f"[ERROR] video_send_thread failed: {e}")
    finally:
        if cap:
            cap.release()
        if sock:
            sock.close()
        print("[VIDEO SEND] stopped")

def audio_send_thread(target_ip, target_port, stop_event: threading.Event):
    # ... (content remains the same) ...
    audio = None
    mic = None
    sock = None
    try:
        audio = pyaudio_inst
        mic = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                         input=True, frames_per_buffer=CHUNK, exception_on_overflow=False) 
                         
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((target_ip, target_port))
        sock.settimeout(None)
        
        print(f"[AUDIO SEND] connected -> {target_ip}:{target_port}")
        while running.is_set() and not stop_event.is_set():
            data = mic.read(CHUNK, exception_on_overflow=False) 
            send_framed(sock, data)
            
    except Exception as e:
        print(f"[ERROR] audio_send_thread failed: {e}")
    finally:
        if mic:
            mic.stop_stream()
            mic.close()
        if sock:
            sock.close()
        print("[AUDIO SEND] stopped")

# ------------------ Media receiver servers (Rest of client.py remains the same) ------------------
def video_server_thread(listen_port, stop_event: threading.Event):
    # ... (content remains the same) ...
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", listen_port)) 
    server.listen(1)
    conn = None
    try:
        server.settimeout(20) 
        conn, addr = server.accept()
        conn.settimeout(None)
        print(f"[VIDEO RECV] connection from {addr}")
        while running.is_set() and not stop_event.is_set():
            payload = recv_framed(conn)
            if payload is None:
                break
                
            frame = np.frombuffer(payload, np.uint8)
            img = cv2.imdecode(frame, cv2.IMREAD_COLOR)
            if img is not None:
                with frame_lock:
                    global latest_frame
                    latest_frame = img
                    
    except socket.timeout:
        print("[ERROR] Video server timeout: No partner connection received.")
    except Exception as e:
        print(f"[ERROR] video_server_thread failed: {e}")
    finally:
        if conn:
            conn.close()
        server.close()
        print("[VIDEO RECV] stopped")

def audio_server_thread(listen_port, stop_event: threading.Event):
    # ... (content remains the same) ...
    global audio_out_stream
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", listen_port))
    server.listen(1)
    conn = None
    try:
        if audio_out_stream is None or not audio_out_stream.is_active():
            audio_out_stream = pyaudio_inst.open(format=FORMAT, channels=CHANNELS,
                                                rate=RATE, output=True,
                                                frames_per_buffer=CHUNK)
                                                
        server.settimeout(20)
        conn, addr = server.accept()
        conn.settimeout(None)
        print(f"[AUDIO RECV] connection from {addr}")
        while running.is_set() and not stop_event.is_set():
            payload = recv_framed(conn)
            if payload is None:
                break
                
            try:
                audio_out_stream.write(payload)
            except Exception:
                pass
                
    except socket.timeout:
        print("[ERROR] Audio server timeout: No partner connection received.")
    except Exception as e:
        print(f"[ERROR] audio_server_thread failed: {e}")
    finally:
        if conn:
            conn.close()
        server.close()
        print("[AUDIO RECV] stopped")


# ------------------ TCP listener ------------------
def tcp_listener(sock: socket.socket):
    global partner, in_call
    # Initialize socket leftover buffer
    sock.leftover = b'' 
    
    while running.is_set():
        try:
            # Using the robust line receiver
            line = recv_packet_line(sock)
            if line is None:
                print("\n[TCP] Server closed connection or connection lost.")
                running.clear()
                stop_call()
                break
            try:
                pkt = json.loads(line)
            except json.JSONDecodeError:
                print(f"\n[TCP] Received non-JSON: {line}")
                continue

            ptype = pkt.get("type")
            
            # --- Chat Message ---
            if ptype == "msg":
                frm = pkt.get("from", "unknown")
                msg = pkt.get("msg", "")
                print(f"\n[{frm}] {msg}")
                
            # --- Errors ---
            elif ptype == "error":
                print(f"\n[SERVER ERROR] {pkt.get('msg')}")
                
            # --- Incoming Call Request ---
            elif ptype == "incoming_call":
                caller = pkt.get("from")
                print(f"\n[CALL] 📞 Incoming call from {caller}")
                
                if in_call.is_set():
                    print(f"[CALL] Already in a call with {partner}. Rejecting {caller}.")
                    safe_send(sock, {"type": "call_answer", "answer": "no"})
                    continue
                    
                ans = None
                while True:
                    ans = input("Accept call? (y/n): ").strip().lower()
                    if ans in ("y", "n"):
                        break
                        
                if ans == "y":
                    safe_send(sock, {"type": "call_answer", "answer": "yes"})
                    # Start local listeners before sending 'call_answer' (or immediately after)
                    start_media_listeners() 
                else:
                    safe_send(sock, {"type": "call_answer", "answer": "no"})
                    
            # --- Call Accepted/Ports Exchange Step 1 ---
            elif ptype == "call_accept":
                partner_name = pkt.get("partner")
                print(f"[CALL] Partner {partner_name} accepted; exchanging ports...")
                
                if not ports_ready.is_set() or my_ip is None:
                    print("[ERROR] Call accepted, but local ports are not ready. Aborting.")
                    safe_send(sock, {"type": "end_call"})
                    stop_call()
                    continue
                    
                safe_send(sock, {
                    "type": "ports", 
                    "ip": my_ip, 
                    "video_port": video_listen_port, 
                    "audio_port": audio_listen_port
                })
                
            # --- Ports Received/Media Start Step 2 ---
            elif ptype == "ports_relay":
                partner_name = pkt.get("partner")
                their_ip = pkt.get("ip")
                their_vport = int(pkt.get("video_port"))
                their_aport = int(pkt.get("audio_port"))
                
                print(f"[CALL] Received partner endpoints {their_ip}:{their_vport} (video), {their_ip}:{their_aport} (audio)")
                
                partner = partner_name
                start_media_streams(their_ip, their_vport, their_aport)
                
            # --- Call Ended/Failed ---
            elif ptype == "call_rejected":
                print("[CALL] Call was rejected by partner.")
                stop_call()
            elif ptype == "call_ended":
                print(f"[CALL] Partner {pkt.get('from')} ended call: {pkt.get('msg')}")
                stop_call()
            elif ptype == "call_failed":
                print(f"[CALL] Call failed: {pkt.get('reason')}")
                stop_call()
            
            # --- Fallback ---
            else:
                print(f"[TCP] Unknown packet: {pkt}")
                
        except Exception as e:
            print(f"[WARN] tcp_listener exception: {e}")
            time.sleep(0.5)
            continue

# ------------------ Call flow helpers (Rest of client.py remains the same) ------------------
media_stop_event = None
video_send_t = None
audio_send_t = None
video_server_t = None
audio_server_t = None
flask_t = None

def start_media_listeners():
    # ... (content remains the same) ...
    global video_listen_port, audio_listen_port, video_server_t, audio_server_t, media_stop_event, my_ip
    
    if media_stop_event and not media_stop_event.is_set():
         stop_call()
         
    media_stop_event = threading.Event()
    
    my_ip = get_my_ip()
    video_listen_port = get_free_port()
    audio_listen_port = get_free_port()
    
    video_server_t = threading.Thread(target=video_server_thread, args=(video_listen_port, media_stop_event), daemon=True)
    audio_server_t = threading.Thread(target=audio_server_thread, args=(audio_listen_port, media_stop_event), daemon=True)
    
    video_server_t.start()
    audio_server_t.start()
    
    ports_ready.set()
    print(f"[CALL] Local media listeners started on {my_ip}:{video_listen_port} (video), {my_ip}:{audio_listen_port} (audio)")
    
    return my_ip, video_listen_port, audio_listen_port

def start_media_streams(target_ip, target_vport, target_aport):
    # ... (content remains the same) ...
    global media_stop_event, video_send_t, audio_send_t, flask_t
    
    video_send_t = threading.Thread(target=video_send_thread, args=(target_ip, target_vport, media_stop_event), daemon=True)
    audio_send_t = threading.Thread(target=audio_send_thread, args=(target_ip, target_aport, media_stop_event), daemon=True)
    
    video_send_t.start()
    audio_send_t.start()
    
    flask_t = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=FLASK_PORT, debug=False, use_reloader=False), daemon=True)
    flask_t.start()
    
    in_call.set()
    print(f"🎉 [CALL] Media streams connected! Local preview http://{get_my_ip()}:{FLASK_PORT}")

def stop_call():
    # ... (content remains the same) ...
    global media_stop_event, video_send_t, audio_send_t, video_server_t, audio_server_t, partner, in_call
    global ports_ready, my_ip, video_listen_port, audio_listen_port
    
    if not in_call.is_set() and (media_stop_event is None or media_stop_event.is_set()):
        return
        
    print("[CALL] Stopping call...")
    
    if media_stop_event:
        media_stop_event.set()
        
    time.sleep(0.5)
    
    media_stop_event = None
    partner = None
    my_ip = None
    video_listen_port = None
    audio_listen_port = None
    ports_ready.clear()
    in_call.clear()
    
    print("[CALL] stopped")

# ------------------ Main client program (Rest of client.py remains the same) ------------------
def interactive_loop(sock: socket.socket):
    print("\n--- Commands ---")
    print(" - Broadcast: /b your message")
    print(" - Private:   /p username your message")
    print(" - Call:      /call username")
    print(" - End call:  /end")
    print(" - Quit:      /quit")
    print("----------------")
    
    while running.is_set():
        try:
            line = sys.stdin.readline().strip()
            if not line:
                continue
                
            if line.startswith("/b "):
                msg = line[3:].strip()
                safe_send(sock, {"type": "broadcast", "msg": msg})
                
            elif line.startswith("/p "):
                rest = line[3:].strip()
                target, _, msg = rest.partition(" ")
                if not target or not msg:
                    print("[INFO] Usage: /p username your message")
                    continue
                safe_send(sock, {"type": "msg", "to": target, "msg": msg})
                
            elif line.startswith("/call "):
                if in_call.is_set():
                    print("[INFO] Already in a call. End it first with /end.")
                    continue
                
                target = line.split(" ", 1)[1].strip()
                if not target:
                    print("[INFO] Usage: /call username")
                    continue

                start_media_listeners() 
                
                safe_send(sock, {"type": "call", "to": target})
                print(f"[CALL] Requesting call with {target}. Waiting for partner acceptance...")

            elif line == "/end":
                if in_call.is_set():
                    safe_send(sock, {"type": "end_call"})
                    stop_call()
                else:
                    print("No active call to end.")
                    
            elif line == "/quit":
                running.clear()
                safe_send(sock, {"type": "quit"})
                try:
                    sock.close()
                except:
                    pass
                break
                
            else:
                print(f"[INFO] Unknown command: '{line}'. Use /b, /p, /call, /end, or /quit.")

        except EOFError:
             running.clear()
             safe_send(sock, {"type": "quit"})
             break
        except Exception as e:
            print(f"[WARN] interactive_loop error: {e}")
            break

def start_client():
    global tcp_sock, username
    
    try:
        username = input("Enter username: ").strip()
        if not username:
            print("Username required.")
            return

        print(f"Connecting to {SERVER_IP}:{SERVER_PORT}...")
        tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_sock.connect((SERVER_IP, SERVER_PORT))
        # Initialize leftover buffer on socket object
        tcp_sock.leftover = b'' 
    except Exception as e:
        print(f"[ERROR] Could not connect to server: {e}")
        return

    safe_send(tcp_sock, {"type": "register", "username": username})
    
    t = threading.Thread(target=tcp_listener, args=(tcp_sock,), daemon=True)
    t.start()
    
    print(f"\nWelcome, {username}! You are connected.")
    
    interactive_loop(tcp_sock)
    
    running.clear()
    stop_call()
    try:
        tcp_sock.close()
    except:
        pass
        
    print("Client exiting.")
    sys.exit(0)

if __name__ == "__main__":
    try:
        start_client()
    except KeyboardInterrupt:
        running.clear()
        stop_call()
        try:
            if tcp_sock:
                tcp_sock.close()
        except:
            pass
        print("\nInterrupted, exiting.")
        sys.exit(0)