import socket
import threading

SERVER_IP = "127.0.0.1"
SERVER_PORT = 5000
My_IP = "10.75.16.16"  # Replace with local IP or use dynamic detection
udp_audio = 5001
udp_video = 5002

pause_event = threading.Event()
pause_event.set()  # Not paused initially

send_lock = threading.Lock()  # To avoid sending message collisions


def send_message(sock, msg):
    with send_lock:
        sock.sendall((msg + "\n").encode())


def recv_message(sock):
    buffer = ""
    while "\n" not in buffer:
        data = sock.recv(1024).decode()
        if not data:
            return None
        buffer += data
    line, rest = buffer.split("\n", 1)
    return line.strip()


def receive_messages(sock):
    while True:
        pause_event.wait()
        try:
            msg = recv_message(sock)
            if not msg:
                print("Disconnected from server.")
                break

            if ":::calling" in msg:
                caller, _ = msg.split(":::", 1)
                reply = input(f"{caller} is calling: (y/n) ")
                if reply.lower() == 'y':
                    send_message(sock, "yes")
                    # Send your IP info
                    send_message(sock, f"{My_IP}:{udp_audio}:{udp_video}")
                    # Receive caller's IP info
                    recv = recv_message(sock)
                    if recv:
                        ip, audio, video = recv.split(":")
                        print(f"Caller {caller} IP: {ip}, audio: {audio}, video: {video}")
                        print("Call accepted - you can now start UDP streams")
                        # Start UDP streaming threads here if implemented
                    else:
                        print("Error receiving caller info")
                else:
                    send_message(sock, "no")
            else:
                print("\n" + msg)
        except Exception as e:
            print(f"Receive error: {e}")
            break


def client_program():
    username = input("Enter your username: ")
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect((SERVER_IP, SERVER_PORT))

    send_message(client, username)

    print("Connected! Type messages.")
    print("Private message format: username:::message")

    receive_thread = threading.Thread(target=receive_messages, args=(client,), daemon=True)
    receive_thread.start()

    while True:
        msg = input()
        if ":::call" in msg:
            send_message(client, msg)
            pause_event.clear()  # pause receiving thread
            try:
                ans = recv_message(client)
                if ans == "0" or ans is None:
                    print("Call declined or error.")
                else:
                    # Send your IP info
                    send_message(client, f"{My_IP}:{udp_audio}:{udp_video}")
                    # Receive callee's IP info
                    recv = recv_message(client)
                    if recv:
                        ip, audio, video = recv.split(":")
                        print(f"Receiver IP: {ip}, audio: {audio}, video: {video}")
                        print("Call accepted - you can now start UDP streams")
                        # Start UDP streaming threads here if implemented
                    else:
                        print("Error receiving receiver info")
            except Exception as e:
                print(f"Error during call setup: {e}")
            pause_event.set()  # resume receiving thread
        elif msg.lower() == "quit":
            client.close()
            break
        else:
            send_message(client, msg)


if __name__ == "__main__":
    client_program()