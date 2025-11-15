import cv2
import socket
import threading
import numpy as np
import pyaudio
from flask import Flask, Response

app = Flask(__name__)

latest_frame = None  # Global video frame

TCP_IP = "10.75.16.45"
VIDEO_PORT = 9001
AUDIO_PORT = 9002

# ----------------------------- AUDIO SETUP -----------------------------
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

p = pyaudio.PyAudio()
audio_stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True)

def audio_receiver():
    """Receive audio over TCP and play it."""
    audio_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    audio_socket.bind((TCP_IP, AUDIO_PORT))
    audio_socket.listen(1)
    conn, addr = audio_socket.accept()
    print("[SERVER] Audio connected:", addr)

    while True:
        audio_data = conn.recv(CHUNK * 2)
        if not audio_data:
            break
        audio_stream.write(audio_data)

# ----------------------------- VIDEO RECEIVER -----------------------------
def video_receiver():
    """Receive camera video over TCP."""
    global latest_frame

    vid_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    vid_socket.bind((TCP_IP, VIDEO_PORT))
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

# ----------------------------- MAIN -----------------------------
if __name__ == "__main__":
    threading.Thread(target=video_receiver, daemon=True).start()
    threading.Thread(target=audio_receiver, daemon=True).start()

    print("[SERVER] Running Flask on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000)
