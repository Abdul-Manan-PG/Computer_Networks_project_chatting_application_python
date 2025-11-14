from flask import Flask, render_template, request
import socket
import threading

app = Flask(__name__)
server_running = False
server_thread = None
server_socket = None

HOST = "0.0.0.0"
PORT = 5001

def run_socket_server():
    global server_socket, server_running
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((HOST, PORT))
    server_socket.listen()
    print(f"[SERVER] Listening on {HOST}:{PORT}")

    try:
        while server_running:
            server_socket.settimeout(1)
            try:
                conn, addr = server_socket.accept()
                print(f"[CLIENT CONNECTED] {addr}")
                conn.send(b"Hello from server!")
                conn.close()
            except socket.timeout:
                continue
    except:
        pass

    print("[SERVER] Stopped")
    server_socket.close()


@app.route("/")
def home():
    return render_template("index.html", message="")


@app.post("/start")
def start_server():
    global server_running, server_thread
    msg = ""
    if not server_running:
        server_running = True
        server_thread = threading.Thread(target=run_socket_server)
        server_thread.start()
        print("[WEB] Server started")
        msg = "Server Started!"
    else:
        msg = "Server is already running!"
    return render_template("index.html", message=msg)


@app.post("/stop")
def stop_server():
    global server_running
    msg = ""
    if server_running:
        server_running = False
        print("[WEB] Server stopped")
        msg = "Server Stopped!"
    else:
        msg = "Server is not running!"
    return render_template("index.html", message=msg)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
