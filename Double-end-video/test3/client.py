#!/usr/bin/env python3
"""
Reliable TCP client for chat + call signaling + media streaming.
Protocol (JSON lines, newline-terminated):
- Register: {"type":"register", "username":"bob"}
- Chat:     {"type":"msg", "to":"alice", "msg":"hello"}
            OR {"type":"broadcast", "msg":"hi all"}
- Call:     {"type":"call", "to":"alice"}
- Answer:   {"type":"call_answer", "answer":"yes" / "no"}
- Ports:    {"type":"ports", "ip":"1.2.3.4", "video_port":5001, "audio_port":5002}
- End call: {"type":"end_call"}
"""

import socket, threading, json, struct, time, sys, cv2, numpy as np, pyaudio
from flask import Flask, Response

# ---------------- CONFIG ----------------
SERVER_IP   = "10.75.16.29"   # <-- change if your server is elsewhere
SERVER_PORT = 5000
VIDEO_FPS   = 20
VIDEO_QUALITY = 80              # JPEG 0-100
CHUNK       = 1024
FORMAT      = pyaudio.paInt16
CHANNELS    = 1
RATE        = 44100
FLASK_PORT  = 5000              # local preview web UI
# ----------------------------------------

app = Flask(__name__)

tcp_sock = None
tcp_lock = threading.Lock()
username = None
running  = threading.Event(); running.set()
in_call  = threading.Event()
partner  = None

latest_frame = None
frame_lock   = threading.Lock()

pyaudio_inst = pyaudio.PyAudio()
audio_out_stream = None

# -------------- Networking utils --------------
def safe_send(sock: socket.socket, obj: dict):
    try:
        with tcp_lock:
            sock.sendall((json.dumps(obj) + "\n").encode())
    except Exception as e:
        print(f"[WARN] safe_send failed: {e}")

def recv_line_from_socket(sock: socket.socket):
    """Return one JSON line or None on disconnect/timeout."""
    sock.settimeout(0.5)
    data = getattr(sock, "leftover", b"")
    try:
        while running.is_set():
            if b"\n" in data:
                line, data = data.split(b"\n", 1)
                sock.leftover = data
                return line.decode()
            chunk = sock.recv(4096)
            if not chunk:
                return None
            data += chunk
    except socket.timeout:
        return None
    except Exception as e:
        print(f"[WARN] recv_line_from_socket: {e}")
        return None

# -------------- Media framing --------------
def send_framed(conn: socket.socket, raw: bytes):
    try:
        conn.sendall(struct.pack("!I", len(raw)) + raw)
    except Exception as e:
        print(f"[ERROR] send_framed: {e}")

def recv_framed(conn: socket.socket):
    try:
        header = conn.recv(4)
        if not header:
            return None
        size = struct.unpack("!I", header)[0]
        data = b""
        while len(data) < size:
            chunk = conn.recv(min(65536, size - len(data)))
            if not chunk:
                return None
            data += chunk
        return data
    except:
        return None

# -------------- Utility --------------
def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]

def get_my_ip():
    try:
        return socket.gethostbyname(socket.gethostname())
    except:
        return "127.0.0.1"

# -------------- Flask preview --------------
def generate_video():
    while running.is_set():
        with frame_lock:
            if latest_frame is not None:
                ok, jpg = cv2.imencode(".jpg", latest_frame, [int(cv2.IMWRITE_JPEG_QUALITY), VIDEO_QUALITY])
                if ok:
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n")
        time.sleep(1.0 / VIDEO_FPS)

@app.route("/")
def index():
    return "<h3>Local Preview</h3><img src='/video'/>"

@app.route("/video")
def video_feed():
    return Response(generate_video(), mimetype="multipart/x-mixed-replace; boundary=frame")

