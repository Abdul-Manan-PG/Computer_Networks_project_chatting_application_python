import socket
import threading

clients = []

def client_thread(conn, addr):
    global clients
    print(f"[CONNECTED] {addr}")
    clients.append(conn)

    try:
        while True:
            size_bytes = conn.recv(4)
            if not size_bytes:
                break
            frame_size = int.from_bytes(size_bytes, "big")

            frame = b""
            while len(frame) < frame_size:
                data = conn.recv(frame_size - len(frame))
                if not data:
                    break
                frame += data

            # broadcast to all except sender
            for c in clients:
                if c != conn:
                    try:
                        c.send(len(frame).to_bytes(4, "big") + frame)
                    except:
                        pass

    except:
        pass
    finally:
        print(f"[DISCONNECTED] {addr}")
        clients.remove(conn)
        conn.close()


def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("0.0.0.0", 9999))
    server.listen()

    print("[SERVER RUNNING] PORT 9999")

    while True:
        conn, addr = server.accept()
        threading.Thread(target=client_thread, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    start_server()
