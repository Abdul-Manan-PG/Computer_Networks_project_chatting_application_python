from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import socket
import threading
import json
import time
from client_db import ClientDatabase

app = Flask(__name__)
app.secret_key = 'secret_key_for_session'

# Configuration
TCP_PORT = 5555
UDP_PORT = 0

class ChatBackend:
    def __init__(self):
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.bind(('0.0.0.0', UDP_PORT))
        self.my_udp_port = self.udp_socket.getsockname()[1]
        
        self.connected = False
        self.username = None
        
        self.target_ip = None
        self.target_udp_port = None
        self.in_call = False
        self.call_status = "Idle"
        
        self.db = ClientDatabase()
        self.message_queue = [] 
        
        # NEW: Store real-time status of friends (not saved in DB, just memory)
        self.friend_statuses = {} 

    def connect(self, server_ip):
        try:
            self.tcp_socket.connect((server_ip, TCP_PORT))
            self.connected = True
            threading.Thread(target=self.listen_tcp, daemon=True).start()
            threading.Thread(target=self.receive_udp, daemon=True).start()
            return True
        except Exception as e:
            print(f"Connection Error: {e}")
            return False

    def send_command(self, data):
        if self.connected:
            try:
                self.tcp_socket.send(json.dumps(data).encode('utf-8'))
            except:
                self.connected = False

    def listen_tcp(self):
        while self.connected:
            try:
                data = self.tcp_socket.recv(16384).decode('utf-8')
                if not data: break
                
                try:
                    msg = json.loads(data)
                    
                    # --- 1. Real-time Message ---
                    if msg.get('type') == 'MESSAGE':
                        sender = msg['from']
                        if self.username:
                            self.db.save_message(self.username, sender, sender, msg['content'], msg['timestamp'])
                        self.message_queue.append(msg)
                    
                    # --- 2. Status Updates (Online/Offline) ---
                    elif msg.get('type') == 'STATUS_UPDATE':
                        # Update memory
                        user_updated = msg['username']
                        status = msg['status']
                        self.friend_statuses[user_updated] = status
                        # Pass to UI to update dot immediately
                        self.message_queue.append(msg)

                    # --- 3. Friend List Sync (Initial Login) ---
                    elif msg.get('status') == 'success' and 'data' in msg:
                        data_content = msg['data']
                        
                        # Case A: It is the Friend List with Status Objects
                        if isinstance(data_content, list) and len(data_content) > 0 and isinstance(data_content[0], dict):
                            if self.username:
                                for f_obj in data_content:
                                    name = f_obj['username']
                                    stat = f_obj['status']
                                    
                                    # Save name to DB
                                    self.db.add_friend(self.username, name)
                                    # Save status to Memory
                                    self.friend_statuses[name] = stat
                                    
                                    # Trigger History Sync
                                    self.send_command({"command": "GET_HISTORY", "of_user": name})
                            
                            # Send this list to UI so it renders initially
                            self.message_queue.append(msg)

                        # Case B: It is History (List of lists/tuples)
                        elif isinstance(data_content, list) and msg.get('with_user'):
                            friend_name = msg['with_user']
                            self.db.bulk_save_messages(self.username, friend_name, data_content)

                    # --- 4. Call Handling ---
                    elif msg.get('type') == 'CALL_INFO':
                        self.target_ip = msg['target_ip']
                        self.target_udp_port = msg['target_port']
                        self.in_call = True
                        self.call_status = "In Call..."
                        threading.Thread(target=self.send_udp_audio).start()
                        self.message_queue.append(msg)
                    
                    elif msg.get('type') == 'INCOMING_CALL':
                        self.in_call = True
                        self.call_status = f"Incoming Call from {msg['from']}!"
                        self.message_queue.append(msg)
                    
                    else:
                        self.message_queue.append(msg)

                except json.JSONDecodeError:
                    pass
            except Exception as e:
                print(f"TCP Error: {e}")
                break

    def receive_udp(self):
        while True:
            try:
                data, addr = self.udp_socket.recvfrom(1024)
                if self.in_call:
                    print(f"[AUDIO OUT] {data.decode()}")
            except:
                pass

    def send_udp_audio(self):
        seq = 1
        while self.in_call:
            msg = f"WebAudioPacket_{seq}"
            try:
                self.udp_socket.sendto(msg.encode(), (self.target_ip, self.target_udp_port))
                time.sleep(1)
                seq += 1
            except:
                break
        self.call_status = "Call Ended"

backend = ChatBackend()

# --- Flask Routes ---

@app.route('/')
def index():
    if backend.username: return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/connect', methods=['POST'])
def connect():
    server_ip = request.form.get('server_ip')
    username = request.form.get('username')
    password = request.form.get('password')
    action = request.form.get('action')

    if not backend.connected:
        if not backend.connect(server_ip):
            return "Could not connect", 400

    cmd = "REGISTER" if action == "register" else "LOGIN"
    backend.send_command({
        "command": cmd, 
        "username": username, 
        "password": password, 
        "udp_port": backend.my_udp_port
    })
    
    time.sleep(0.5)
    for msg in backend.message_queue:
        if msg.get('status') == 'success':
             if action == 'login':
                 backend.username = username
                 session['user'] = username
                 # Trigger initial sync
                 backend.send_command({"command": "GET_FRIENDS"})
                 return redirect(url_for('dashboard'))
             else:
                 return "Registered. Go back and Login."
        elif msg.get('status') == 'error':
            return f"Error: {msg.get('message')}"

    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    if not backend.username: return redirect(url_for('index'))
    return render_template('dashboard.html', username=backend.username)

# --- API ---

@app.route('/api/send_message', methods=['POST'])
def send_message():
    data = request.json
    backend.send_command({"command": "SEND_MSG", "to": data['to'], "message": data['message']})
    t = time.strftime("%H:%M:%S")
    backend.db.save_message(backend.username, data['to'], backend.username, data['message'], t)
    return jsonify({"status": "ok", "timestamp": t})

@app.route('/api/add_friend', methods=['POST'])
def add_friend():
    friend = request.json['friend']
    backend.send_command({"command": "ADD_FRIEND", "friend_name": friend})
    # Add to DB and assume offline until server says otherwise
    backend.db.add_friend(backend.username, friend)
    backend.friend_statuses[friend] = "Offline"
    return jsonify({"status": "ok"})

@app.route('/api/get_friends')
def get_friends():
    # 1. Get list from DB
    db_friends = backend.db.get_friends(backend.username)
    
    # 2. Merge with Live Status from Memory
    response_list = []
    for f in db_friends:
        # Default to Offline if we haven't heard anything
        stat = backend.friend_statuses.get(f, "Offline")
        response_list.append({"username": f, "status": stat})
        
    return jsonify({"status": "success", "data": response_list})

@app.route('/api/history/<friend_name>')
def get_history(friend_name):
    msgs = backend.db.get_history(backend.username, friend_name)
    formatted = [{"from": m[0], "content": m[1], "timestamp": m[2]} for m in msgs]
    return jsonify(formatted)

@app.route('/api/call_user', methods=['POST'])
def call_user():
    target = request.json['target']
    backend.send_command({"command": "INIT_CALL", "callee": target})
    return jsonify({"status": "dialing"})

@app.route('/api/updates')
def updates():
    data = list(backend.message_queue)
    backend.message_queue.clear()
    return jsonify({"messages": data, "call_status": backend.call_status})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=True, threaded=True)