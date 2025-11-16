import socket
import threading
import time
from webserver import update_frame

SERVER_IP = "127.0.0.1"
SERVER_PORT = 9999

def receive_thread(sock):
    while True:
        size_bytes = sock.recv(4)
        if not size_bytes:
            break
        frame_size = int.from_bytes(size_bytes, "big")

        frame = b""
        while len(frame) < frame_size:
            data = sock.recv(frame_size - len(frame))
            if not data:
                break
            frame += data

        update_frame(frame)   # send to Flask viewer


def start_client():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((SERVER_IP, SERVER_PORT))

    threading.Thread(target=receive_thread, args=(sock,), daemon=True).start()

    print("[CLIENT CONNECTED]")

    # polling folder where JS saves webcam frames
    while True:
        try:
            frame = open("current.jpg", "rb").read()
            sock.send(len(frame).to_bytes(4, "big") + frame)
        except:
            pass
        time.sleep(0.03)


if __name__ == "__main__":
    start_client()
