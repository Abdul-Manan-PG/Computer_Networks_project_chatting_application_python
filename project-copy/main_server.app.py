from flask import Flask, render_template
import socket
import threading

app = Flask(__name__)

SERVER_IP = "10.75.16.16"
PORT = 5000

clients = {}          # {"username": socket}
clients_lock = threading.Lock()


def handle_client(sock):
    username = None
    try:
        # First message must be username
        username = sock.recv(1024).decode().strip()
        print(f"[CONNECTED] {username}")

        with clients_lock:
            clients[username] = sock

        while True:
            data = sock.recv(1024)
            if not data:
                break

            msg = data.decode().strip()

            # Protocol: STATUS:<name>
            if msg.startswith("STATUS:"):
                target = msg.split(":", 1)[1]

                with clients_lock:
                    status = "online" if target in clients else "offline"

                sock.send(status.encode())

    except Exception as e:
        print(f"[ERROR] {e}")

    finally:
        # remove client safely
        if username:
            with clients_lock:
                if username in clients:
                    del clients[username]

        sock.close()
        print(f"[DISCONNECTED] {username}")


def start_tcp_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((SERVER_IP, PORT))
    server.listen()
    print(f"[TCP SERVER] Running at {SERVER_IP}:{PORT}")

    while True:
        sock, addr = server.accept()
        threading.Thread(target=handle_client, args=(sock,), daemon=True).start()


# ----------------------------- FLASK UI -----------------------------
@app.route("/")
def index():
    return render_template("index.html")


# Start TCP server in background
threading.Thread(target=start_tcp_server, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5500)
