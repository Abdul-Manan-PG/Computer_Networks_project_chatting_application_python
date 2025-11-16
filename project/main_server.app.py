from flask import Flask, render_template
import cv2
import socket
import threading
import pyaudio
import time

app = Flask(__name__)

SERVER_IP = "10.75.16.16"
PORT = 5000

server_hosting = False

client = {} #dictionary of clients having their socket

# def get_free_port():
#     with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
#         s.bind(('', 0))  # Bind to any available port
#         port = s.getsockname()[1]  # Get the assigned port number
#     return port

def handle_client(sock):
    try:
        # ---- 1. First message = username ----
        username = sock.recv(1024).decode().strip()
        print(f"[CONNECTED] {username}")

        # Save the socket
        client[username] = sock

        # ---- 2. Main listen loop ----
        while True:
            # Ask: "Whose status do you want?"
            data = sock.recv(1024)
            if not data:
                break  # client disconnected

            target = data.decode().strip()

            # ---- STATUS CHECK ----
            if target in client:
                status = "online"
            else:
                status = "online"

            # Send status back
            sock.send(status.encode())

    except Exception as e:
        print(f"[ERROR] {e}")

    finally:
        # ---- Clean disconnect ----
        if username in client:
            del client[username]
        sock.close()
        print(f"[DISCONNECTED] {username}")


def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((SERVER_IP, PORT))
    server.listen()

    print(f"Server running on PORT {PORT}")

    while True:
        client_socket, _ = server.accept()
        client_socket.send("Connected".encode())
        thread = threading.Thread(target=handle_client, args=(client_socket,))
        thread.daemon = True
        thread.start()

# ----------------------------- FLASK WEB UI -----------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/start")
def start():
    global server_hosting
    if not server_hosting:
        server_hosting = True
        print("Server started.")
    return "Server Started!"

@app.route("/stop")
def stop():
    global server_hosting
    if server_hosting:
        server_hosting = False
        print("Server stopped.")
    return "Server Stopped!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5500)
