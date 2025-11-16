import socket
import threading

HOST = "10.75.16.16"
PORT = 5000

clients = {}  # username: socket

def broadcast(message, sender_socket=None):
    for user, client_sock in clients.items():
        if client_sock != sender_socket:
            try:
                client_sock.send(message.encode())
            except:
                client_sock.close()


def handle_client(client_socket):
    global clients
    try:
        username = client_socket.recv(1024).decode().strip()
        clients[username] = client_socket
        print(f"[+] {username} connected.")

        # Notify others
        broadcast(f"{username} joined the chat!", client_socket)

        while True:
            msg = client_socket.recv(2048).decode()
            if not msg:
                break

            print(f"{username}: {msg}")

            # format: recipient:::message
            if ":::" in msg:
                to_user, text = msg.split(":::", 1)
                if to_user in clients:
                    clients[to_user].send(f"{username}: {text}".encode())
                else:
                    client_socket.send("User not found!".encode())
            else:
                broadcast(f"{username}: {msg}", client_socket)

    except:
        pass
    finally:
        # Cleanup
        for user, sock in list(clients.items()):
            if sock == client_socket:
                del clients[user]
                break
        client_socket.close()
        broadcast(f"{username} left the chat!")


def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen()

    print(f"Server running on PORT {PORT}")

    while True:
        client_socket, _ = server.accept()
        print("New connection")

        thread = threading.Thread(target=handle_client, args=(client_socket,))
        thread.daemon = True
        thread.start()


if __name__ == "__main__":
    start_server()
