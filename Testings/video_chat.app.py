from flask import Flask, render_template_string
from flask_socketio import Flask, SocketIO, emit, request

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-very-secret-key!' # Change this
socketio = SocketIO(app)

# This is our "database" of online users.
# It will store { 'user_id_123': 'connection_id_abc' }
online_users = {}

# The HTML and JavaScript for the client
# This is what the user sees in their browser
HTML = """
<html>
<head>
    <title>Socket.IO User Chat</title>
</head>
<body>
    <h1>My User ID: <span id="my_id_display"></span></h1>
    <hr>
    <div>
        <input id="my_id" type="text" placeholder="Enter Your User ID">
        <button id="login_button">Login</button>
    </div>
    <hr>
    <h2>Send a Message</h2>
    <div>
        <input id="to_id" type="text" placeholder="Recipient's User ID">
        <input id="message" type="text" placeholder="Your Message">
        <button id="send_button">Send</button>
    </div>
    <hr>
    <h2>Messages Received</h2>
    <ul id="messages"></ul>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
    <script>
        // Connect to the server
        var socket = io();
        var my_id = "";

        // --- 1. Login ---
        document.getElementById("login_button").onclick = function() {
            my_id = document.getElementById("my_id").value;
            if (my_id) {
                // Tell the server "This is my ID"
                socket.emit('register', { 'user_id': my_id });
                document.getElementById("my_id_display").innerText = my_id;
                console.log("Logged in as: " + my_id);
            }
        };

        // --- 2. Send Message ---
        document.getElementById("send_button").onclick = function() {
            var to_id = document.getElementById("to_id").value;
            var msg = document.getElementById("message").value;
            if (to_id && msg) {
                // Tell the server to send this message
                socket.emit('private_message', { 'to_id': to_id, 'message': msg });
                console.log("Sending message to " + to_id + ": " + msg);
                // Clear inputs
                document.getElementById("message").value = "";
            }
        };

        // --- 3. Receive Message ---
        socket.on('new_message', function(data) {
            console.log("Message received:", data);
            var item = document.createElement('li');
            item.textContent = "From " + data.from_id + ": " + data.message;
            document.getElementById("messages").appendChild(item);
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    """Serve the HTML page"""
    return render_template_string(HTML)

# --- Socket.IO Event Handlers ---

@socketio.on('connect')
def handle_connect():
    print(f"Client connected with ID: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    print(f"Client disconnected: {request.sid}")
    # Find the user_id for this connection and remove them
    user_id_to_remove = None
    for user_id, sid in online_users.items():
        if sid == request.sid:
            user_id_to_remove = user_id
            break
    if user_id_to_remove:
        del online_users[user_id_to_remove]
        print(f"User {user_id_to_remove} went offline.")

@socketio.on('register')
def handle_register(data):
    """A user tells us their ID."""
    user_id = data['user_id']
    connection_id = request.sid
    
    # Save this user in our "database"
    online_users[user_id] = connection_id
    
    print(f"User '{user_id}' registered with connection ID: {connection_id}")
    print("Online users:", online_users)

@socketio.on('private_message')
def handle_private_message(data):
    """A user wants to send a message to another user."""
    to_id = data['to_id']
    message = data['message']
    
    # Find the sender's ID
    from_id = None
    for user_id, sid in online_users.items():
        if sid == request.sid:
            from_id = user_id
            break
            
    if not from_id:
        print("Could not find sender. Message not sent.")
        return

    # Find the recipient's connection ID
    recipient_sid = online_users.get(to_id)
    
    if recipient_sid:
        # Send the message ONLY to that recipient
        print(f"Sending message from '{from_id}' to '{to_id}' (SID: {recipient_sid})")
        emit('new_message', 
             { 'from_id': from_id, 'message': message }, 
             to=recipient_sid)
    else:
        print(f"User '{to_id}' is not online. Message not sent.")
        # You could also send an error back to the sender here
        emit('error_message', {'info': f"User '{to_id}' is not online."})


if __name__ == '__main__':
    print("Starting server... Open http://127.0.0.1:5000 in your browser.")
    socketio.run(app, debug=True, port=5000, allow_unsafe_werkzeug=True)