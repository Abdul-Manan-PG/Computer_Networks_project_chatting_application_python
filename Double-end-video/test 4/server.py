import socket
import threading
import json
import time
import sys

# CONFIG (Use 0.0.0.0 for listening on all interfaces)
HOST = "0.0.0.0" 
PORT = 5000

clients = {}        # username -> socket
busy = {}           # username -> partner
clients_lock = threading.Lock()


# ---------------------------------------------------
# ------------ Utility Send Function ----------------
# ---------------------------------------------------
def safe_send(sock, data: dict) -> bool:
    """Safely send JSON dictionary over TCP. Returns True on success."""
    try:
        packet = json.dumps(data) + "\n"
        sock.sendall(packet.encode("utf-8"))
        return True # SUCCESS
    except Exception as e:
        # Log the failure for debugging the network issue
        try:
             # Attempt to get the remote address for logging
            peername = sock.getpeername()
            print(f"[WARN] safe_send failed to {peername}: {e}", file=sys.stderr)
        except:
            print(f"[WARN] safe_send failed (socket error): {e}", file=sys.stderr)
        return False # FAILURE

# ---------------------------------------------------
# ------------ Packet Receiver Utility ---------------
# ---------------------------------------------------
# Helper to read one JSON packet line from a socket buffer
def recv_packet_line(sock, timeout=None):
    """Reads a single newline-terminated JSON line from the socket buffer."""
    sock.settimeout(timeout)
    buffer = getattr(sock, 'leftover', b'')
    try:
        while True:
            # Check leftover first
            if b"\n" in buffer:
                line, rest = buffer.split(b"\n", 1)
                sock.leftover = rest
                return line.decode("utf-8")

            chunk = sock.recv(4096)
            if not chunk:
                return None # Connection closed
            buffer += chunk

    except socket.timeout:
        sock.leftover = buffer
        return None
    except Exception as e:
        # print(f"[ERROR] recv_packet_line error: {e}") 
        sock.leftover = b''
        return None


# ---------------------------------------------------
# ------------ Reliable Call Signaling ---------------
# ---------------------------------------------------
def initiate_call(caller, receiver):
    """Caller requests a call with receiver."""
    caller_sock = None
    receiver_sock = None

    with clients_lock:
        if receiver not in clients:
            if caller in clients:
                safe_send(clients[caller], {"type": "error", "msg": f"Receiver '{receiver}' offline"})
            return

        if receiver in busy:
            if caller in clients:
                safe_send(clients[caller], {"type": "error", "msg": f"'{receiver}' is busy"})
            return

        caller_sock = clients.get(caller)
        receiver_sock = clients.get(receiver)
        
        if not caller_sock or not receiver_sock:
            # Should be prevented by checks above, but safety first
            return

    print(f"[CALL] {caller} initiating call with {receiver}")
    
    # Send incoming call notification
    success = safe_send(receiver_sock, {
        "type": "incoming_call",
        "from": caller
    })
    
    # --- CRITICAL FIX: CHECK SEND STATUS ---
    if not success:
        # Notify the caller immediately that the invitation failed
        safe_send(caller_sock, {"type": "call_failed", "reason": f"Failed to send invitation to {receiver}. Receiver socket may be dead."})
        print(f"[CALL] {caller} <--> {receiver}: Failed to send invitation. Aborting.")
        return 
    # ---------------------------------------

    def wait_for_answer_and_ports():
        # --- 1. Wait for Call Answer ---
        try:
            # Use the socket's current buffer if available, otherwise block
            ans_raw = recv_packet_line(receiver_sock, timeout=20)
            if ans_raw is None:
                safe_send(caller_sock, {"type": "call_failed", "reason": "Receiver did not answer in time"})
                print(f"[CALL] {caller} <--> {receiver}: Timeout waiting for answer")
                return
            ans = json.loads(ans_raw)
        except (json.JSONDecodeError, Exception) as e:
            print(f"[ERROR] Answer receive failed: {e}")
            safe_send(caller_sock, {"type": "call_failed", "reason": "Connection error or invalid response from receiver"})
            return

        if ans.get("type") != "call_answer" or ans.get("answer") != "yes":
            safe_send(caller_sock, {"type": "call_rejected"})
            print(f"[CALL] {caller} <--> {receiver}: Rejected")
            return

        # --- 2. Both agreed → Notify acceptance and request ports ---
        safe_send(caller_sock, {"type": "call_accept", "partner": receiver})
        safe_send(receiver_sock, {"type": "call_accept", "partner": caller})
        print(f"[CALL] {caller} <--> {receiver}: Accepted. Requesting ports.")

        # --- 3. UDP Port exchange ---
        # Receive Caller's ports
        p1 = None
        try:
            raw1 = recv_packet_line(caller_sock, timeout=10)
            p1_pkt = json.loads(raw1)
            if raw1 is None or p1_pkt.get("type") != "ports":
                 raise ValueError("Invalid or missing ports packet from caller")
            p1 = p1_pkt
        except Exception as e:
            print(f"[ERROR] Caller port exchange failed: {e}")
            safe_send(caller_sock, {"type": "error", "msg": "Failed to receive your ports"})
            safe_send(receiver_sock, {"type": "call_failed", "reason": "Caller failed to send media ports."})
            return
        
        # Receive Receiver's ports
        p2 = None
        try:
            raw2 = recv_packet_line(receiver_sock, timeout=10)
            p2_pkt = json.loads(raw2)
            if raw2 is None or p2_pkt.get("type") != "ports":
                 raise ValueError("Invalid or missing ports packet from receiver")
            p2 = p2_pkt
        except Exception as e:
            print(f"[ERROR] Receiver port exchange failed: {e}")
            safe_send(caller_sock, {"type": "call_failed", "reason": "Receiver failed to send media ports."})
            safe_send(receiver_sock, {"type": "error", "msg": "Failed to receive your ports"})
            return


        # --- 4. Relay ports ---
        # Send Partner's ports to Caller (Relay P2 data to Caller)
        safe_send(caller_sock, {
            "type": "ports_relay", 
            "partner": receiver,
            "ip": p2.get("ip"), 
            "video_port": p2.get("video_port"), 
            "audio_port": p2.get("audio_port")
        })
        # Send Partner's ports to Receiver (Relay P1 data to Receiver)
        safe_send(receiver_sock, {
            "type": "ports_relay", 
            "partner": caller,
            "ip": p1.get("ip"), 
            "video_port": p1.get("video_port"), 
            "audio_port": p1.get("audio_port")
        })

        with clients_lock:
            busy[caller] = receiver
            busy[receiver] = caller

        print(f"[CALL] {caller} <--> {receiver} CONNECTED")

    threading.Thread(target=wait_for_answer_and_ports, daemon=True).start()