# -------------- Media sender threads --------------
def video_send_thread(target_ip, target_port, stop_event: threading.Event):
    cap = sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((target_ip, target_port))
        sock.settimeout(None)
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("[ERROR] Camera not available"); return
        print(f"[VIDEO SEND] connected -> {target_ip}:{target_port}")
        while running.is_set() and not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05); continue
            ok, enc = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), VIDEO_QUALITY])
            if ok:
                send_framed(sock, enc.tobytes())
            time.sleep(1.0 / VIDEO_FPS)
    except Exception as e:
        print(f"[ERROR] video_send_thread: {e}")
    finally:
        if cap: cap.release()
        if sock: sock.close()
        print("[VIDEO SEND] stopped")

def audio_send_thread(target_ip, target_port, stop_event: threading.Event):
    sock = mic = None
    try:
        mic = pyaudio_inst.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((target_ip, target_port))
        sock.settimeout(None)
        print(f"[AUDIO SEND] connected -> {target_ip}:{target_port}")
        while running.is_set() and not stop_event.is_set():
            send_framed(sock, mic.read(CHUNK, exception_on_overflow=False))
    except Exception as e:
        print(f"[ERROR] audio_send_thread: {e}")
    finally:
        if mic: mic.stop_stream(); mic.close()
        if sock: sock.close()
        print("[AUDIO SEND] stopped")

# -------------- Media receiver servers --------------
def video_server_thread(listen_port, stop_event: threading.Event):
    server = conn = None
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", listen_port))
        server.listen(1)
        server.settimeout(10)
        conn, addr = server.accept()
        conn.settimeout(None)
        print(f"[VIDEO RECV] connection from {addr}")
        global latest_frame
        while running.is_set() and not stop_event.is_set():
            payload = recv_framed(conn)
            if payload is None:
                break
            img = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
            if img is not None:
                with frame_lock:
                    latest_frame = img
    except Exception as e:
        print(f"[ERROR] video_server_thread: {e}")
    finally:
        if conn: conn.close()
        if server: server.close()
        print("[VIDEO RECV] stopped")

def audio_server_thread(listen_port, stop_event: threading.Event):
    global audio_out_stream
    server = conn = None
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("0.0.0.0", listen_port))
        server.listen(1)
        if audio_out_stream is None:
            audio_out_stream = pyaudio_inst.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True, frames_per_buffer=CHUNK)
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
            except:
                pass
    except Exception as e:
        print(f"[ERROR] audio_server_thread: {e}")
    finally:
        if conn: conn.close()
        if server: server.close()
        print("[AUDIO RECV] stopped")

# -------------- TCP listener --------------
def tcp_listener(sock: socket.socket):
    global partner, in_call
    while running.is_set():
        line = recv_line_from_socket(sock)
        if line is None:
            print("[TCP] Server closed connection."); running.clear(); break
        try:
            pkt = json.loads(line)
        except:
            print(f"[TCP] non-JSON: {line}"); continue
        ptype = pkt.get("type")
        if ptype == "msg":
            print(f"\n[{pkt.get('from')}] {pkt.get('msg')}")
        elif ptype == "error":
            print(f"\n[SERVER ERROR] {pkt.get('msg')}")
        elif ptype == "incoming_call":
            caller = pkt.get("from")
            print(f"\n[CALL] Incoming call from {caller}")
            ans = None
            while ans not in ("y", "n"):
                ans = input("Accept call? (y/n): ").strip().lower()
            safe_send(sock, {"type": "call_answer", "answer": "yes" if ans == "y" else "no"})
        elif ptype == "call_accept":
            print("[CALL] Partner accepted; exchanging ports...")
        elif ptype == "call_rejected":
            print("[CALL] Call was rejected by partner.")
        elif ptype == "ports":
            partner = pkt.get("from")
            their_ip = pkt.get("ip")
            their_vport = int(pkt.get("video_port"))
            their_aport = int(pkt.get("audio_port"))
            print(f"[CALL] Received partner endpoints {their_ip}:{their_vport} (video), {their_ip}:{their_aport} (audio)")
            start_media_streams(their_ip, their_vport, their_aport)
        elif ptype == "call_ended":
            print(f"[CALL] Partner ended call: {pkt.get('from')}")
            stop_call()
        else:
            print(f"[TCP] {pkt}")

