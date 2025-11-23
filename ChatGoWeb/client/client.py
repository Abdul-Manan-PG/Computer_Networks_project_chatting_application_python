from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import socket, threading, json, time, os, base64
from client_db import ClientDatabase
import argparse

app = Flask(__name__)
app.secret_key = 'super_secret_chat_go'

UPLOAD_FOLDER = 'static/uploads'
if not os.path.exists(UPLOAD_FOLDER): os.makedirs(UPLOAD_FOLDER)

TCP_PORT = 5555

class ChatBackend:
    def __init__(self):
        self.reset_state()
        self.db = ClientDatabase()
        self.msg_queue = []

    def reset_state(self):
        self.sock = None
        self.connected = False
        self.username = None
        self.friend_statuses = {}

    def connect(self, ip):
        if self.connected: return True
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((ip, TCP_PORT))
            self.sock.settimeout(None)
            self.connected = True
            threading.Thread(target=self.listener, daemon=True).start()
            return True
        except: return False

    def send(self, data):
        if self.connected:
            try: self.sock.sendall((json.dumps(data)+"\n").encode('utf-8'))
            except: self.connected = False

    def listener(self):
        buf = ""
        while self.connected:
            try:
                data = self.sock.recv(1024*1024).decode('utf-8')
                if not data: break
                buf += data
                while "\n" in buf:
                    msg, buf = buf.split("\n", 1)
                    if msg: self.process_msg(json.loads(msg))
            except: 
                self.connected = False
                break

    def process_msg(self, msg):
        t = msg.get('type')
        
        if 'status' in msg and not t: # Command Responses
            self.msg_queue.append(msg)
        
        elif t == 'STATUS':
            self.friend_statuses[msg['username']] = msg['status']
            self.msg_queue.append(msg)

        elif t == 'MESSAGE':
            ctx = msg.get('group') if msg.get('group') else msg['from']
            is_g = True if msg.get('group') else False
            self.db.save_msg(ctx, msg['from'], msg['content'], msg['is_file'], msg['time'], is_g)
            self.msg_queue.append(msg)

        elif t == 'FRIENDS':
            # Sync friends
            self.msg_queue.append(msg)
            for f in msg['data']: 
                self.friend_statuses[f['name']] = f['status']
                self.db.add_friend(f['name'])

        elif t == 'GROUPS':
            self.msg_queue.append(msg)
            for g in msg['data']: self.db.add_group(g)

        # WebRTC Signaling - Just pass through to frontend
        elif t in ['PEER_JOINED', 'EXISTING_PEER', 'SIGNAL', 'PEER_LEFT']:
            self.msg_queue.append(msg)

        elif t == 'HISTORY':
            self.msg_queue.append(msg)

backend = ChatBackend()

@app.route('/')
def index():
    return render_template('login.html')

@app.route('/connect', methods=['POST'])
def connect():
    ip = request.form.get('server_ip')
    user = request.form.get('username')
    pw = request.form.get('password')
    act = request.form.get('action')

    if not backend.connect(ip): return "Server Offline", 500
    
    backend.send({"command": "REGISTER" if act=='register' else "LOGIN", "username": user, "password": pw, "udp_port": 0})
    
    # Poll for auth response
    for _ in range(50):
        time.sleep(0.1)
        for i, m in enumerate(backend.msg_queue):
            if 'status' in m and 'message' in m:
                backend.msg_queue.pop(i)
                if m['status'] == 'success':
                    if act == 'login':
                        backend.username = user
                        session['user'] = user
                        backend.send({"command": "GET_FRIENDS"})
                        backend.send({"command": "GET_GROUPS"})
                        return redirect(url_for('dashboard'))
                    else: return "Registered! <a href='/'>Login</a>"
                else: return f"Error: {m['message']}"
    return "Timeout"

@app.route('/dashboard')
def dashboard():
    if not backend.username: return redirect('/')
    return render_template('dashboard.html', username=backend.username)

# --- API ---
@app.route('/api/send', methods=['POST'])
def send_msg():
    d = request.json
    cmd = "SEND_GROUP_MSG" if d['is_group'] else "SEND_MSG"
    backend.send({"command": cmd, "to": d['to'], "msg": d['msg']})
    # Save locally
    backend.db.save_msg(d['to'], backend.username, d['msg'], False, time.ctime(), d['is_group'])
    return jsonify({"status": "ok", "time": time.ctime()})

@app.route('/api/upload', methods=['POST'])
def upload():
    f = request.files['file']
    to = request.form['to']
    is_g = request.form['is_group'] == 'true'
    
    fn = f"{int(time.time())}_{f.filename}"
    path = os.path.join(UPLOAD_FOLDER, fn)
    f.save(path)
    
    with open(path, "rb") as fi: enc = base64.b64encode(fi.read()).decode('utf-8')
    
    cmd = "SEND_GROUP_MSG" if is_g else "SEND_MSG"
    backend.send({"command": cmd, "to": to, "msg": enc, "is_file": True, "filename": fn})
    backend.db.save_msg(to, backend.username, fn, True, time.ctime(), is_g)
    return jsonify({"status": "ok", "filename": fn, "time": time.ctime()})

@app.route('/api/action', methods=['POST'])
def action():
    d = request.json
    backend.send(d)
    return jsonify({"status": "ok"})

@app.route('/api/updates')
def updates():
    out = list(backend.msg_queue)
    backend.msg_queue.clear()
    return jsonify(out)

@app.route('/api/history')
def history():
    target = request.args.get('target')
    if not target: return jsonify([])
    hist = backend.db.get_history(target)
    # [sender, content, is_file, time]
    # If empty locally, fetch from server (server will send HISTORY type msg later)
    if not hist: backend.send({"command": "GET_HISTORY", "of_user": target})
    return jsonify([{"sender": h[0], "content": h[1], "is_file": h[2], "time": h[3]} for h in hist])

@app.route('/logout')
def logout():
    backend.send({"command": "LOGOUT"})
    backend.reset_state()
    session.clear()
    return redirect('/')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5000)
    args = parser.parse_args()
    app.run(host='0.0.0.0', port=args.port, debug=True, threaded=True)