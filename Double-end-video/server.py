import socket
import threading

HOST = "10.75.24.57"
PORT = 5000

clients = {}         # username -> socket
busy = {}            # username -> partner username


def broadcast(message, sender_socket=None):
    """Send message to all other connected clients."""
    for user, sock in clients.items():
        if sock != sender_socket:  # send to all EXCEPT sender
            try:
                sock.send(message.encode())
            except:
                sock.close()


def video_call_request(caller, receiver):
    """Handle video call request from caller → receiver."""
    caller_sock = clients[caller]
    receiver_sock = clients[receiver]

    # Busy check
    if receiver in busy:
        caller_sock.send(f"{receiver} is busy in another call".encode())
        return

    # Send request
    receiver_sock.send(f"{caller} is calling you".encode())

    # Wait for response
    try:
        ans = receiver_sock.recv(1024).decode().strip()
    except:
        caller_sock.send("Call failed: receiver disconnected.".encode())
        return

    if ans.lower() == "y":
        caller_sock.send("200".encode())   # accepted
        receiver_sock.send("200".encode())

        # exchange ports
        port_from_receiver = receiver_sock.recv(1024)
        caller_sock.send(port_from_receiver)

        port_from_caller = caller_sock.recv(1024)
        receiver_sock.send(port_from_caller)

        # mark as busy
        busy[caller] = receiver
        busy[receiver] = caller

    else:
        caller_sock.send("400".encode())   # rejected


def handle_client(client_socket):
    global clients, busy

    try:
        username = client_socket.recv(1024).decode().strip()
        clients[username] = client_socket
        print(f"[+] {username} connected.")

        broadcast(f"{username} joined the chat!", client_socket)

        while True:
            msg = client_socket.recv(2048).decode()
            if not msg:
                break

            # Format: receiver:::message
            if ":::" in msg:
                to_user, text = msg.split(":::", 1)

                if text == "204":        # end call
                    if username in busy:
                        partner = busy[username]
                        del busy[username]
                        del busy[partner]
                    continue

                if text == "call":
                    if to_user in clients:
                        video_call_request(username, to_user)
                    else:
                        client_socket.send("User not found!".encode())
                    continue

                # Otherwise normal direct message
                if to_user in clients:
                    clients[to_user].send(f"{username}: {text}".encode())
                else:
                    client_socket.send("User not found!".encode())

            else:
                broadcast(f"{username}: {msg}", client_socket)

    except Exception as e:
        print("Error:", e)

    finally:
        # Clean disconnect
        if username in clients:
            del clients[username]

        # Remove from busy if in call
        if username in busy:
            partner = busy[username]
            del busy[username]
            if partner in busy:
                del busy[partner]

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
