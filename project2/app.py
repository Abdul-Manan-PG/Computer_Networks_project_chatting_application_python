from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
import os
import json
from datetime import datetime

# --- App Setup ---
app = Flask(__name__)
# A secret key is required for Flask sessions (for logins)
app.config['SECRET_KEY'] = 'your-very-secret-key-12345!'
socketio = SocketIO(app)

# --- Database File Paths ---
DATA_DIR = os.path.join(os.path.dirname(__file__))
DATABASE_FILE = os.path.join(DATA_DIR, 'database.json')
MESSAGES_FILE = os.path.join(DATA_DIR, 'messages.json')

# --- Helper Functions ---
def load_db():
    """Loads the user/friends database."""
    with open(DATABASE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_messages():
    """Loads all message histories."""
    if not os.path.exists(MESSAGES_FILE):
        return {}
    try:
        with open(MESSAGES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {} # Return empty dict if file is empty or corrupt

def save_messages(messages):
    """Saves all message histories."""
    with open(MESSAGES_FILE, 'w', encoding='utf-8') as f:
        json.dump(messages, f, indent=2)

# --- Presence Tracking ---
# Tracks online users: {"username": "socket_id"}
ONLINE_USERS = {}

# --- Authentication Routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        db = load_db()
        
        # Check if user exists and password is correct
        if username in db.get("users", {}) and db["users"][username] == password:
            session['username'] = username  # Log the user in
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Invalid username or password")
    
    # If already logged in, go to main page
    if 'username' in session:
        return redirect(url_for('index'))
        
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))

# --- Main Application Routes (Protected) ---

@app.route('/')
def index():
    """Main dashboard, shows friend list."""
    if 'username' not in session:
        return redirect(url_for('login'))
    
    username = session['username']
    db = load_db()
    
    # Get the user's specific friend list
    my_friends = db.get("friends", {}).get(username, [])
    
    return render_template('chat.html', 
                           friends=my_friends, 
                           active_friend=None, 
                           messages=[])

@app.route('/chat/<friend>')
def chat(friend):
    """Shows the chat window with a specific friend."""
    if 'username' not in session:
        return redirect(url_for('login'))
    
    username = session['username']
    db = load_db()
    my_friends = db.get("friends", {}).get(username, [])
    
    # Security check: only allow chatting with people on your friends list
    if friend not in my_friends:
        return redirect(url_for('index'))

    # Load this user's message history for this friend
    all_messages = load_messages()
    chat_history = all_messages.get(username, {}).get(friend, [])
    
    return render_template('chat.html', 
                           friends=my_friends, 
                           active_friend=friend, 
                           messages=chat_history)

# --- SocketIO Handlers for Real-Time ---

@socketio.on('connect')
def on_connect():
    """Handle a new user connection."""
    if 'username' not in session:
        return False # Disconnect if not logged in
    
    username = session['username']
    ONLINE_USERS[username] = request.sid
    print(f"[CONNECTED] {username} (sid: {request.sid})")
    
    # Tell EVERYONE about the new online user list
    emit('user_list_update', list(ONLINE_USERS.keys()), broadcast=True)

@socketio.on('disconnect')
def on_disconnect():
    """Handle a user disconnection."""
    if 'username' in session:
        username = session['username']
        if username in ONLINE_USERS:
            del ONLINE_USERS[username]
            print(f"[DISCONNECTED] {username}")
            # Tell EVERYONE about the updated online user list
            emit('user_list_update', list(ONLINE_USERS.keys()), broadcast=True)

@socketio.on('chat_message')
def handle_message(data):
    """Handle a new text chat message and save it."""
    if 'username' not in session:
        return

    sender = session['username']
    recipient = data['recipient']
    text = data['text']
    
    # Create message objects
    sender_msg = {
        "sender": "me", 
        "text": text,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    recipient_msg = {
        "sender": sender, 
        "text": text,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    
    # Load all messages
    all_messages = load_messages()

    # 1. Add message to sender's history (as "me")
    all_messages.setdefault(sender, {}).setdefault(recipient, []).append(sender_msg)
    
    # 2. Add message to recipient's history (as "sender")
    all_messages.setdefault(recipient, {}).setdefault(sender, []).append(recipient_msg)
    
    # 3. Save the updated messages file
    save_messages(all_messages)
    
    # 4. Send the message to the recipient if they are online
    recipient_sid = ONLINE_USERS.get(recipient)
    if recipient_sid:
        emit('new_message', recipient_msg, to=recipient_sid)

# --- WebRTC Signaling (Private 1-to-1) ---

@socketio.on('webrtc_offer')
def handle_offer(data):
    """Relay a WebRTC offer to a specific user."""
    sender = session['username']
    recipient = data['recipient']
    recipient_sid = ONLINE_USERS.get(recipient)
    
    if recipient_sid:
        print(f"[OFFER] From {sender} to {recipient}")
        emit('webrtc_offer', {'sender': sender, 'sdp': data['sdp']}, to=recipient_sid)

@socketio.on('webrtc_answer')
def handle_answer(data):
    """Relay a WebRTC answer to a specific user."""
    sender = session['username']
    recipient = data['recipient']
    recipient_sid = ONLINE_USERS.get(recipient)
    
    if recipient_sid:
        print(f"[ANSWER] From {sender} to {recipient}")
        emit('webrtc_answer', {'sender': sender, 'sdp': data['sdp']}, to=recipient_sid)

@socketio.on('webrtc_candidate')
def handle_candidate(data):
    """Relay a WebRTC ICE candidate to a specific user."""
    sender = session['username']
    recipient = data['recipient']
    recipient_sid = ONLINE_USERS.get(recipient)
    
    if recipient_sid:
        print(f"[CANDIDATE] From {sender} to {recipient}")
        emit('webrtc_candidate', {'sender': sender, 'candidate': data['candidate']}, to=recipient_sid)

# --- Run the App ---
if __name__ == '__main__':
    print("[SERVER] Starting Flask-SocketIO server...")
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)