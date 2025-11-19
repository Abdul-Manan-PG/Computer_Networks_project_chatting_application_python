#!/usr/bin/env python3
"""
Reliable TCP client for chat + call signaling + media streaming.

Protocol (JSON lines, newline-terminated):
- Register: {"type":"register", "username":"bob"}
- Chat:     {"type":"msg", "to":"alice", "msg":"hello"}  OR {"type":"broadcast", "msg":"hi all"}
- Call:     {"type":"call", "to":"alice"}
- Answer:   {"type":"call_answer", "answer":"yes" / "no"}
- Ports:    {"type":"ports", "ip":"1.2.3.4", "video_port":5001, "audio_port":5002}
- End call: {"type":"end_call"}
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
SERVER_IP = "10.75.26.20"
SERVER_PORT = 5000

VIDEO_FPS = 20
VIDEO_QUALITY = 80  # JPEG quality (0-100)
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
FLASK_PORT = 5000  # local web UI port for preview
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
        data = (json.dumps(obj) + "\n").encode()
        with tcp_lock:
            sock.sendall(data)
    except Exception as e:
        print(f"[WARN] safe_send failed: {e}")

def safe_recv_line(sock: socket.socket, timeout=None):
    """Receive a single newline-terminated JSON line. Returns str or None."""
    sock.settimeout(timeout)
    buffer = b""
    try:
        while running.is_set():
            chunk = sock.recv(4096)
            if not chunk:
                return None
            buffer += chunk
            if b"\n" in buffer:
                line, rest = buffer.split(b"\n", 1)
                # Put rest back into the socket using a small local buffer hack is complicated.
                # Simpler: keep a static leftover stored on the socket object.
                # We'll attach a 'leftover' attribute to the socket.
                sock.leftover = rest
                return line.decode()
    except socket.timeout:
        return None
    except Exception as e:
        print(f"[WARN] safe_recv_line error: {e}")
        return None

def recv_line_from_socket(sock: socket.socket):
    """Helper that honors sock.leftover if present, then reads more as needed."""
    try:
        if getattr(sock, "leftover", b""):
            data = sock.leftover
            if b"\n" in data:
                line, rest = data.split(b"\n", 1)
                sock.leftover = rest
                return line.decode()
            # else use buffer as starting point
        else:
            data = b""
        sock.settimeout(0.5)
        while running.is_set():
            chunk = sock.recv(4096)
            if not chunk:
                return None
            data += chunk
            if b"\n" in data:
                line, rest = data.split(b"\n", 1)
                sock.leftover = rest
                return line.decode()
    except socket.timeout:
        return None
    except Exception as e:
        print(f"[WARN] recv_line_from_socket error: {e}")
        return None

# ------------------ Media framing utils ------------------
def send_framed(conn: socket.socket, raw_bytes: bytes):
    """Send length-prefixed frame (4 bytes big-endian)."""
    try:
        header = struct.pack("!I", len(raw_bytes))
        conn.sendall(header + raw_bytes)
    except Exception as e:
        print(f"[ERROR] send_framed: {e}")

def recv_framed(conn: socket.socket):
    """Receive a single framed payload (blocking). Returns bytes or None on error."""
    try:
        header = conn.recv(4)
        if not header:
            return None
        (size,) = struct.unpack("!I", header)
        data = b""
        while len(data) < size:
            chunk = conn.recv(min(65536, size - len(data)))
            if not chunk:
                return None
            data += chunk
        return data
    except Exception as e:
        # print(f"[DEBUG] recv_framed error: {e}")
        return None

# ------------------ Utility ------------------
def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port

def get_my_ip():
    # Best-effort, not NAT-aware
    try:
        return socket.gethostbyname(socket.gethostname())
    except:
        return "127.0.0.1"

# ------------------ Flask preview ------------------
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
    return "<h3>Local Preview</h3><img src='/video' />"

@app.route("/video")
def video_feed():
    return Response(generate_video(), mimetype="multipart/x-mixed-replace; boundary=frame")

# ------------------ Media sender threads ------------------
def video_send_thread(target_ip, target_port, stop_event: threading.Event):
    """Connect to partner's video port and stream webcam frames framed."""
    cap = None
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((target_ip, target_port))
        sock.settimeout(None)
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("[ERROR] Camera not available")
            return
        print(f"[VIDEO SEND] connected -> {target_ip}:{target_port}")
        while running.is_set() and not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue
            # encode
            ok, enc = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), VIDEO_QUALITY])
            if not ok:
                continue
            payload = enc.tobytes()
            send_framed(sock, payload)
            time.sleep(1.0 / VIDEO_FPS)
    except Exception as e:
        print(f"[ERROR] video_send_thread: {e}")
    finally:
        try:
            if cap:
                cap.release()
        except:
            pass
        try:
            if sock:
                sock.close()
        except:
            pass
        print("[VIDEO SEND] stopped")

