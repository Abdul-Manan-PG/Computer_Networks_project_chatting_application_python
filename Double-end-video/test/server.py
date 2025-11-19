import socket



def handle_client(client_socket):
    global clients
    try:
        username = client_socket.recv(1024).decode().strip()
        clients[username] = client_socket
        print(f"[+] {username} connected.")

        while True:
            msg = client_socket.recv(2048).decode()
            if not msg:
                break

            # format: recipient:::message
            if ":::" in msg:
                to_user, text = msg.split(":::", 1)
                if to_user in clients:
                    video_call_request(username, to_user)
                else:
                    client_socket.send("User not found!".encode())
            else:
                broadcast(f"{username}: {msg}", client_socket)

    except:
        pass
    finally:
        client_socket.close()

# Create UDP socket
server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Bind to IP and PORT
SERVER_IP = "0.0.0.0"   # Listen on all interfaces
SERVER_PORT = 5005

server_socket.bind((SERVER_IP, SERVER_PORT))
print(f"UDP server listening on {SERVER_IP}:{SERVER_PORT}")


