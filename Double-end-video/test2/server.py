import socket
import threading
import json
import time

HOST = "10.75.16.29"
PORT = 5000

clients = {}        # username -> socket
busy = {}           # username -> partner
clients_lock = threading.Lock()


# ---------------------------------------------------
# ------------ Utility Send Function ----------------
# ---------------------------------------------------
def safe_send(sock, data: dict):
    """Safely send JSON dictionary over TCP."""
    try:
        packet = json.dumps(data) + "\n"
        sock.sendall(packet.encode())
    except:
        pass


# ---------------------------------------------------
# ------------ Reliable Call Signaling ---------------
# ---------------------------------------------------
def initiate_call(caller, receiver):
    """Caller requests a call with receiver."""
    with clients_lock:
        if receiver not in clients:
            safe_send(clients[caller], {"type": "error", "msg": "Receiver offline"})
            return

        if receiver in busy:
            safe_send(clients[caller], {"type": "error", "msg": "User busy"})
            return

        caller_sock = clients[caller]
        receiver_sock = clients[receiver]

    # Send incoming call notification
    safe_send(receiver_sock, {
        "type": "incoming_call",
        "from": caller
    })

    # Wait for response without blocking the entire thread
    def wait_for_answer():
        try:
            receiver_sock.settimeout(20)
            ans_raw = receiver_sock.recv(2048).decode().strip()
        except:
            safe_send(caller_sock, {"type": "error", "msg": "Receiver did not answer"})
            return

        try:
            ans = json.loads(ans_raw)
        except:
            safe_send(caller_sock, {"type": "error", "msg": "Invalid response"})
            return

        if ans.get("type") != "call_answer":
            safe_send(caller_sock, {"type": "error", "msg": "Invalid packet"})
            return

        if ans.get("answer") != "yes":
            safe_send(caller_sock, {"type": "call_rejected"})
            return

        # Both agreed → request UDP ports
        safe_send(caller_sock, {"type": "call_accept"})
        safe_send(receiver_sock, {"type": "call_accept"})

        # UDP Port exchange
        try:
            p1 = caller_sock.recv(1024).decode().strip()
            p2 = receiver_sock.recv(1024).decode().strip()

            caller_sock.sendall(p2.encode())
            receiver_sock.sendall(p1.encode())
        except:
            safe_send(caller_sock, {"type": "error", "msg": "UDP exchange failed"})
            safe_send(receiver_sock, {"type": "error", "msg": "UDP exchange failed"})
            return

        with clients_lock:
            busy[caller] = receiver
            busy[receiver] = caller

        print(f"[CALL] {caller} <--> {receiver} CONNECTED")

    threading.Thread(target=wait_for_answer, daemon=True).start()


# ---------------------------------------------------
# ---------------- Client Thread ---------------------
# ---------------------------------------------------
def client_thread(sock):
    username = None

    try:
        # first packet must be username
        raw = sock.recv(1024).decode().strip()
        data = json.loads(raw)
        username = data.get("username")

        if not username:
            safe_send(sock, {"type": "error", "msg": "Username missing"})
            sock.close()
            return

        with clients_lock:
            clients[username] = sock

        print(f"[+] {username} connected")

        # main loop
        while True:
            raw = sock.recv(4096)
            if not raw:
                break

            for line in raw.decode().split("\n"):
                if not line.strip():
                    continue

                try:
                    packet = json.loads(line)
                except:
                    safe_send(sock, {"type": "error", "msg": "Invalid JSON"})
                    continue

                handle_packet(username, sock, packet)

    except:
        pass
    finally:
        cleanup_user(username, sock)


# ---------------------------------------------------
# ---------------- Packet Handler --------------------
# ---------------------------------------------------
def handle_packet(username, sock, packet):
    ptype = packet.get("type")

    # ---------- Send chat message ----------
    if ptype == "msg":
        to_user = packet.get("to")
        text = packet.get("msg")

        with clients_lock:
            if to_user in clients:
                safe_send(clients[to_user], {
                    "type": "msg",
                    "from": username,
                    "msg": text
                })
            else:
                safe_send(sock, {"type": "error", "msg": "User not found"})

    # ---------- Start call ----------
    elif ptype == "call":
        to_user = packet.get("to")
        initiate_call(username, to_user)

    # ---------- End call ----------
    elif ptype == "end_call":
        with clients_lock:
            if username in busy:
                partner = busy.pop(username)
                busy.pop(partner, None)

                if partner in clients:
                    safe_send(clients[partner], {
                        "type": "call_ended",
                        "from": username
                    })

                print(f"[CALL] Ended: {username} <--> {partner}")


# ---------------------------------------------------
# ---------------- Cleanup User ----------------------
# ---------------------------------------------------
def cleanup_user(username, sock):
    with clients_lock:
        if username in clients:
            del clients[username]

        if username in busy:
            partner = busy.pop(username)
            busy.pop(partner, None)
            if partner in clients:
                safe_send(clients[partner], {"type": "call_ended", "msg": "User disconnected"})

    try:
        sock.close()
    except:
        pass

    print(f"[-] {username} disconnected")


# ---------------------------------------------------
# -------------------- Server ------------------------
# ---------------------------------------------------
def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen(50)

    print(f"\nServer running on {HOST}:{PORT}\n")

    while True:
        sock, addr = server.accept()
        print(f"[NEW] Connection from {addr}")
        threading.Thread(target=client_thread, args=(sock,), daemon=True).start()


if __name__ == "__main__":
    start_server()