# ---------------------------------------------------
# ---------------- Client Thread (Rest of server.py remains the same)
# ---------------------------------------------------
def client_thread(sock):
    # ... (content remains the same as Refined server.py in previous response)
    username = None
    sock.leftover = b'' 
    # ... (handle registration and main loop) ...
    try:
        raw = recv_packet_line(sock, timeout=5)
        if raw is None:
            return
            
        data = json.loads(raw)
        username = data.get("username")

        if data.get("type") != "register" or not username:
            safe_send(sock, {"type": "error", "msg": "First packet must be {'type': 'register', 'username': 'your_name'}"})
            sock.close()
            return

        with clients_lock:
            if username in clients:
                 safe_send(sock, {"type": "error", "msg": "Username already taken."})
                 sock.close()
                 return
            clients[username] = sock

        print(f"[+] {username} connected")

        while True:
            line = recv_packet_line(sock)
            if line is None:
                break

            try:
                packet = json.loads(line)
            except json.JSONDecodeError:
                safe_send(sock, {"type": "error", "msg": "Invalid JSON format"})
                continue

            handle_packet(username, sock, packet)

    except Exception:
        pass
    finally:
        cleanup_user(username, sock)


# ---------------------------------------------------
# ---------------- Packet Handler (Rest of server.py remains the same)
# ---------------------------------------------------
def handle_packet(username, sock, packet):
    ptype = packet.get("type")

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
                safe_send(sock, {"type": "error", "msg": f"User '{to_user}' not found or offline"})
    
    elif ptype == "broadcast":
        text = packet.get("msg")
        if not text:
            safe_send(sock, {"type": "error", "msg": "Missing 'msg' in broadcast packet"})
            return
            
        with clients_lock:
            for uname, client_sock in clients.items():
                if uname != username:
                     safe_send(client_sock, {
                        "type": "msg",
                        "from": username,
                        "msg": f"[BROADCAST] {text}"
                    })

    elif ptype == "call":
        to_user = packet.get("to")
        if not to_user:
            safe_send(sock, {"type": "error", "msg": "Missing 'to' in call packet"})
            return
        
        with clients_lock:
             if username in busy:
                  safe_send(sock, {"type": "error", "msg": f"You are already in a call with {busy[username]}."})
                  return
        
        initiate_call(username, to_user)
        
    elif ptype == "end_call":
        with clients_lock:
            if username in busy:
                partner = busy.pop(username)
                busy.pop(partner, None)

                if partner in clients:
                    safe_send(clients[partner], {
                        "type": "call_ended",
                        "from": username,
                        "msg": f"Call ended by {username}."
                    })
                print(f"[CALL] Ended: {username} <--> {partner} (Client request)")
            else:
                safe_send(sock, {"type": "error", "msg": "No active call to end."})
    
    elif ptype == "quit":
        pass
        
    else:
        safe_send(sock, {"type": "error", "msg": f"Unknown packet type: {ptype}"})


# ---------------------------------------------------
# ---------------- Cleanup User (Rest of server.py remains the same)
# ---------------------------------------------------
def cleanup_user(username, sock):
    # ... (content remains the same as Refined server.py in previous response)
    if not username:
        try:
            sock.close()
        except:
            pass
        return
        
    with clients_lock:
        if username in clients:
            del clients[username]

        if username in busy:
            partner = busy.pop(username)
            busy.pop(partner, None)
            if partner in clients:
                safe_send(clients[partner], {"type": "call_ended", "from": username, "msg": "Partner disconnected."})

    try:
        sock.close()
    except:
        pass

    print(f"[-] {username} disconnected")


# ---------------------------------------------------
# -------------------- Server (Rest of server.py remains the same)
# ---------------------------------------------------
def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) 
    try:
        server.bind((HOST, PORT))
    except Exception as e:
        print(f"[CRITICAL] Could not bind to {HOST}:{PORT}. Error: {e}")
        return
        
    server.listen(50)

    print(f"\n✨ Server running on {HOST}:{PORT}\n")
    print("--- Awaiting Connections ---")

    try:
        while True:
            sock, addr = server.accept()
            print(f"[NEW] Connection from {addr[0]}:{addr[1]}")
            threading.Thread(target=client_thread, args=(sock,), daemon=True).start()
    except KeyboardInterrupt:
        print("\n[INFO] Server stopping...")
    finally:
        server.close()
        print("[INFO] Server stopped.")


if __name__ == "__main__":
    start_server()