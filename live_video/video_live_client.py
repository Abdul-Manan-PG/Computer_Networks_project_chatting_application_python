import cv2
import socket
import threading
import pyaudio
import time
from flask import Flask, render_template

app = Flask(__name__)

SERVER_IP = "10.75.16.45"   # <<< CHANGE THIS
VIDEO_PORT = 9001
AUDIO_PORT = 9002

streaming = False

# ----------------------------- VIDEO STREAM -----------------------------
def send_video():
    global streaming

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_IP, VIDEO_PORT))

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

def send_audio():
    global streaming

    audio = pyaudio.PyAudio()
    mic = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                     input=True, frames_per_buffer=CHUNK)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_IP, AUDIO_PORT))

    while streaming:
        data = mic.read(CHUNK)
        sock.sendall(data)

    mic.close()
    sock.close()

# ----------------------------- FLASK WEB UI -----------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/start")
def start():
    global streaming
    if not streaming:
        streaming = True
        threading.Thread(target=send_video, daemon=True).start()
        threading.Thread(target=send_audio, daemon=True).start()
    return "Streaming Started!"

@app.route("/stop")
def stop():
    global streaming
    streaming = False
    return "Streaming Stopped!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5500)
