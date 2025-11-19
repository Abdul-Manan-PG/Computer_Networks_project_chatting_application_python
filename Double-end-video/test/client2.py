import cv2
import socket
import threading
import numpy as np
import pyaudio
from flask import Flask, Response
import time
import sys

SERVER_IP = "10.75.26.20"
SERVER_PORT = 5000
app = Flask(__name__)

# Global State
latest_frame = None
streaming = False
stop_call = False
frame_lock = threading.Lock()
current_partner = None
tcp_socket = None

# ----------------------------- VIDEO SEND -----------------------------
def send_video(ip, port):
    global streaming, stop_call
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((ip, port))
        cap = cv2.VideoCapture(0)

        while streaming and not stop_call:
            ok, frame = cap.read()
            if not ok:
                break
            _, buf = cv2.imencode(".jpg", frame)
            s.sendall(buf.tobytes() + b"FRAME_END")
            time.sleep(0.03)

        cap.release()
        s.close()
    except:
        pass

# ----------------------------- AUDIO SEND -----------------------------
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

def send_audio(ip, port):
    global streaming, stop_call
    try:
        p = pyaudio.PyAudio()
        mic = p.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                     input=True, frames_per_buffer=CHUNK)

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((ip, port))

        while streaming and not stop_call:
            data = mic.read(CHUNK)
            s.sendall(data)

        mic.close()
        s.close()
    except:
        pass

# ----------------------------- AUDIO RECEIVE -----------------------------
p = pyaudio.PyAudio()
speaker = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True)

def audio_receiver(port):
    global stop_call
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("0.0.0.0", port))
        s.listen(1)
        conn, _ = s.accept()

        while not stop_call:
            data = conn.recv(CHUNK * 2)
            if not data:
                break
            speaker.write(data)

        conn.close()
    except:
        pass

# ----------------------------- VIDEO RECEIVE -----------------------------
def video_receiver(port):
    global latest_frame, stop_call

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("0.0.0.0", port))
        s.listen(1)
        conn, _ = s.accept()

        buffer = b""
        while not stop_call:
            data = conn.recv(65536)
            if not data:
                break

            buffer += data
            while b"FRAME_END" in buffer:
                frame_raw, buffer = buffer.split(b"FRAME_END", 1)
                frame = cv2.imdecode(np.frombuffer(frame_raw, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    with frame_lock:
                        latest_frame = frame

        conn.close()
    except:
        pass

# ----------------------------- FLASK STREAM -----------------------------
def generate_video():
    global latest_frame
    while True:
        with frame_lock:
            if latest_frame is not None:
                _, jpeg = cv2.imencode(".jpg", latest_frame)
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
        time.sleep(0.03)

@app.route("/")
def index():
    return "<h1>Live Call Video</h1><img src='/video'>"

@app.route("/video")
def video():
    return Response(generate_video(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

# ----------------------------- UTILS -----------------------------
def get_free_port():
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port

def get_my_ip():
    return socket.gethostbyname(socket.gethostname())

# ----------------------------- TCP LISTENER -----------------------------
def tcp_listener(sock):
    global stop_call, streaming, current_partner

    while True:
        try:
            msg = sock.recv(2048).decode()
            if not msg:
                print("[TCP] Server disconnected.")
                sys.exit()

            print(msg)

            # ------------ CALL INCOMING ------------
            if msg.startswith("[CALL]"):
                caller = msg.split(' ', 1)[1]
                print(f"\n{caller} is calling you.")
                ans = input("Accept? (Y/N): ")

                if ans.lower() == "y":
                    sock.send("/accept".encode())

                    # Server sends partner IP and ports
                    info = sock.recv(1024).decode()
                    ip, v_in, a_in, v_out, a_out = info.split(":")

                    # Start receivers
                    threading.Thread(target=video_receiver, args=[int(v_in)], daemon=True).start()
                    threading.Thread(target=audio_receiver, args=[int(a_in)], daemon=True).start()

                    # Start senders
                    threading.Thread(target=send_video, args=[ip, int(v_out)], daemon=True).start()
                    threading.Thread(target=send_audio, args=[ip, int(a_out)], daemon=True).start()

                    streaming = True
                    current_partner = caller

                    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000, debug=False),
                                     daemon=True).start()
                else:
                    sock.send("/reject".encode())

        except Exception as e:
            print("[ERROR LISTENER]", e)
            break

# ----------------------------- MAIN CLIENT -----------------------------
def client_main():
    global tcp_socket, stop_call, streaming, current_partner

    username = input("Enter username: ")
    tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_socket.connect((SERVER_IP, SERVER_PORT))
    tcp_socket.send(username.encode())

    print("""
Commands:
  - broadcast:   /b message
  - private:     /p username message
  - call:        /call username
  - end call:    /end
  - quit:        /quit
""")

    threading.Thread(target=tcp_listener, args=(tcp_socket,), daemon=True).start()

    while True:
        cmd = input()

        if cmd == "/quit":
            tcp_socket.send(cmd.encode())
            stop_call = True
            sys.exit()

        # ------------ MAKE CALL ------------
        if cmd.startswith("/call "):
            target = cmd.split()[1]
            print(f"[INFO] Calling {target}...")
            tcp_socket.send(cmd.encode())
            continue

        # ------------ END CALL ------------
        if cmd == "/end":
            tcp_socket.send(cmd.encode())
            stop_call = True
            streaming = False
            current_partner = None
            print("[CALL ENDED]")
            continue

        # Other messages
        tcp_socket.send(cmd.encode())


if __name__ == "__main__":
    client_main()
