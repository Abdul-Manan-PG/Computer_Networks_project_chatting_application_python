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

    def send_json(self, sock, data):
        """Helper to send JSON data with a newline delimiter."""
        try:
            msg = json.dumps(data) + "\n"
            sock.send(msg.encode('utf-8'))
        except Exception as e:
            print(f"Send error: {e}")

    def broadcast_json(self, data, exclude_user=None):
        """Send a JSON object to all connected clients."""
        msg = json.dumps(data) + "\n"
        encoded_msg = msg.encode('utf-8')
        
        for user, client_sock in self.clients.items():
            if user != exclude_user:
                try:
                    client_sock.send(encoded_msg)
                except:
                    pass

    def handle_client(self, client_socket, addr):
        print(f"New connection from {addr}")
        user = None
        buffer = ""
        
        try:
            while True:
                data = client_socket.recv(4096).decode('utf-8')
                if not data:
                    break
                
                buffer += data
                
                while "\n" in buffer:
                    message_str, buffer = buffer.split("\n", 1)
                    if not message_str.strip():
                        continue

                    try:
                        request = json.loads(message_str)
                    except json.JSONDecodeError:
                        continue

                    command = request.get('command')
                    
                    # --- Auth Handling ---
                    if command == 'REGISTER':
                        success = self.db.register_user(request['username'], request['password'])
                        response = {"status": "success", "message": "Registration successful"} if success else {"status": "error", "message": "Username taken"}
                        self.send_json(client_socket, response)

                    elif command == 'LOGIN':
                        success = self.db.validate_login(request['username'], request['password'])
                        if success:
                            user = request['username']
                            udp_port = request.get('udp_port', 0)
                            self.db.update_user_address(user, addr[0], udp_port)
                            self.clients[user] = client_socket
                            
                            self.send_json(client_socket, {"status": "success", "message": f"Welcome {user}!"})
                            
                            # Notify others I am ONLINE
                            self.broadcast_json({
                                "type": "STATUS_UPDATE", 
                                "username": user, 
                                "status": "Online"
                            }, exclude_user=user)
                        else:
                            self.send_json(client_socket, {"status": "error", "message": "Invalid credentials"})

                    # --- Logic that requires login ---
                    elif user:
                        if command == 'LOGOUT':
                            # 1. Remove user immediately
                            if user in self.clients:
                                del self.clients[user]
                            
                            # 2. Notify others I am OFFLINE
                            self.broadcast_json({
                                "type": "STATUS_UPDATE", 
                                "username": user, 
                                "status": "Offline"
                            })
                            
                            # 3. Confirm logout to client
                            self.send_json(client_socket, {"status": "success", "message": "Logged out"})
                            
                            # 4. Close connection loop
                            return 

                        elif command == 'SEND_MSG':
                            recipient = request['to']
                            msg = request['message']

                            # STRICT RULE: Cannot send to offline user
                            if recipient in self.clients:
                                # User is Online - Save and Send
                                self.db.save_message(user, recipient, msg)
                                
                                payload = {
                                    "type": "MESSAGE",
                                    "from": user,
                                    "content": msg,
                                    "timestamp": time.ctime()
                                }
                                try:
                                    self.send_json(self.clients[recipient], payload)
                                    self.send_json(client_socket, {"status": "success", "message": "Message sent"})
                                except:
                                    self.send_json(client_socket, {"status": "error", "message": "Recipient connection failed"})
                            else:
                                # User is Offline - REJECT message
                                self.send_json(client_socket, {"status": "error", "message": "User is Offline. Cannot send message."})

                        elif command == 'ADD_FRIEND':
                            res = self.db.add_friend(user, request['friend_name'])
                            self.send_json(client_socket, {"status": "info", "message": res})

                        elif command == 'GET_FRIENDS':
                            friends_list = self.db.get_friends(user)
                            enriched_friends = []
                            for f in friends_list:
                                status = "Online" if f in self.clients else "Offline"
                                enriched_friends.append({"username": f, "status": status})

                            self.send_json(client_socket, {"status": "success", "data": enriched_friends})
                        
                        elif command == 'CHECK_STATUS':
                            # Allow client to explicitly ask for a status
                            target = request['target']
                            status = "Online" if target in self.clients else "Offline"
                            self.send_json(client_socket, {
                                "type": "STATUS_UPDATE",
                                "username": target,
                                "status": status
                            })

                        elif command == 'GET_HISTORY':
                            friend = request['of_user']
                            history = self.db.get_chat_history(user, friend)
                            self.send_json(client_socket, {
                                "status": "success", 
                                "data": history,
                                "with_user": friend 
                            })

                        elif command == 'INIT_CALL':
                            callee = request['callee']
                            addr_info = self.db.get_user_address(callee)
                            
                            if addr_info and callee in self.clients:
                                call_id = self.db.log_call(user, callee, "INITIATED")
                                self.send_json(client_socket, {
                                    "status": "success",
                                    "type": "CALL_INFO",
                                    "target_ip": addr_info[0],
                                    "target_port": addr_info[1],
                                    "call_id": call_id
                                })
                                
                                self.send_json(self.clients[callee], {
                                    "type": "INCOMING_CALL",
                                    "from": user,
                                    "caller_ip": addr[0]
                                })
                            else:
                                self.send_json(client_socket, {"status": "error", "message": "User offline"})

        except Exception as e:
            print(f"Error with {addr}: {e}")
        finally:
            if user and user in self.clients:
                del self.clients[user]
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