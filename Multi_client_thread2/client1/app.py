from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import socket
import threading
import queue
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Configuration ---
SERVER_IP = "127.0.0.1"
SERVER_PORT = 5000
MY_IP = "10.75.16.16"
UDP_AUDIO_PORT = 5001
UDP_VIDEO_PORT = 5002

# --- Global State ---
client_socket = None
connected = False
username = ""

# Locks and Events
socket_lock = threading.Lock() # Ensures only one thread touches the socket at a time
response_queue = queue.Queue() # For passing data from listener to main thread

# Buffer must be bytes to avoid Unicode decode errors on partial chunks
recv_buffer = b"" 

# State flags
waiting_for_call_response = False

# --- Helper Functions ---

def reset_connection():
    """Cleans up socket and state on disconnect"""
    global client_socket, connected, recv_buffer
    connected = False
    recv_buffer = b""
    if client_socket:
        try:
            client_socket.close()
        except:
            pass
    client_socket = None
    socketio.emit('status', {'msg': 'Disconnected from server.'})

def send_message(sock, msg):
    """Thread-safe sending with error handling"""
    global connected
    if not sock or not connected:
        return False
    
    try:
        with socket_lock:
            sock.sendall((msg + '\n').encode('utf-8'))
        return True
    except Exception as e:
        print(f"Send Error: {e}")
        reset_connection()
        return False

def recv_line(sock):
    """
    Robustly receives data until a newline is found.
    Handles buffer management and decoding errors.
    """
    global recv_buffer
    
    try:
        while b'\n' not in recv_buffer:
            try:
                # Non-blocking check or timeout could go here
                chunk = sock.recv(4096)
                if not chunk:
                    return None # Socket closed by remote
                recv_buffer += chunk
            except socket.timeout:
                continue # Just loop back if timeout
            except BlockingIOError:
                continue
            except Exception as e:
                print(f"Recv Error: {e}")
                return None

        # Split the buffer at the first newline
        line_bytes, recv_buffer = recv_buffer.split(b'\n', 1)
        return line_bytes.decode('utf-8').strip()
    except Exception as e:
        print(f"Decoding Error: {e}")
        return None

# --- Background Listener Thread ---

def socket_client_receive():
    global connected, waiting_for_call_response
    
    print("Listener thread started...")
    
    while connected and client_socket:
        try:
            # We do NOT lock here indefinitely, otherwise we block sending
            # We only read. The OS handles the socket buffer.
            msg = recv_line(client_socket)
            
            if msg is None:
                print("Server closed connection.")
                reset_connection()
                break

            # Logic: If main thread is waiting for a specific response, 
            # put it in the queue. Otherwise, emit to browser.
            if waiting_for_call_response:
                # Check if this message looks like a call response
                # (This logic depends on your server protocol strictness)
                is_protocol_msg = msg in ["yes", "no", "0"] or (":" in msg and msg.count(":") >= 2)
                
                if is_protocol_msg:
                    response_queue.put(msg)
                    continue 
            
            # Normal Message Handling
            if ":::calling" in msg:
                try:
                    caller, _ = msg.split(":::", 1)
                    socketio.emit('incoming_call', {'caller': caller})
                except ValueError:
                    pass
            else:
                socketio.emit('message', {'msg': msg})
                
        except Exception as e:
            print(f"Listener Exception: {e}")
            reset_connection()
            break

# --- Flask Routes & Events ---

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect_to_server')
def handle_connect(data):
    global client_socket, connected, username
    
    if connected:
        emit('status', {'msg': 'Already connected!'})
        return

    username = data.get('username', 'Guest').strip()

    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.settimeout(5.0) # 5 Second timeout for operations
        client_socket.connect((SERVER_IP, SERVER_PORT))
        
        # Send username immediately
        client_socket.sendall((username + '\n').encode('utf-8'))
        
        connected = True
        
        # Start background thread
        t = threading.Thread(target=socket_client_receive, daemon=True)
        t.start()

        emit('status', {'msg': f'Connected to server as {username}'})
    except Exception as e:
        reset_connection()
        emit('status', {'msg': f'Failed to connect: {e}'})

@socketio.on('send_message')
def handle_send_message(data):
    if connected:
        msg = data['msg']
        if send_message(client_socket, msg):
            emit('message', {'msg': f"You: {msg}"})
        else:
            emit('status', {'msg': 'Failed to send. Connection lost.'})

@socketio.on('start_call')
def handle_start_call(data):
    global waiting_for_call_response
    
    if not connected:
        emit('status', {'msg': 'Not connected to server.'})
        return

    target = data['target']
    
    # 1. Send the Call Request
    if not send_message(client_socket, f"{target}:::call"):
        emit('call_response', {'msg': 'Connection lost during call setup.'})
        return

    # 2. Wait for response via Queue (Timeout 10s)
    waiting_for_call_response = True
    
    try:
        # Wait for "0", "yes", or IP info
        ans = response_queue.get(timeout=10) 
        
        if ans == "0":
             emit('call_response', {'msg': f"{target} declined or unavailable."})
             waiting_for_call_response = False
             return

        # 3. If accepted, send MY IP info
        if not send_message(client_socket, f"{MY_IP}:{UDP_AUDIO_PORT}:{UDP_VIDEO_PORT}"):
             waiting_for_call_response = False
             return

        # 4. Wait for THEIR IP info
        recv_ip_data = response_queue.get(timeout=10)
        waiting_for_call_response = False
        
        try:
            ip, audio, video = recv_ip_data.split(":")
            emit('call_response', {'msg': f"Call established! Peer: {ip}, Audio: {audio}, Video: {video}"})
        except ValueError:
             emit('call_response', {'msg': 'Invalid data received from peer.'})

    except queue.Empty:
        waiting_for_call_response = False
        emit('call_response', {'msg': 'Call request timed out (No response).'})
    except Exception as e:
        waiting_for_call_response = False
        emit('call_response', {'msg': f'Error: {e}'})

@socketio.on('answer_call')
def handle_answer_call(data):
    global waiting_for_call_response
    
    answer = data['answer'] # 'y' or 'n'
    
    if not connected: 
        return

    try:
        if answer.lower() == 'y':
            # 1. Send Yes
            send_message(client_socket, "yes")
            
            # 2. Send My IP
            send_message(client_socket, f"{MY_IP}:{UDP_AUDIO_PORT}:{UDP_VIDEO_PORT}")
            
            # 3. Wait for Peer IP (Need to hijack the queue temporarily)
            waiting_for_call_response = True
            try:
                recv = response_queue.get(timeout=10)
                ip, audio, video = recv.split(":")
                socketio.emit('call_accepted', {'msg': f"Call connected - Peer: {ip}"})
            except queue.Empty:
                socketio.emit('status', {'msg': 'Timed out waiting for peer IP.'})
            finally:
                waiting_for_call_response = False
        else:
            send_message(client_socket, "no")
            
    except Exception as e:
        socketio.emit('status', {'msg': f'Error answering call: {e}'})

if __name__ == '__main__':
    # 'allow_unsafe_werkzeug' needed sometimes if using standard threading
    socketio.run(app, debug=True, port=5500, allow_unsafe_werkzeug=True)