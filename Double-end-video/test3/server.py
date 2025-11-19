#!/usr/bin/env python3
"""
Reliable TCP chat + call signaling server.
Protocol: JSON lines, newline-terminated.
Matches client.py exactly.
"""

import socket
import threading
import json

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
# ------------ Reliable Call Signaling --------------
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

    receiver_sock = clients[receiver]
    caller_sock = clients[caller]

    # Notify receiver
    safe_send(receiver_sock, {"type": "incoming_call", "from": caller})

    # Wait for answer
    def wait_for_answer():
        try:
            receiver_sock.settimeout(20)
            raw = receiver_sock.recv(4096).decode().strip()
            ans = json.loads(raw)
            if ans.get("type") != "call_answer" or ans.get("answer") != "yes":
                safe_send(caller_sock, {"type": "call_rejected"})
                return

            # Both accepted
            safe_send(caller_sock, {"type": "call_accept"})
            safe_send(receiver_sock, {"type": "call_accept"})

            with clients_lock:
                busy[caller] = receiver
                busy[receiver] = caller

            print(f"[CALL] {caller} <--> {receiver} CONNECTED")

        except:
            safe_send(caller_sock, {"type": "error", "msg": "Receiver did not answer"})

    threading.Thread(target=wait_for_answer, daemon=True).start()

# ---------------------------------------------------
# ---------------- Packet Handler --------------------
# ---------------------------------------------------
def handle_packet(username, sock, packet):
    ptype = packet.get("type")

    if ptype == "msg":
        to_user = packet.get("to")
        text = packet.get("msg")
        with clients_lock:
            if to_user in clients:
                safe_send(clients[to_user], {"type": "msg", "from": username, "msg": text})
            else:
                safe_send(sock, {"type": "error", "msg": "User not found"})

    elif ptype == "broadcast":
        with clients_lock:
            for u, s in clients.items():
                if u != username:
                    safe_send(s, {"type": "msg", "from": username, "msg": packet.get("msg")})

    elif ptype == "call":
        to_user = packet.get("to")
        initiate_call(username, to_user)

    elif ptype == "end_call":
        with clients_lock:
            if username in busy:
                partner = busy.pop(username)
                busy.pop(partner, None)
                if partner in clients:
                    safe_send(clients[partner], {"type": "call_ended", "from": username})
                print(f"[CALL] Ended: {username} <--> {partner}")

    elif ptype == "ports":
        with clients_lock:
            if username not in busy:
                safe_send(sock, {"type": "error", "msg": "Not in a call"})
                return
            partner = busy[username]
            if partner not in clients:
                return
            safe_send(clients[partner], {
                "type": "ports",
                "from": username,
                "ip": packet.get("ip"),
                "video_port": packet.get("video_port"),
                "audio_port": packet.get("audio_port")
            })

# ---------------------------------------------------
# ---------------- Client Thread ---------------------
# ---------------------------------------------------
def client_thread(sock):
    username = None
    try:
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

        while True:
            raw = sock.recv(4096)
            if not raw:
                break
            for line in raw.decode().split("\n"):
                line = line.strip()
                if not line:
                    continue
                try:
                    pkt = json.loads(line)
                    handle_packet(username, sock, pkt)
                except:
                    safe_send(sock, {"type": "error", "msg": "Invalid JSON"})

    except:
        pass
    finally:
        cleanup_user(username, sock)

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
                safe_send(clients[partner], {"type": "call_ended", "from": username})
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