def audio_send_thread(target_ip, target_port, stop_event: threading.Event):
    """Connect to partner's audio port and stream microphone audio framed."""
    audio = None
    mic = None
    sock = None
    try:
        audio = pyaudio_inst
        mic = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                         input=True, frames_per_buffer=CHUNK)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((target_ip, target_port))
        sock.settimeout(None)
        print(f"[AUDIO SEND] connected -> {target_ip}:{target_port}")
        while running.is_set() and not stop_event.is_set():
            data = mic.read(CHUNK, exception_on_overflow=False)
            send_framed(sock, data)
    except Exception as e:
        print(f"[ERROR] audio_send_thread: {e}")
    finally:
        try:
            if mic:
                mic.stop_stream()
                mic.close()
        except:
            pass
        try:
            if sock:
                sock.close()
        except:
            pass
        print("[AUDIO SEND] stopped")

# ------------------ Media receiver servers ------------------
def video_server_thread(listen_port, stop_event: threading.Event):
    """Accept single connection and display frames to latest_frame"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", listen_port))
    server.listen(1)
    conn = None
    try:
        server.settimeout(10)
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
    except Exception as e:
        print(f"[ERROR] video_server_thread: {e}")
    finally:
        try:
            if conn:
                conn.close()
        except:
            pass
        try:
            server.close()
        except:
            pass
        print("[VIDEO RECV] stopped")

def audio_server_thread(listen_port, stop_event: threading.Event):
    """Accept single connection and write audio frames to output stream."""
    global audio_out_stream
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", listen_port))
    server.listen(1)
    conn = None
    try:
        if audio_out_stream is None:
            audio_out_stream = pyaudio_inst.open(format=FORMAT, channels=CHANNELS,
                                                rate=RATE, output=True,
                                                frames_per_buffer=CHUNK)
        server.settimeout(10)
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
    except Exception as e:
        print(f"[ERROR] audio_server_thread: {e}")
    finally:
        try:
            if conn:
                conn.close()
        except:
            pass
        try:
            server.close()
        except:
            pass
        print("[AUDIO RECV] stopped")

# ------------------ TCP listener ------------------
def tcp_listener(sock: socket.socket):
    global partner, in_call
    while running.is_set():
        try:
            line = recv_line_from_socket(sock)
            if line is None:
                print("[TCP] Server closed connection.")
                running.clear()
                break
            try:
                pkt = json.loads(line)
            except Exception:
                print(f"[TCP] Received non-JSON: {line}")
                continue

            ptype = pkt.get("type")
            if ptype == "msg":
                frm = pkt.get("from", "unknown")
                msg = pkt.get("msg", "")
                print(f"\n[{frm}] {msg}")
            elif ptype == "error":
                print(f"\n[SERVER ERROR] {pkt.get('msg')}")
            elif ptype == "incoming_call":
                caller = pkt.get("from")
                print(f"\n[CALL] Incoming call from {caller}")
                # prompt user for answer in a blocking way on main thread: send a simple console prompt
                ans = None
                while True:
                    ans = input("Accept call? (y/n): ").strip().lower()
                    if ans in ("y", "n"):
                        break
                if ans == "y":
                    safe_send(sock, {"type": "call_answer", "answer": "yes"})
                    # server will coordinate ports exchange; wait for 'ports' packet
                else:
                    safe_send(sock, {"type": "call_answer", "answer": "no"})
            elif ptype == "call_accept":
                # server told both sides call accepted; next step is ports exchange by sending/receiving 'ports'
                print("[CALL] Partner accepted; exchanging ports...")
            elif ptype == "call_rejected":
                print("[CALL] Call was rejected by partner.")
            elif ptype == "ports":
                # partner's ports received from server
                partner = pkt.get("from")
                their_ip = pkt.get("ip")
                their_vport = int(pkt.get("video_port"))
                their_aport = int(pkt.get("audio_port"))
                print(f"[CALL] Received partner endpoints {their_ip}:{their_vport} (video), {their_ip}:{their_aport} (audio)")
                # start sending to partner and start listening servers already started by us earlier
                start_media_streams(their_ip, their_vport, their_aport)
            elif ptype == "call_ended":
                print(f"[CALL] Partner ended call: {pkt.get('from')}")
                stop_call()
            else:
                # generic print for unknown
                print(f"[TCP] {pkt}")
        except Exception as e:
            print(f"[WARN] tcp_listener exception: {e}")
            time.sleep(0.5)
            continue

# ------------------ Call flow helpers ------------------
media_stop_event = None
video_send_t = None
audio_send_t = None
video_server_t = None
audio_server_t = None
flask_t = None
video_listen_port = None
audio_listen_port = None

def start_media_listeners():
    """Pick ports and start local servers for receiving partner's streams. Return (ip, vport, aport)."""
    global video_listen_port, audio_listen_port, video_server_t, audio_server_t, media_stop_event
    media_stop_event = threading.Event()
    video_listen_port = get_free_port()
    audio_listen_port = get_free_port()
    video_server_t = threading.Thread(target=video_server_thread, args=(video_listen_port, media_stop_event), daemon=True)
    audio_server_t = threading.Thread(target=audio_server_thread, args=(audio_listen_port, media_stop_event), daemon=True)
    video_server_t.start()
    audio_server_t.start()
    return get_my_ip(), video_listen_port, audio_listen_port

