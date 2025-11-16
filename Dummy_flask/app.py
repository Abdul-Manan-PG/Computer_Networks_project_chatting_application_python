from flask import Flask, render_template, request, redirect, url_for, jsonify
import json
import os
from datetime import datetime

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
FRIENDS_FILE = os.path.join(DATA_DIR, 'friends.txt')
MESSAGES_FILE = os.path.join(DATA_DIR, 'messages.json')

os.makedirs(DATA_DIR, exist_ok=True)

# initialize files if they don't exist
if not os.path.exists(FRIENDS_FILE):
    with open(FRIENDS_FILE, 'w', encoding='utf-8') as f:
        f.write('Alice\nBob\nCharlie')

if not os.path.exists(MESSAGES_FILE):
    initial = {
        "Alice": [
            {"sender": "Alice", "text": "Hey! How are you?", "time": "2025-11-15 18:00"},
            {"sender": "me", "text": "I'm good — working on a Flask demo.", "time": "2025-11-15 18:05"}
        ],
        "Bob": [
            {"sender": "Bob", "text": "Want to play tonight?", "time": "2025-11-12 20:10"}
        ],
        "Charlie": []
    }
    with open(MESSAGES_FILE, 'w', encoding='utf-8') as f:
        json.dump(initial, f, indent=2)


def load_friends():
    with open(FRIENDS_FILE, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]


def load_messages():
    with open(MESSAGES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_messages(messages):
    with open(MESSAGES_FILE, 'w', encoding='utf-8') as f:
        json.dump(messages, f, indent=2)


@app.route('/')
def index():
    friends = load_friends()
    return render_template('chat.html', friends=friends, active=None, messages=[])


@app.route('/chat/<friend>')
def chat(friend):
    friends = load_friends()
    messages = load_messages()
    return render_template('chat.html', friends=friends, active=friend, messages=messages.get(friend, []))


@app.route('/send', methods=['POST'])
def send():
    friend = request.form.get('friend')
    text = request.form.get('text', '').strip()
    filename = request.form.get('filename', '').strip()

    if not friend:
        return redirect('/')

    messages = load_messages()

    final_text = text
    if filename:
        final_text += f" [sent file: {filename}]"

    if final_text:
        messages.setdefault(friend, []).append({
            "sender": "me",
            "text": final_text,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M")
        })

    save_messages(messages)
    return redirect(url_for('chat', friend=friend))


@app.route('/api/send', methods=['POST'])
def api_send():
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
    return jsonify({"ok": True})


if __name__ == '__main__':
    app.run(host="10.75.16.16", port=5000, debug=True)
