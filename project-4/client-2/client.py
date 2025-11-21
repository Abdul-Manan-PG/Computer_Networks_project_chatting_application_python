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
            # Re-create socket if it was closed
            if self.tcp_socket.fileno() == -1:
                self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            self.tcp_socket.connect((server_ip, TCP_PORT))
            self.connected = True
            threading.Thread(target=self.listen_tcp, daemon=True).start()
            threading.Thread(target=self.receive_udp, daemon=True).start()
            return True
        except Exception as e:
            print(f"Connection Error: {e}")
            return False
    
    def disconnect(self):
        if self.connected:
            try:
                self.send_command({"command": "LOGOUT"})
                time.sleep(0.2)
                self.tcp_socket.close()
            except:
                pass
        self.reset_state()

    def send_command(self, data):
        if self.connected:
            try:
                msg = json.dumps(data) + "\n"
                self.tcp_socket.send(msg.encode('utf-8'))
                return True
            except Exception as e:
                print(f"Send Failed: {e}")
                self.connected = False
                return False
        return False

    def listen_tcp(self):
        buffer = ""
        while self.connected:
            try:
                data = self.tcp_socket.recv(4096).decode('utf-8')
                if not data:
                    self.connected = False
                    break
                
                buffer += data
                
                while "\n" in buffer:
                    message_str, buffer = buffer.split("\n", 1)
                    if not message_str.strip(): continue
                        
                    try:
                        msg = json.loads(message_str)
                        self.process_message(msg)
                    except json.JSONDecodeError:
                        print("JSON Decode Error")

            except Exception as e:
                print(f"TCP Error: {e}")
                self.connected = False
                break

    def process_message(self, msg):
        # 1. Real-time Message
        if msg.get('type') == 'MESSAGE':
            sender = msg['from']
            if self.username:
                self.db.save_message(self.username, sender, sender, msg['content'], msg['timestamp'])
            self.message_queue.append(msg)
        
        # 2. Status Updates
        elif msg.get('type') == 'STATUS_UPDATE':
            user_updated = msg['username']
            status = msg['status']
            self.friend_statuses[user_updated] = status
            self.message_queue.append(msg)

        # 3. Friend List Sync (Response to GET_FRIENDS)
        elif msg.get('status') == 'success' and 'data' in msg:
            data_content = msg['data']
            
            # Case A: Friend List with Statuses
            if isinstance(data_content, list) and (len(data_content) == 0 or isinstance(data_content[0], dict)):
                if self.username:
                    for f_obj in data_content:
                        name = f_obj['username']
                        stat = f_obj['status']
                        # Update DB and Memory
                        self.db.add_friend(self.username, name)
                        self.friend_statuses[name] = stat
                        # Auto-fetch history
                        self.send_command({"command": "GET_HISTORY", "of_user": name})
                
                # Push to queue so UI updates
                self.message_queue.append(msg)

            # Case B: History Data
            elif isinstance(data_content, list) and msg.get('with_user'):
                friend_name = msg['with_user']
                self.db.bulk_save_messages(self.username, friend_name, data_content)
            else:
                self.message_queue.append(msg)
        
        # 4. Error handling
        elif msg.get('status') == 'error':
             self.message_queue.append(msg)

        # 5. Call Handling
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
            return "Could not connect to Server. Is it running?", 400

    cmd = "REGISTER" if action == "register" else "LOGIN"
    backend.send_command({
        "command": cmd, 
        "username": username, 
        "password": password, 
        "udp_port": backend.my_udp_port
    })
    
    # Wait for response
    for _ in range(20):
        time.sleep(0.1)
        found_msg = None
        for i, msg in enumerate(backend.message_queue):
            if msg.get('status') in ['success', 'error'] and 'message' in msg:
                found_msg = msg
                backend.message_queue.pop(i)
                break
        
        if found_msg:
            if found_msg['status'] == 'success':
                if action == 'login':
                    backend.username = username
                    session['user'] = username
                    # Initial Fetch
                    backend.send_command({"command": "GET_FRIENDS"})
                    return redirect(url_for('dashboard'))
                else:
                    return f"<h2>Registration Successful!</h2><p>User '{username}' created.</p><a href='/'>Go to Login</a>"
            else:
                return f"<h2>Error</h2><p>{found_msg['message']}</p><a href='/'>Try Again</a>"

    return "Server took too long to respond. <a href='/'>Try Again</a>"

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
        to_user = data['to']
        message = data['message']

        if not backend.connected:
             return jsonify({"status": "error", "message": "Disconnected from server."}), 503

        # 1. Local Strict Check
        status = backend.friend_statuses.get(to_user, "Offline")
        if status == "Offline":
            return jsonify({"status": "error", "message": "User is Offline. Cannot send message."}), 400

        # 2. Send
        success = backend.send_command({"command": "SEND_MSG", "to": to_user, "message": message})
        if not success:
             return jsonify({"status": "error", "message": "Failed to send command to server."}), 500

        # 3. Optimistic Save (UI feedback)
        t = time.strftime("%H:%M:%S")
        backend.db.save_message(backend.username, to_user, backend.username, message, t)
        
        return jsonify({"status": "ok", "timestamp": t})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

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
    """
    Called when 'Refresh' is clicked.
    1. Sends request to server to get FRESH statuses.
    2. Returns current local state immediately (UI will update again when server responds).
    """
    if backend.connected:
        backend.send_command({"command": "GET_FRIENDS"})
    
    # Return what we currently have
    db_friends = backend.db.get_friends(backend.username)
    response_list = []
    for f in db_friends:
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
    return jsonify({"messages": data, "call_status": backend.call_status, "connected": backend.connected})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True, threaded=True)