def start_media_streams(target_ip, target_vport, target_aport):
    """Start threads that send our camera/mic to partner endpoints."""
    global media_stop_event, video_send_t, audio_send_t, flask_t
    if media_stop_event is None:
        media_stop_event = threading.Event()
    # start senders
    video_send_t = threading.Thread(target=video_send_thread, args=(target_ip, target_vport, media_stop_event), daemon=True)
    audio_send_t = threading.Thread(target=audio_send_thread, args=(target_ip, target_aport, media_stop_event), daemon=True)
    video_send_t.start()
    audio_send_t.start()
    # start flask preview
    flask_t = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=FLASK_PORT, debug=False, use_reloader=False), daemon=True)
    flask_t.start()
    in_call.set()
    print(f"[CALL] Media streams started. Local preview http://0.0.0.0:{FLASK_PORT}")

def stop_call():
    global media_stop_event, video_send_t, audio_send_t, video_server_t, audio_server_t, partner, in_call
    if not in_call.is_set():
        return
    print("[CALL] Stopping call...")
    # signal media threads to stop
    if media_stop_event:
        media_stop_event.set()
    # join threads briefly (they are daemon so will exit)
    time.sleep(0.5)
    media_stop_event = None
    partner = None
    in_call.clear()
    print("[CALL] stopped")

# ------------------ Main client program ------------------
def interactive_loop(sock: socket.socket):
    global partner, tcp_sock
    print("Commands:")
    print(" - broadcast: /b your message")
    print(" - private:   /p username your message")
    print(" - call:      /call username")
    print(" - end call:  /end")
    print(" - quit:      /quit")
    while running.is_set():
        try:
            line = input().strip()
            if not line:
                continue
            if line.startswith("/b "):
                msg = line[3:].strip()
                safe_send(sock, {"type": "broadcast", "msg": msg})
            elif line.startswith("/p "):
                rest = line[3:].strip()
                target, _, msg = rest.partition(" ")
                safe_send(sock, {"type": "msg", "to": target, "msg": msg})
            elif line.startswith("/call "):
                target = line.split(" ", 1)[1].strip()
                if in_call.is_set():
                    print("[INFO] Already in a call. End it first.")
                    continue
                # start local listeners
                ip, vport, aport = start_media_listeners()
                # register local ports with server
                safe_send(sock, {"type": "call", "to": target})
                # wait briefly for server to ask for ports or for acceptance; our server expects port exchange after '200'
                # To keep things robust: sleep small time then send ports packet
                time.sleep(0.2)
                safe_send(sock, {"type": "ports", "ip": ip, "video_port": vport, "audio_port": aport})
                # partner ports will arrive later via server 'ports' packet
            elif line == "/end":
                if in_call.is_set():
                    safe_send(sock, {"type": "end_call"})
                    stop_call()
                else:
                    print("No active call.")
            elif line == "/quit":
                running.clear()
                safe_send(sock, {"type": "quit"})
                try:
                    sock.close()
                except:
                    pass
                break
            else:
                # default: broadcast as message
                safe_send(sock, {"type": "broadcast", "msg": line})
        except Exception as e:
            print(f"[WARN] interactive_loop error: {e}")
            break

def start_client():
    global tcp_sock, username
    username = input("Enter username: ").strip()
    if not username:
        print("Username required.")
        return

    try:
        tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_sock.connect((SERVER_IP, SERVER_PORT))
    except Exception as e:
        print(f"[ERROR] Could not connect to server: {e}")
        return

    # register
    safe_send(tcp_sock, {"type": "register", "username": username})
    # start listener
    t = threading.Thread(target=tcp_listener, args=(tcp_sock,), daemon=True)
    t.start()
    # start interactive loop on main thread
    interactive_loop(tcp_sock)
    # cleanup
    running.clear()
    stop_call()
    try:
        tcp_sock.close()
    except:
        pass
    print("Client exiting.")

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
