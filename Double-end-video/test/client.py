import socket

client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

SERVER_IP = "127.0.0.1"   # Change this to server IP if using different devices
SERVER_PORT = 5005

message = "Hello from client!"
n = 0
while n < 10:
    client_socket.sendto(message.encode(), (SERVER_IP, SERVER_PORT))
    n = n + 1

print("Message sent!")
