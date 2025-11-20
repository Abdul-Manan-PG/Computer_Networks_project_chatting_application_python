import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import socket
import threading
import json
import struct
import base64
import time
import utils  # Local utils.py

# --- CONFIGURATION ---
SERVER_IP = '127.0.0.1' 
SERVER_TCP = 5000
SERVER_UDP = 5001

app = Flask(__name__)
app.config['SECRET_KEY'] = 'user_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- Global State ---
tcp_sock = None
udp_sock = None
my_username = ""
connected = False
active_server_users = [] # List of users currently online (from Server)

# --- Helpers ---
def push_combined_user_list():
    """
    Combines server online list with local data folder list.
    Emits to UI with status.
    """
    # 1. Get all users who have history on this PC
    historical_users = utils.get_existing_users()
    
    # 2. Create a set of all unique names (Active + Historical)
    # We use a set to avoid duplicates
    all_unique = set(active_server_users + historical_users)
    
    final_list = []
    
    for u in all_unique:
        # Skip ourself
        if u == my_username: 
            continue

        # Determine status
        status = 'offline'
        if u in active_server_users:
            status = 'online'
            
        # Special check for Rooms (start with #) - always online if in server list
        if u.startswith('#'):
            if u in active_server_users:
                final_list.append({'username': u, 'status': 'room'})
        else:
            final_list.append({'username': u, 'status': status})

    # 3. Emit to Javascript
    socketio.emit('frontend_user_update', {'users': final_list})

# --- Networking Threads ---

def tcp_listen_thread():
    global connected, tcp_sock, active_server_users
    while connected:
        try:
            raw_len = tcp_sock.recv(4)
            if not raw_len: break
            msg_len = struct.unpack('>I', raw_len)[0]
            
            data = b''
            while len(data) < msg_len:
                packet = tcp_sock.recv(msg_len - len(data))
                if not packet: break
                data += packet
            
            if not data: break
            
            msg = json.loads(data.decode('utf-8'))
            
            if msg['type'] == 'USER_LIST':
                # Update global list and push combined view
                active_server_users = msg['users']
                push_combined_user_list()

            elif msg['type'] == 'MSG':
                utils.save_message_history(my_username, msg)
                socketio.emit('receive_message', msg)
                
        except Exception as e:
            print(f"TCP Error: {e}")
            break
    
    connected = False
    socketio.emit('status', {'msg': 'Disconnected from server'})

def udp_listen_thread():
    global connected, udp_sock
    while connected:
        try:
            data, _ = udp_sock.recvfrom(65535)
            header_end = data.find(b'|')
            if header_end != -1:
                meta = data[:header_end].decode('utf-8')
                payload = data[header_end+1:]
                sender = meta.split(':')[2]
                b64 = base64.b64encode(payload).decode('utf-8')
                socketio.emit('incoming_media', {'sender': sender, 'data': b64})
        except:
            break

# --- Flask Routes ---

@app.route('/')
def index():
    return render_template('index.html')

# --- SocketIO Handlers ---

@socketio.on('login')
def on_login(data):
    global tcp_sock, udp_sock, my_username, connected
    my_username = data['username']
    
    # Ensure my own folder exists
    utils.ensure_user_structure(my_username)
    
    try:
        tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_sock.connect((SERVER_IP, SERVER_TCP))
        
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.sendto(f"REGISTER:{my_username}".encode('utf-8'), (SERVER_IP, SERVER_UDP))
        
        connected = True
        
        threading.Thread(target=tcp_listen_thread, daemon=True).start()
        threading.Thread(target=udp_listen_thread, daemon=True).start()
        
        login_payload = json.dumps({'type': 'LOGIN', 'username': my_username}).encode('utf-8')
        tcp_sock.sendall(struct.pack('>I', len(login_payload)) + login_payload)
        
        emit('login_success', {'username': my_username})
        
        # Load History
        hist = utils.load_user_history(my_username)
        emit('load_history', {'history': hist})
        
        # Trigger an initial user list push (loading existing files immediately)
        push_combined_user_list()
        
    except Exception as e:
        emit('status', {'msg': f"Connection failed: {e}"})

@socketio.on('send_chat')
def on_chat(data):
    if not connected: return
    msg = {
        'type': 'MSG',
        'sender': my_username,
        'target': data['target'],
        'content': data['message'],
        'is_room': data.get('is_room', False),
        'timestamp':  time.time()
    }
    payload = json.dumps(msg).encode('utf-8')
    tcp_sock.sendall(struct.pack('>I', len(payload)) + payload)
    utils.save_message_history(my_username, msg)

@socketio.on('join_room')
def on_join(data):
    if not connected: return
    msg = {'type': 'JOIN_ROOM', 'username': my_username, 'room_name': data['room']}
    payload = json.dumps(msg).encode('utf-8')
    tcp_sock.sendall(struct.pack('>I', len(payload)) + payload)

@socketio.on('stream_media')
def on_stream(data):
    if not connected: return
    try:
        raw = base64.b64decode(data['data'])
        header = f"STREAM:{data['target']}:{my_username}|".encode('utf-8')
        udp_sock.sendto(header + raw, (SERVER_IP, SERVER_UDP))
    except: pass

if __name__ == '__main__':
    print("Client running on http://localhost:5600")
    socketio.run(app, port=5600, debug=True)