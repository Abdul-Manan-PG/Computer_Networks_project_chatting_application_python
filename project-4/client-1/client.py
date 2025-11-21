from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import socket
import threading
import json
import time
import os
import base64
from client_db import ClientDatabase

app = Flask(__name__)
app.secret_key = 'secret_key_for_session'

# Ensure upload directory exists
UPLOAD_FOLDER = 'static/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

TCP_PORT = 5555
UDP_PORT = 0

class ChatBackend:
    def __init__(self):
        self.reset_state()
        self.db = ClientDatabase()
        self.message_queue = [] 
        
    def reset_state(self):
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.bind(('0.0.0.0', UDP_PORT))
        self.my_udp_port = self.udp_socket.getsockname()[1]
        self.connected = False
        self.username = None
        self.friend_statuses = {} 
        self.target_ip = None
        self.target_udp_port = None
        self.in_call = False
        self.call_status = "Idle"

    def connect(self, server_ip):
        try:
            if self.tcp_socket.fileno() == -1: self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.tcp_socket.connect((server_ip, TCP_PORT))
            self.connected = True
            threading.Thread(target=self.listen_tcp, daemon=True).start()
            threading.Thread(target=self.receive_udp, daemon=True).start()
            return True
        except: return False
    
    def disconnect(self):
        if self.connected:
            try:
                self.send_command({"command": "LOGOUT"})
                time.sleep(0.2)
                self.tcp_socket.close()
            except: pass
        self.reset_state()

    def send_command(self, data):
        if self.connected:
            try:
                msg = json.dumps(data) + "\n"
                self.tcp_socket.send(msg.encode('utf-8'))
                return True
            except: 
                self.connected = False
                return False
        return False

    def listen_tcp(self):
        buffer = ""
        while self.connected:
            try:
                data = self.tcp_socket.recv(1024*1024).decode('utf-8') # Large buffer for files
                if not data:
                    self.connected = False
                    break
                buffer += data
                while "\n" in buffer:
                    message_str, buffer = buffer.split("\n", 1)
                    if not message_str.strip(): continue
                    try: self.process_message(json.loads(message_str))
                    except: pass
            except: 
                self.connected = False
                break

    def process_message(self, msg):
        msg_type = msg.get('type')
        
        if msg_type == 'MESSAGE':
            sender = msg['from']
            content = msg['content']
            m_type = msg.get('msg_type', 'text')
            filename = msg.get('filename', '')

            # If it's a file, decode and save
            if m_type != 'text':
                try:
                    file_data = base64.b64decode(content)
                    filepath = os.path.join(UPLOAD_FOLDER, filename)
                    # Handle duplicate filenames
                    if os.path.exists(filepath):
                        filename = f"{int(time.time())}_{filename}"
                        filepath = os.path.join(UPLOAD_FOLDER, filename)
                    
                    with open(filepath, 'wb') as f:
                        f.write(file_data)
                    
                    # For DB, we store the filename, not the base64 content
                    content = filename 
                except Exception as e:
                    print(f"File save error: {e}")

            if self.username:
                self.db.save_message(self.username, sender, sender, content, m_type, msg['timestamp'])
            self.message_queue.append(msg)
        
        elif msg_type == 'STATUS_UPDATE':
            self.friend_statuses[msg['username']] = msg['status']
            self.message_queue.append(msg)

        elif msg.get('status') == 'success' and 'data' in msg:
            data = msg['data']
            # Friend List
            if isinstance(data, list) and (len(data)==0 or isinstance(data[0], dict)):
                if self.username:
                    for f in data:
                        self.db.add_friend(self.username, f['username'])
                        self.friend_statuses[f['username']] = f['status']
                        self.send_command({"command": "GET_HISTORY", "of_user": f['username']})
                self.message_queue.append(msg)
            # History
            elif isinstance(data, list) and msg.get('with_user'):
                self.db.bulk_save_messages(self.username, msg['with_user'], data)

        elif msg_type == 'CALL_INFO':
            self.target_ip = msg['target_ip']
            self.target_udp_port = msg['target_port']
            self.in_call = True
            self.call_status = "In Call..."
            threading.Thread(target=self.send_udp_audio).start()
            self.message_queue.append(msg)
            
        elif msg_type == 'INCOMING_CALL':
            self.in_call = True
            self.call_status = f"Incoming Call from {msg['from']}!"
            self.message_queue.append(msg)
            
        elif msg.get('status') == 'error':
             self.message_queue.append(msg)

    def receive_udp(self):
        while True:
            try:
                data, addr = self.udp_socket.recvfrom(1024)
                if self.in_call: print(f"[AUDIO OUT] {data.decode()}")
            except: pass

    def send_udp_audio(self):
        seq = 1
        while self.in_call:
            msg = f"WebAudioPacket_{seq}"
            try:
                self.udp_socket.sendto(msg.encode(), (self.target_ip, self.target_udp_port))
                time.sleep(1)
                seq += 1
            except: break
        self.call_status = "Call Ended"

