import socket
import threading

HOST = "10.75.16.29"
PORT = 5000

clients = {}         # username -> socket
busy = {}            # username -> partner username
clients_lock = threading.Lock()  # For thread-safe access to clients/busy dicts

def broadcast(message, sender_socket=None):
    """Send message to all other connected clients."""
    with clients_lock:
        for user, sock in clients.items():
            if sock != sender_socket:
                try:
                    sock.send(message.encode())
                except:
                    sock.close()

def video_call_request(caller, receiver):
    """Handle video call request from caller → receiver."""
    with clients_lock:
        if caller not in clients or receiver not in clients:
            return
        
        caller_sock = clients[caller]
        receiver_sock = clients[receiver]

        if receiver in busy:
            caller_sock.send(f"{receiver} is busy in another call".encode())
            return

        receiver_sock.send(f"{caller}::: calling".encode())

        try:
            ans = receiver_sock.recv(1024).decode().strip()
        except:
            caller_sock.send("Call failed: receiver disconnected.".encode())
            return

        if ans.lower() == "y":
            caller_sock.send("200".encode())
            receiver_sock.send("200".encode())

            try:
                port_from_receiver = receiver_sock.recv(1024)
                caller_sock.send(port_from_receiver)

                port_from_caller = caller_sock.recv(1024)
                receiver_sock.send(port_from_caller)
            except:
                caller_sock.send("Call failed: port exchange error.".encode())
                receiver_sock.send("Call failed: port exchange error.".encode())
                return

            busy[caller] = receiver
            busy[receiver] = caller
            print(f"[CALL] {caller} and {receiver} are now in a call.")

        else:
            caller_sock.send("400".encode())

def handle_client(client_socket):
    global clients, busy
    username = None

    try:
        username = client_socket.recv(1024).decode().strip()
        with clients_lock:
            clients[username] = client_socket
        print(f"[+] {username} connected.")

        broadcast(f"{username} joined the chat!", client_socket)

        while True:
            msg = client_socket.recv(2048).decode()
            if not msg:
                break

            if ":::" in msg:
                parts = msg.split(":::", 1)
                if len(parts) != 2:
                    client_socket.send("Invalid message format.".encode())
                    continue
                
                to_user, text = parts
                to_user = to_user.strip()
                text = text.strip()

                if text == "204":
                    with clients_lock:
                        if username in busy:
                            partner = busy[username]
                            del busy[username]
                            if partner in busy:
                                del busy[partner]
                            print(f"[CALL] Call ended between {username} and {partner}.")
                            if partner in clients:
                                try:
                                    clients[partner].send(f"{username} ended the call.".encode())
                                except:
                                    pass
                        else:
                            client_socket.send("You are not in a call.".encode())
                    continue

                if text == "calling":
                    with clients_lock:
                        if to_user in clients:
                            video_call_request(username, to_user)
                        else:
                            client_socket.send("User not found!".encode())
                    continue

                with clients_lock:
                    if to_user in clients:
                        clients[to_user].send(f"{username}: {text}".encode())
                    else:
                        client_socket.send("User not found!".encode())

            else:
                broadcast(f"{username}: {msg}", client_socket)

    except Exception as e:
        print(f"Error handling {username}: {e}")

    finally:
        with clients_lock:
            if username and username in clients:
                del clients[username]

            if username and username in busy:
                partner = busy[username]
                del busy[username]
                if partner in busy:
                    del busy[partner]
                print(f"[CALL] Call forcibly ended due to disconnect: {username} and {partner}.")

        client_socket.close()
        broadcast(f"{username} left the chat!")
        print(f"[-] {username} disconnected.")

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()

    print(f"Server running on {HOST}:{PORT}")

    while True:
        client_socket, _ = server.accept()
        print("[+] New connection")

        thread = threading.Thread(target=handle_client, args=(client_socket,))
        thread.daemon = True
        thread.start()

if __name__ == "__main__":
    start_server()
