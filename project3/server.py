import socket
import threading
import json
import struct

# Configuration
HOST = '0.0.0.0'
TCP_PORT = 5000
UDP_PORT = 5001
BUFFER_SIZE = 4096

# State Management
clients = {}  
rooms = {}    
udp_addresses = {} 

# --- THE FIX IS HERE ---
# Use RLock (Re-entrant Lock) so functions can call other locked functions safely
lock = threading.RLock() 
# -----------------------

def handle_tcp_client(client_socket, addr):
    """Handles reliable commands, text, and file transfers."""
    username = None
    try:
        while True:
            # 1. Read 4-byte length header
            raw_len = client_socket.recv(4)
            if not raw_len: break
            msg_len = struct.unpack('>I', raw_len)[0]

            # 2. Read the specific amount of data
            data = b''
            while len(data) < msg_len:
                packet = client_socket.recv(msg_len - len(data))
                if not packet: break
                data += packet
            
            if not data: break

            # 3. Parse JSON
            try:
                message = json.loads(data.decode('utf-8'))
            except json.JSONDecodeError:
                print(f"JSON Error from {addr}")
                continue

            command = message.get('type')

            if command == 'LOGIN':
                username = message['username']
                with lock:
                    clients[username] = {'tcp_sock': client_socket, 'addr': addr, 'status': 'online'}
                print(f"[TCP] User logged in: {username} from {addr}")
                broadcast_user_list()

            elif command == 'MSG':
                target = message.get('target')
                is_room = message.get('is_room', False)
                if is_room:
                    broadcast_room(target, message, sender=username)
                else:
                    send_tcp_to_user(target, message)

            elif command == 'JOIN_ROOM':
                room_name = message['room_name']
                with lock:
                    if room_name not in rooms:
                        rooms[room_name] = []
                    if username not in rooms[room_name]:
                        rooms[room_name].append(username)
                print(f"[ROOM] {username} joined {room_name}")

            elif command == 'FILE_Header':
                target = message.get('target')
                send_tcp_to_user(target, message)

            elif command == 'FILE_CHUNK':
                target = message.get('target')
                send_tcp_to_user(target, message)

    except Exception as e:
        print(f"[TCP] Error with {addr}: {e}")
    finally:
        if username:
            print(f"[TCP] Disconnecting {username}")
            with lock:
                if username in clients:
                    del clients[username]
                if username in udp_addresses:
                    del udp_addresses[username]
                # Remove from rooms
                for r in rooms:
                    if username in rooms[r]:
                        rooms[r].remove(username)
            broadcast_user_list()
        client_socket.close()

def send_tcp_to_user(username, message_dict):
    """Helper to pack and send JSON over TCP."""
    with lock:
        if username in clients:
            try:
                sock = clients[username]['tcp_sock']
                json_data = json.dumps(message_dict).encode('utf-8')
                sock.sendall(struct.pack('>I', len(json_data)) + json_data)
            except Exception as e:
                print(f"Send error to {username}: {e}")

def broadcast_room(room_name, message_dict, sender):
    with lock:
        if room_name in rooms:
            for user in rooms[room_name]:
                if user != sender:
                    send_tcp_to_user(user, message_dict)

def broadcast_user_list():
    """Sends the list of active users to everyone."""
    with lock:
        active_users = list(clients.keys())
        # Append rooms to the list so they are visible
        room_list = [f"#{r}" for r in rooms.keys()]
        
        msg = {'type': 'USER_LIST', 'users': active_users + room_list}
        
        for user in clients:
            send_tcp_to_user(user, msg)

def udp_server():
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.bind((HOST, UDP_PORT))
    print(f"[UDP] Server listening on {HOST}:{UDP_PORT}")

    while True:
        try:
            data, addr = udp_sock.recvfrom(65535)
            try:
                header_end = data.find(b'|')
                if header_end == -1: 
                    # Handle Register
                    msg_str = data.decode('utf-8', errors='ignore')
                    if msg_str.startswith("REGISTER:"):
                        u = msg_str.split(":")[1]
                        with lock: udp_addresses[u] = addr
                    continue
                
                metadata = data[:header_end].decode('utf-8')
                parts = metadata.split(':')
                
                if parts[0] == 'STREAM':
                    target = parts[1]
                    with lock:
                        if target in udp_addresses:
                            udp_sock.sendto(data, udp_addresses[target])
                        elif target in rooms:
                            for member in rooms[target]:
                                if member != parts[2] and member in udp_addresses:
                                    udp_sock.sendto(data, udp_addresses[member])
            except: pass
        except Exception as e:
            print(f"[UDP] Error: {e}")

if __name__ == "__main__":
    tcp_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_server.bind((HOST, TCP_PORT))
    tcp_server.listen(5)
    
    threading.Thread(target=udp_server, daemon=True).start()
    print(f"[TCP] Server listening on {HOST}:{TCP_PORT}")

    while True:
        conn, addr = tcp_server.accept()
        threading.Thread(target=handle_tcp_client, args=(conn, addr), daemon=True).start()