backend = ChatBackend()

# --- Routes ---
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
        if not backend.connect(server_ip): return "Server connection failed", 400

    backend.send_command({"command": "REGISTER" if action == "register" else "LOGIN", "username": username, "password": password, "udp_port": backend.my_udp_port})
    
    for _ in range(20):
        time.sleep(0.1)
        for i, msg in enumerate(backend.message_queue):
            if msg.get('status') in ['success', 'error'] and 'message' in msg:
                backend.message_queue.pop(i)
                if msg['status'] == 'success':
                    if action == 'login':
                        backend.username = username
                        session['user'] = username
                        backend.send_command({"command": "GET_FRIENDS"})
                        return redirect(url_for('dashboard'))
                    else: return f"<h2>Registered!</h2><a href='/'>Login</a>"
                else: return f"<h2>Error</h2><p>{msg['message']}</p>"
    return "Timeout"

@app.route('/logout')
def logout():
    backend.disconnect()
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if not backend.username: return redirect(url_for('index'))
    return render_template('dashboard.html', username=backend.username)

@app.route('/api/send_message', methods=['POST'])
def send_message():
    try:
        data = request.json
        if not backend.connected: return jsonify({"error": "Disconnected"}), 503
        
        status = backend.friend_statuses.get(data['to'], "Offline")
        if status == "Offline": return jsonify({"status": "error", "message": "User Offline"}), 400

        backend.send_command({"command": "SEND_MSG", "to": data['to'], "message": data['message']})
        t = time.strftime("%H:%M:%S")
        backend.db.save_message(backend.username, data['to'], backend.username, data['message'], "text", t)
        return jsonify({"status": "ok", "timestamp": t})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files: return jsonify({"error": "No file"}), 400
    file = request.files['file']
    to_user = request.form['to']
    msg_type = request.form['type'] # image, audio, video, file
    
    if file.filename == '': return jsonify({"error": "No filename"}), 400
    
    # Check offline status strict check
    status = backend.friend_statuses.get(to_user, "Offline")
    if status == "Offline": return jsonify({"status": "error", "message": "User Offline"}), 400

    # Save locally
    filename = f"{int(time.time())}_{file.filename}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    
    # Read and Encode
    with open(filepath, "rb") as f:
        encoded_string = base64.b64encode(f.read()).decode('utf-8')
    
    # Send
    success = backend.send_command({
        "command": "SEND_MSG",
        "to": to_user,
        "message": encoded_string, # Base64 content
        "msg_type": msg_type,
        "filename": filename
    })

    if success:
        t = time.strftime("%H:%M:%S")
        # Save to DB (Store filename only)
        backend.db.save_message(backend.username, to_user, backend.username, filename, msg_type, t)
        return jsonify({"status": "ok", "timestamp": t, "filename": filename})
    else:
        return jsonify({"status": "error", "message": "Failed to send"}), 500

@app.route('/api/add_friend', methods=['POST'])
def add_friend():
    friend = request.json['friend']
    backend.send_command({"command": "ADD_FRIEND", "friend_name": friend})
    backend.send_command({"command": "CHECK_STATUS", "target": friend})
    backend.db.add_friend(backend.username, friend)
    backend.friend_statuses[friend] = "Offline"
    return jsonify({"status": "ok"})

@app.route('/api/get_friends')
def get_friends():
    if backend.connected: backend.send_command({"command": "GET_FRIENDS"})
    db_friends = backend.db.get_friends(backend.username)
    data = [{"username": f, "status": backend.friend_statuses.get(f, "Offline")} for f in db_friends]
    return jsonify({"status": "success", "data": data})

@app.route('/api/history/<friend_name>')
def get_history(friend_name):
    msgs = backend.db.get_history(backend.username, friend_name)
    # Format: sender, content, msg_type, timestamp
    formatted = [{"from": m[0], "content": m[1], "msg_type": m[2], "timestamp": m[3]} for m in msgs]
    return jsonify(formatted)

@app.route('/api/call_user', methods=['POST'])
def call_user():
    backend.send_command({"command": "INIT_CALL", "callee": request.json['target']})
    return jsonify({"status": "dialing"})

@app.route('/api/updates')
def updates():
    data = list(backend.message_queue)
    backend.message_queue.clear()
    return jsonify({"messages": data, "call_status": backend.call_status, "connected": backend.connected})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)