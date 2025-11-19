import cv2
import socket
import threading
import numpy as np
import pyaudio
from flask import Flask, Response
import time

SERVER_IP = "10.75.16.16"   # change to server IP for other devices
SERVER_PORT = 5000
My_Ip = "0.0.0.0"
app = Flask(__name__)

latest_frame = None  # Global video frame

streaming = False

# ----------------------------- VIDEO STREAM -----------------------------
def send_video(IP, VIDEO_PORT):
    global streaming

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((IP, VIDEO_PORT))

    cap = cv2.VideoCapture(0)

    while streaming:
        ret, frame = cap.read()
        if not ret:
            break

        _, buffer = cv2.imencode(".jpg", frame)
        sock.sendall(buffer.tobytes() + b"FRAME_END")

        time.sleep(0.03)  # ~30 FPS

    cap.release()
    sock.close()

# ----------------------------- AUDIO STREAM -----------------------------
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

def send_audio(IP, AUDIO_PORT):
    global streaming

    audio = pyaudio.PyAudio()
    mic = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                     input=True, frames_per_buffer=CHUNK)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((IP, AUDIO_PORT))

    while streaming:
        data = mic.read(CHUNK)
        sock.sendall(data)

    mic.close()
    sock.close()

# ----------------------------- AUDIO SETUP -----------------------------

p = pyaudio.PyAudio()
audio_stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True)

def audio_receiver(AUDIO_PORT):
    """Receive audio over TCP and play it."""
    audio_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    audio_socket.bind((My_Ip, AUDIO_PORT))
    audio_socket.listen(1)
    conn, addr = audio_socket.accept()
    print("[SERVER] Audio connected:", addr)

    while True:
        audio_data = conn.recv(CHUNK * 2)
        if not audio_data:
            break
        audio_stream.write(audio_data)

# ----------------------------- VIDEO RECEIVER -----------------------------
def video_receiver(VIDEO_PORT):
    """Receive camera video over TCP."""
    global latest_frame

    vid_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    vid_socket.bind((My_Ip, VIDEO_PORT))
    vid_socket.listen(1)
    conn, addr = vid_socket.accept()
    print("[SERVER] Video connected:", addr)

    buffer = b""

    while True:
        data = conn.recv(65536)
        if not data:
            break

        buffer += data

        while b"FRAME_END" in buffer:
            frame_data, buffer = buffer.split(b"FRAME_END", 1)
            frame = np.frombuffer(frame_data, np.uint8)
            frame = cv2.imdecode(frame, cv2.IMREAD_COLOR)

            if frame is not None:
                latest_frame = frame

# ----------------------------- FLASK VIDEO STREAM -----------------------------
def generate_video():
    global latest_frame
    while True:
        if latest_frame is not None:
            ret, jpeg = cv2.imencode(".jpg", latest_frame)
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")

@app.route("/")
def index():
    return "<h1>Server Video Stream</h1><img src='/video'>"

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

def receive_messages(sock):
    while True:
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
                    port1 = 8999
                    port2 = 8998
                    message = My_Ip + ':' + port1 + ':' + port2
                    sock.send(message.encode())
                    threading.Thread(target=video_receiver,args=[port1], daemon=True).start()
                    threading.Thread(target=audio_receiver,args=[port2], daemon=True).start()
                    msg = sock.recv(1024).decode()
                    IP, port3, port4 = msg.split(":", 2)
                    threading.Thread(target=send_video,args=[IP, port3], daemon=True).start()
                    threading.Thread(target=send_audio,args=[IP, port4], daemon=True).start()
                    print("[SERVER] Running Flask on http://0.0.0.0:5000")
                    app.run(host="0.0.0.0", port=5000)
                else:
                    continue
            print("\n" + msg)
        except:
            break


def client_program():
    username = input("Enter your username: ")

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect((SERVER_IP, SERVER_PORT))

    client.send(username.encode())

    print("Connected! Type messages.")
    print("Private message format: username:::message")

    threading.Thread(target=receive_messages, args=(client,), daemon=True).start()

    while True:
        msg = input()
        if msg.lower() == "quit":
            client.close()
            break
        client.send(msg.encode())


if __name__ == "__main__":
    client_program()
