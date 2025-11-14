from flask import Flask, render_template_string
import socket
import threading

app = Flask(__name__)
server_running = False
server_thread = None
server_socket = None

HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Server Control</title>
</head>
<body>
    <h1>Socket Server Control</h1>
    <form action="/start" method="post">
        <button type="submit">Start Server</button>
    </form>
    <form action="/stop" method="post">
        <button type="submit">Stop Server</button>
    </form>
</body>
</html>
"""

# Replace "0.0.0.0" with your local IP if needed
HOST = "10.75.27.94"  
PORT = 5001  # TCP port for clients to connect

def run_socket_server():
    global server_socket, server_running

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((HOST, PORT))
    server_socket.listen()
    print(f"[SERVER] Listening on {HOST}:{PORT}")

    try:
        while server_running:
            server_socket.settimeout(1)  # avoid blocking forever
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
    return render_template_string(HTML)

@app.post("/start")
def start_server():
    global server_running, server_thread

    if not server_running:
        server_running = True
        server_thread = threading.Thread(target=run_socket_server)
        server_thread.start()
        print("[WEB] Server started")

    return "Server started! <br><a href='/'>Go Back</a>"

@app.post("/stop")
def stop_server():
    global server_running

    if server_running:
        server_running = False
        print("[WEB] Server stopped")

    return "Server stopped! <br><a href='/'>Go Back</a>"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)  # Web panel accessible to LAN
