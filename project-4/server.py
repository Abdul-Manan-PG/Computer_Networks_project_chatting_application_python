import socket
import threading
import json
import time
from chat_db import ChatDatabase

HOST = '0.0.0.0'
TCP_PORT = 5555

class ChatServer:
    def __init__(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((HOST, TCP_PORT))
        self.server_socket.listen()
        self.db = ChatDatabase()
        self.clients = {} 
        print(f"Server started on {HOST}:{TCP_PORT}")

    def send_json(self, sock, data):
        try:
            msg = json.dumps(data) + "\n"
            sock.send(msg.encode('utf-8'))
        except Exception as e:
            print(f"Send error: {e}")

    def broadcast_json(self, data, exclude_user=None):
        msg = json.dumps(data) + "\n"
        encoded_msg = msg.encode('utf-8')
        for user, client_sock in self.clients.items():
            if user != exclude_user:
                try: client_sock.send(encoded_msg)
                except: pass

    def handle_client(self, client_socket, addr):
        print(f"New connection from {addr}")
        user = None
        buffer = ""
        
        try:
            while True:
                data = client_socket.recv(1024*1024).decode('utf-8') # Increased buffer for files
                if not data: break
                buffer += data
                
                while "\n" in buffer:
                    message_str, buffer = buffer.split("\n", 1)
                    if not message_str.strip(): continue
                    try: request = json.loads(message_str)
                    except: continue

                    command = request.get('command')
                    
                    if command == 'REGISTER':
                        success = self.db.register_user(request['username'], request['password'])
                        response = {"status": "success", "message": "Registered"} if success else {"status": "error", "message": "Username taken"}
                        self.send_json(client_socket, response)

                    elif command == 'LOGIN':
                        if self.db.validate_login(request['username'], request['password']):
                            user = request['username']
                            self.db.update_user_address(user, addr[0], request.get('udp_port', 0))
                            self.clients[user] = client_socket
                            self.send_json(client_socket, {"status": "success", "message": f"Welcome {user}!"})
                            self.broadcast_json({"type": "STATUS_UPDATE", "username": user, "status": "Online"}, exclude_user=user)
                        else:
                            self.send_json(client_socket, {"status": "error", "message": "Invalid credentials"})

                    elif user:
                        if command == 'LOGOUT':
                            if user in self.clients: del self.clients[user]
                            self.broadcast_json({"type": "STATUS_UPDATE", "username": user, "status": "Offline"})
                            self.send_json(client_socket, {"status": "success"})
                            return 

                        elif command == 'SEND_MSG':
                            recipient = request['to']
                            msg_content = request['message'] # For text, this is text. For file, this is base64
                            msg_type = request.get('msg_type', 'text')
                            filename = request.get('filename', '')

                            if recipient in self.clients:
                                # We do NOT save file content to DB to save space, only filename
                                # If text, save text. If file, save filename + " (File)"
                                db_content = filename if msg_type != 'text' else msg_content
                                self.db.save_message(user, recipient, db_content)
                                
                                payload = {
                                    "type": "MESSAGE",
                                    "from": user,
                                    "content": msg_content, # Send full base64 to recipient
                                    "msg_type": msg_type,
                                    "filename": filename,
                                    "timestamp": time.ctime()
                                }
                                try:
                                    self.send_json(self.clients[recipient], payload)
                                    self.send_json(client_socket, {"status": "success", "message": "Sent"})
                                except:
                                    self.send_json(client_socket, {"status": "error", "message": "Send Failed"})
                            else:
                                self.send_json(client_socket, {"status": "error", "message": "User Offline"})

                        elif command == 'ADD_FRIEND':
                            res = self.db.add_friend(user, request['friend_name'])
                            self.send_json(client_socket, {"status": "info", "message": res})

                        elif command == 'GET_FRIENDS':
                            friends = self.db.get_friends(user)
                            data = [{"username": f, "status": "Online" if f in self.clients else "Offline"} for f in friends]
                            self.send_json(client_socket, {"status": "success", "data": data})
                        
                        elif command == 'CHECK_STATUS':
                            target = request['target']
                            status = "Online" if target in self.clients else "Offline"
                            self.send_json(client_socket, {"type": "STATUS_UPDATE", "username": target, "status": status})

                        elif command == 'GET_HISTORY':
                            friend = request['of_user']
                            history = self.db.get_chat_history(user, friend)
                            self.send_json(client_socket, {"status": "success", "data": history, "with_user": friend})

                        elif command == 'INIT_CALL':
                            callee = request['callee']
                            addr_info = self.db.get_user_address(callee)
                            if addr_info and callee in self.clients:
                                call_id = self.db.log_call(user, callee, "INITIATED")
                                self.send_json(client_socket, {"status": "success", "type": "CALL_INFO", "target_ip": addr_info[0], "target_port": addr_info[1], "call_id": call_id})
                                self.send_json(self.clients[callee], {"type": "INCOMING_CALL", "from": user, "caller_ip": addr[0]})
                            else:
                                self.send_json(client_socket, {"status": "error", "message": "User offline"})

        except Exception as e:
            print(f"Error with {addr}: {e}")
        finally:
            if user and user in self.clients:
                del self.clients[user]
                self.broadcast_json({"type": "STATUS_UPDATE", "username": user, "status": "Offline"})
            client_socket.close()

    def start(self):
        while True:
            client, addr = self.server_socket.accept()
            thread = threading.Thread(target=self.handle_client, args=(client, addr))
            thread.start()

if __name__ == "__main__":
    server = ChatServer()
    server.start()