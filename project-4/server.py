import socket
import threading
import json
import time
from chat_db import ChatDatabase

# Configuration
HOST = '0.0.0.0'
TCP_PORT = 5555

class ChatServer:
    def __init__(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((HOST, TCP_PORT))
        self.server_socket.listen()
        self.db = ChatDatabase()
        self.clients = {}  # Map username -> socket object
        print(f"Server started on {HOST}:{TCP_PORT}")

    def broadcast(self, message, exclude_user=None):
        """Send a raw text message to all connected clients."""
        for user, client_sock in self.clients.items():
            if user != exclude_user:
                try:
                    client_sock.send(message.encode('utf-8'))
                except:
                    pass

    def broadcast_json(self, data, exclude_user=None):
        """Send a JSON object to all connected clients."""
        msg = json.dumps(data)
        for user, client_sock in self.clients.items():
            if user != exclude_user:
                try:
                    client_sock.send(msg.encode('utf-8'))
                except:
                    pass

    def handle_client(self, client_socket, addr):
        print(f"New connection from {addr}")
        user = None
        
        try:
            while True:
                data = client_socket.recv(4096).decode('utf-8')
                if not data:
                    break
                
                request = json.loads(data)
                command = request.get('command')
                response = {"status": "error", "message": "Unknown command"}

                # --- Auth Handling ---
                if command == 'REGISTER':
                    success = self.db.register_user(request['username'], request['password'])
                    response = {"status": "success", "message": "Registration successful"} if success else {"status": "error", "message": "Username taken"}
                    client_socket.send(json.dumps(response).encode('utf-8'))

                elif command == 'LOGIN':
                    success = self.db.validate_login(request['username'], request['password'])
                    if success:
                        user = request['username']
                        udp_port = request.get('udp_port', 0)
                        self.db.update_user_address(user, addr[0], udp_port)
                        self.clients[user] = client_socket
                        
                        response = {"status": "success", "message": f"Welcome {user}!"}
                        client_socket.send(json.dumps(response).encode('utf-8'))
                        
                        # Notify others that I am ONLINE
                        self.broadcast_json({
                            "type": "STATUS_UPDATE", 
                            "username": user, 
                            "status": "Online"
                        }, exclude_user=user)
                    else:
                        response = {"status": "error", "message": "Invalid credentials"}
                        client_socket.send(json.dumps(response).encode('utf-8'))

                # --- Logic that requires login ---
                elif user:
                    if command == 'SEND_MSG':
                        recipient = request['to']
                        msg = request['message']
                        self.db.save_message(user, recipient, msg)

                        if recipient in self.clients:
                            payload = {
                                "type": "MESSAGE",
                                "from": user,
                                "content": msg,
                                "timestamp": time.ctime()
                            }
                            try:
                                self.clients[recipient].send(json.dumps(payload).encode('utf-8'))
                                response = {"status": "success", "message": "Message sent"}
                            except:
                                response = {"status": "error", "message": "Recipient disconnected"}
                        else:
                            response = {"status": "success", "message": "Message saved (User offline)"}
                        
                        client_socket.send(json.dumps(response).encode('utf-8'))

                    elif command == 'ADD_FRIEND':
                        res = self.db.add_friend(user, request['friend_name'])
                        client_socket.send(json.dumps({"status": "info", "message": res}).encode('utf-8'))

                    elif command == 'GET_FRIENDS':
                        # Get basic list of strings from DB
                        friends_list = self.db.get_friends(user)
                        
                        # Enrich with Online/Offline status
                        enriched_friends = []
                        for f in friends_list:
                            status = "Online" if f in self.clients else "Offline"
                            enriched_friends.append({"username": f, "status": status})

                        client_socket.send(json.dumps({"status": "success", "data": enriched_friends}).encode('utf-8'))

                    elif command == 'GET_FRIENDS_STATUS':
                        # Simple helper to just check specific friends
                        friends_list = self.db.get_friends(user)
                        status_map = {f: ("Online" if f in self.clients else "Offline") for f in friends_list}
                        client_socket.send(json.dumps({"type": "STATUS_SYNC", "data": status_map}).encode('utf-8'))

                    elif command == 'GET_HISTORY':
                        friend = request['of_user']
                        history = self.db.get_chat_history(user, friend)
                        client_socket.send(json.dumps({
                            "status": "success", 
                            "data": history,
                            "with_user": friend 
                        }).encode('utf-8'))

                    elif command == 'INIT_CALL':
                        callee = request['callee']
                        addr_info = self.db.get_user_address(callee)
                        
                        if addr_info and callee in self.clients:
                            call_id = self.db.log_call(user, callee, "INITIATED")
                            client_socket.send(json.dumps({
                                "status": "success",
                                "type": "CALL_INFO",
                                "target_ip": addr_info[0],
                                "target_port": addr_info[1],
                                "call_id": call_id
                            }).encode('utf-8'))
                            
                            self.clients[callee].send(json.dumps({
                                "type": "INCOMING_CALL",
                                "from": user,
                                "caller_ip": addr[0]
                            }).encode('utf-8'))
                        else:
                            client_socket.send(json.dumps({"status": "error", "message": "User offline"}).encode('utf-8'))

        except Exception as e:
            print(f"Error with {addr}: {e}")
        finally:
            if user and user in self.clients:
                del self.clients[user]
                # Notify others that I am OFFLINE
                self.broadcast_json({
                    "type": "STATUS_UPDATE", 
                    "username": user, 
                    "status": "Offline"
                })
            client_socket.close()

    def start(self):
        while True:
            client, addr = self.server_socket.accept()
            thread = threading.Thread(target=self.handle_client, args=(client, addr))
            thread.start()

if __name__ == "__main__":
    server = ChatServer()
    server.start()