import socket
import threading

HOST = "0.0.0.0"
PORT = 5000

clients = {}  # username: socket
busy = {}  # username: partner_username


def send_message(sock, msg):
    try:
        sock.sendall((msg + "\n").encode())
    except:
        pass


def recv_message(sock):
    buffer = ""
    while "\n" not in buffer:
        try:
            data = sock.recv(1024).decode()
            if not data:
                return None
            buffer += data
        except:
            return None
    line, rest = buffer.split("\n", 1)
    return line.strip()


def handle_client(client_socket):
    global clients, busy
    username = None
    try:
        username = recv_message(client_socket)
        if not username:
            client_socket.close()
            return
        clients[username] = client_socket
        print(f"[+] {username} connected.")

        # Notify others
        for user, sock in clients.items():
            if user != username:
                send_message(sock, f"{username} joined the chat!")

        while True:
            msg = recv_message(client_socket)
            if not msg:
                break

            print(f"{username}: {msg}")

            if ":::call" in msg:
                to_user, text = msg.split(":::", 1)
                if to_user in clients and to_user not in busy:
                    # Notify callee
                    send_message(clients[to_user], f"{username}:::calling")
                    ans = recv_message(clients[to_user])
                    if ans == "yes":
                        # accepted
                        send_message(clients[username], "1")
                        busy[username] = to_user
                        busy[to_user] = username
                        try:
                            port1 = recv_message(clients[to_user])
                            port2 = recv_message(clients[username])
                            send_message(clients[username], port1)
                            send_message(clients[to_user], port2)
                        except:
                            send_message(clients[username], "0")
                            send_message(clients[to_user], "0")
                            del busy[username]
                            del busy[to_user]
                    else:
                        send_message(clients[username], "0")
                else:
                    send_message(client_socket, "User not found or busy!")
            elif ":::" in msg:
                to_user, text = msg.split(":::", 1)
                if to_user in clients:
                    send_message(clients[to_user], f"{username}: {text}")
                else:
                    send_message(client_socket, "User not found!")
            else:
                # Broadcast to others
                for user, sock in clients.items():
                    if user != username:
                        send_message(sock, f"{username}: {msg}")

    except Exception as e:
        print(f"Error with {username}: {e}")
    finally:
        if username:
            if username in clients:
                del clients[username]
            if username in busy:
                partner = busy[username]
                del busy[username]
                if partner in busy:
                    del busy[partner]
            for user, sock in clients.items():
                send_message(sock, f"{username} left the chat!")
        client_socket.close()
        print(f"[-] {username} disconnected.")


def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()

    print(f"Server running on {HOST}:{PORT}")

    while True:
        client_socket, addr = server.accept()
        print(f"New connection from {addr}")

        thread = threading.Thread(target=handle_client, args=(client_socket,))
        thread.daemon = True
        thread.start()


if __name__ == "__main__":
    start_server()