# -------------- Call flow helpers --------------
media_stop_event = None
video_send_t = audio_send_t = video_server_t = audio_server_t = flask_t = None
video_listen_port = audio_listen_port = None

def start_media_listeners():
    global video_listen_port, audio_listen_port, video_server_t, audio_server_t, media_stop_event
    media_stop_event = threading.Event()
    video_listen_port = get_free_port()
    audio_listen_port = get_free_port()
    video_server_t = threading.Thread(target=video_server_thread, args=(video_listen_port, media_stop_event), daemon=True)
    audio_server_t = threading.Thread(target=audio_server_thread, args=(audio_listen_port, media_stop_event), daemon=True)
    video_server_t.start(); audio_server_t.start()
    return get_my_ip(), video_listen_port, audio_listen_port

def start_media_streams(target_ip, target_vport, target_aport):
    global media_stop_event, video_send_t, audio_send_t, flask_t
    if media_stop_event is None:
        media_stop_event = threading.Event()
    video_send_t = threading.Thread(target=video_send_thread, args=(target_ip, target_vport, media_stop_event), daemon=True)
    audio_send_t = threading.Thread(target=audio_send_thread, args=(target_ip, target_aport, media_stop_event), daemon=True)
    video_send_t.start(); audio_send_t.start()
    flask_t = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=FLASK_PORT, debug=False, use_reloader=False), daemon=True)
    flask_t.start()
    in_call.set()
    print(f"[CALL] Media streams started. Local preview: http://0.0.0.0:{FLASK_PORT}")

def stop_call():
    global media_stop_event, partner, in_call
    if not in_call.is_set():
        return
    print("[CALL] Stopping call...")
    if media_stop_event:
        media_stop_event.set()
    time.sleep(0.5)
    media_stop_event = None
    partner = None
    in_call.clear()
    print("[CALL] stopped")

# -------------- Main client program --------------
def interactive_loop(sock: socket.socket):
    print("Commands:\n - broadcast: /b your message\n - private:   /p username your message\n - call:      /call username\n - end call:  /end\n - quit:      /quit")
    while running.is_set():
        try:
            line = input().strip()
            if not line:
                continue
            if line.startswith("/b "):
                safe_send(sock, {"type": "broadcast", "msg": line[3:].strip()})
            elif line.startswith("/p "):
                rest = line[3:].strip()
                target, _, msg = rest.partition(" ")
                safe_send(sock, {"type": "msg", "to": target, "msg": msg})
            elif line.startswith("/call "):
                target = line.split(" ", 1)[1].strip()
                if in_call.is_set():
                    print("[INFO] Already in a call. End it first."); continue
                ip, vport, aport = start_media_listeners()
                safe_send(sock, {"type": "call", "to": target})
                time.sleep(0.2)
                safe_send(sock, {"type": "ports", "ip": ip, "video_port": vport, "audio_port": aport})
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
                safe_send(sock, {"type": "broadcast", "msg": line})
        except Exception as e:
            print(f"[WARN] interactive_loop: {e}")
            break

def start_client():
    global tcp_sock, username
    username = input("Enter username: ").strip()
    if not username:
        print("Username required."); return
    try:
        tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_sock.connect((SERVER_IP, SERVER_PORT))
    except Exception as e:
        print(f"[ERROR] Could not connect to server: {e}"); return
    safe_send(tcp_sock, {"type": "register", "username": username})
    threading.Thread(target=tcp_listener, args=(tcp_sock,), daemon=True).start()
    interactive_loop(tcp_sock)
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
            tcp_sock.close()
        except:
            pass
        print("\nInterrupted, exiting.")
        sys.exit(0)