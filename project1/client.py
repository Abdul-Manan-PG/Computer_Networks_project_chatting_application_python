import threading
import time
from flask import Flask, render_template, request, redirect, url_for, jsonify
import json
import os
from datetime import datetime
import socket

tcp_lock = threading.Lock()
USERNAME = "Manan"     # <-- change for each device

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
FRIENDS_FILE = os.path.join(DATA_DIR, 'friends.txt')
MESSAGES_FILE = os.path.join(DATA_DIR, 'messages.json')
os.makedirs(DATA_DIR, exist_ok=True)

# Initialize data files
if not os.path.exists(FRIENDS_FILE):
    with open(FRIENDS_FILE, 'w', encoding='utf-8') as f:
        f.write('Alice\nBob\nCharlie')

if not os.path.exists(MESSAGES_FILE):
    initial = {
        "Alice": [{"sender": "Alice", "text": "Hey! How are you?", "time": "2025-11-15 18:00"}],
        "Bob": [],
        "Charlie": []
    }
    with open(MESSAGES_FILE, 'w', encoding='utf-8') as f:
        json.dump(initial, f, indent=2)

# TCP client socket
client = None
Host = '10.75.16.16'
Port = 5000
connected_event = threading.Event()

def connect_to_server(retries=5, delay=2):
    global client
    attempt = 0

    while attempt < retries:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((Host, Port))

            # identify our username
            sock.sendall(USERNAME.encode())

            client = sock
            print("[CLIENT] Connected to TCP server")
            connected_event.set()
            return

        except Exception as e:
            print(f"[CLIENT] Attempt {attempt+1} failed: {e}")
            attempt += 1
            time.sleep(delay)

    print("[CLIENT] Could not connect to TCP server")


# Start connection in background before first request
threading.Thread(target=connect_to_server, daemon=True).start()

# Utility functions
def load_friends():
    with open(FRIENDS_FILE, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]

def load_messages():
    with open(MESSAGES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_messages(messages):
    with open(MESSAGES_FILE, 'w', encoding='utf-8') as f:
        json.dump(messages, f, indent=2)

# Routes
@app.route('/')
def index():
    if not connected_event.is_set():
        return "<h2>Connecting to server... Please wait.</h2>"
    friends = load_friends()
    return render_template('chat.html', friends=friends, active=None, messages=[])

@app.route('/chat/<friend>')
def chat(friend):
    if not connected_event.is_set():
        return "<h2>Connecting to server... Please wait.</h2>"
    friends = load_friends()
    messages = load_messages()
    return render_template('chat.html', friends=friends, active=friend, messages=messages.get(friend, []))

@app.route('/send', methods=['POST'])
def send():
    if not connected_event.is_set():
        return "<h2>Cannot send message. Server not connected.</h2>"

    friend = request.form.get('friend')
    text = request.form.get('text', '').strip()
    filename = request.form.get('filename', '').strip()
    if not friend or not text:
        return redirect('/')

    messages = load_messages()
    final_text = text
    if filename:
        final_text += f" [sent file: {filename}]"

    messages.setdefault(friend, []).append({
        "sender": "me",
        "text": final_text,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    save_messages(messages)

    # Send to TCP server
    try:
        client.sendall(final_text.encode())
    except Exception as e:
        print(f"Failed to send to server: {e}")

    return redirect(url_for('chat', friend=friend))

@app.route('/api/send', methods=['POST'])
def api_send():
    if not connected_event.is_set():
        return jsonify({"ok": False, "error": "Server not connected"})
    data = request.get_json()
    friend = data.get('friend')
    text = data.get('text', '').strip()
    if not friend or not text:
        return jsonify({"ok": False})

    messages = load_messages()
    messages.setdefault(friend, []).append({
        "sender": "me",
        "text": text,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    save_messages(messages)

    try:
        client.sendall(text.encode())
    except Exception as e:
        print(f"Failed to send to server: {e}")

    return jsonify({"ok": True})

def request_status(friend):
    if client is None:
        return "offline"

    with tcp_lock:
        for i in range(5):
            try:
                msg = f"STATUS:{friend}"
                client.sendall(msg.encode())

                data = client.recv(1024)
                if data:
                    return data.decode().strip()

            except:
                pass

            time.sleep(2)

    return "offline"


@app.route('/api/status/<friend>')
def friend_status(friend):
    status = request_status(friend)
    return jsonify({"friend": friend, "status": status})

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
