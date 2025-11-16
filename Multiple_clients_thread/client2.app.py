import socket
import threading

SERVER_IP = "10.75.16.16"   # change to server IP for other devices
SERVER_PORT = 5000

def receive_messages(sock):
    while True:
        try:
            msg = sock.recv(2048).decode()
            if not msg:
                break
            print("\n" + msg)
        except:
            break


def client_program():
    username = input("Enter your username: ")

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect((SERVER_IP, SERVER_PORT))

    client.send(username.encode())

    print("Connected! Type messages.")
    print("Private message format: username:::message")

    threading.Thread(target=receive_messages, args=(client,), daemon=True).start()

    while True:
        msg = input()
        if msg.lower() == "quit":
            client.close()
            break
        client.send(msg.encode())


if __name__ == "__main__":
    client_program()
