import cv2
import socket
import threading
import numpy as np
import pyaudio
from flask import Flask, Response
import time

SERVER_IP = "10.75.16.29"   # Update to your server's IP
SERVER_PORT = 5000
app = Flask(__name__)

latest_frame = None  # Global video frame
streaming = False  # Flag to control streaming
stop_call = False  # Flag to stop call gracefully
frame_lock = threading.Lock()  # For thread-safe access to latest_frame
current_partner = None  # Track the current call partner for end-call notification

# ----------------------------- VIDEO STREAM -----------------------------
def send_video(IP, VIDEO_PORT):
    global streaming, stop_call
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((IP, VIDEO_PORT))
        cap = cv2.VideoCapture(0)
        while streaming and not stop_call:
            ret, frame = cap.read()
            if not ret:
                break
            _, buffer = cv2.imencode(".jpg", frame)
            sock.sendall(buffer.tobytes() + b"FRAME_END")
            time.sleep(0.03)  # ~30 FPS
        cap.release()
        sock.close()
    except Exception as e:
        print(f"[ERROR] Video send failed: {e}")

# ----------------------------- AUDIO STREAM -----------------------------
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

def send_audio(IP, AUDIO_PORT):
    global streaming, stop_call
    try:
        audio = pyaudio.PyAudio()
        mic = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                         input=True, frames_per_buffer=CHUNK)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((IP, AUDIO_PORT))
        while streaming and not stop_call:
            data = mic.read(CHUNK)
            sock.sendall(data)
        mic.close()
        sock.close()
    except Exception as e:
        print(f"[ERROR] Audio send failed: {e}")

# ----------------------------- AUDIO SETUP -----------------------------
p = pyaudio.PyAudio()
audio_stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True)

def audio_receiver(AUDIO_PORT):
    global stop_call
    try:
        audio_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        audio_socket.bind(("0.0.0.0", AUDIO_PORT))
        audio_socket.listen(1)
        conn, addr = audio_socket.accept()
        print("[CLIENT] Audio connected:", addr)
        while not stop_call:
            audio_data = conn.recv(CHUNK * 2)
            if not audio_data:
                break
            audio_stream.write(audio_data)
        conn.close()
    except Exception as e:
        print(f"[ERROR] Audio receive failed: {e}")

# ----------------------------- VIDEO RECEIVER -----------------------------
def video_receiver(VIDEO_PORT):
    global latest_frame, stop_call
    try:
        vid_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        vid_socket.bind(("0.0.0.0", VIDEO_PORT))
        vid_socket.listen(1)
        conn, addr = vid_socket.accept()
        print("[CLIENT] Video connected:", addr)
        buffer = b""
        while not stop_call:
            data = conn.recv(65536)
            if not data:
                break
            buffer += data
            while b"FRAME_END" in buffer:
                frame_data, buffer = buffer.split(b"FRAME_END", 1)
                frame = np.frombuffer(frame_data, np.uint8)
                frame = cv2.imdecode(frame, cv2.IMREAD_COLOR)
                if frame is not None:
                    with frame_lock:
                        latest_frame = frame
        conn.close()
    except Exception as e:
        print(f"[ERROR] Video receive failed: {e}")

# ----------------------------- FLASK VIDEO STREAM -----------------------------
def generate_video():
    global latest_frame
    while True:
        with frame_lock:
            if latest_frame is not None:
                ret, jpeg = cv2.imencode(".jpg", latest_frame)
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")
        time.sleep(0.03)

@app.route("/")
def index():
    return "<h1>Video Stream</h1><img src='/video'>"

@app.route("/video")
def video():
    return Response(generate_video(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")

def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port

def get_my_ip():
    return socket.gethostbyname(socket.gethostname())  # Adjust if behind NAT

def receive_messages(sock):
    global streaming, stop_call, current_partner
    while not stop_call:
        try:
            msg = sock.recv(2048).decode()
            if not msg:
                break
            if "::: calling" in msg:
                from_u, text = msg.split(":::", 1)
                print(f"\n{from_u} is calling you")
                ans = input("Enter Y/N: ")
                sock.send(ans.encode())
                if ans.lower() == 'y':
                    _ = sock.recv(1024)
                    port1 = get_free_port()
                    threading.Thread(target=video_receiver, args=[port1], daemon=True).start()
                    port2 = get_free_port()
                    threading.Thread(target=audio_receiver, args=[port2], daemon=True).start()
                    my_ip = get_my_ip()
                    message = f"{my_ip}:{port1}:{port2}"
                    sock.send(message.encode())
                    msg = sock.recv(1024).decode()
                    IP, port3, port4 = msg.split(":", 2)
                    threading.Thread(target=send_video, args=[IP, int(port3)], daemon=True).start()
                    threading.Thread(target=send_audio, args=[IP, int(port4)], daemon=True).start()
                    streaming = True
                    current_partner = from_u  # Track partner
                    flask_thread = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000, debug=False), daemon=True)
                    flask_thread.start()
                    print("[CLIENT] Running Flask on http://0.0.0.0:5000")
                    print("Type 'endcall' to stop the call.")
                else:
                    continue
            print("\n" + msg)
        except Exception as e:
            print(f"[ERROR] Message receive failed: {e}")
            break

def client_program():
    global stop_call, current_partner
    username = input("Enter your username: ")
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect((SERVER_IP, SERVER_PORT))
    client.send(username.encode())
    print("Connected! Type messages.")
    print("Private message format: username:::message")
    print("To call: call username")
    threading.Thread(target=receive_messages, args=(client,), daemon=True).start()
    
    while not stop_call:
        msg = input()
        if msg.lower() == "quit":
            stop_call = True
            client.close()
            break
        elif msg.lower() == "endcall":
            if current_partner:
                client.send(f"{current_partner}:::204".encode())  # Notify server to end call
            stop_call = True
            streaming = False
            current_partner = None
            print("Call ended.")
            continue
        elif msg.startswith("call "):
            target = msg.split(" ", 1)[1]
            client.send(f"{target}::: calling".encode())
            try:
                response = client.recv(1024).decode()
                if response == "200":
                    port3 = get_free_port()
                    threading.Thread(target=video_receiver, args=[port3], daemon=True).start()
                    port4 = get_free_port()
                    threading.Thread(target=audio_receiver, args=[port4], daemon=True).start()
                    my_ip = get_my_ip()
                    message = f"{my_ip}:{port3}:{port4}"
                    client.send(message.encode())
                    msg = client.recv(1024).decode()
                    IP, port1, port2 = msg.split(":", 2)
                    threading.Thread(target=send_video, args=[IP, int(port1)], daemon=True).start()
                    threading.Thread(target=send_audio, args=[IP, int(port2)], daemon=True).start()
                    streaming = True
                    current_partner = target
                    flask_thread = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000, debug=False), daemon=True)
                    flask_thread.start()
                    print("[CLIENT] Running Flask on http://0.0.0.0:5000")
                    print("Type 'endcall' to stop the call.")
                elif response == "400":
                    print("Call declined.")
                else:
                    print(f"Call response: {response}")
            except Exception as e:
                print(f"[ERROR] Call initiation failed: {e}")
        else:
            client.send(msg.encode())

if __name__ == "__main__":
    client_program()
