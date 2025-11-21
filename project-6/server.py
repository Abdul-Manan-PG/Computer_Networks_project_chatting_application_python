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
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((HOST, TCP_PORT))
        self.server_socket.listen()
        self.db = ChatDatabase()
        self.clients = {} 
        print(f"Server started on {HOST}:{TCP_PORT}")

    def send_json(self, sock, data):
        try:
            msg = json.dumps(data) + "\n"
            sock.sendall(msg.encode('utf-8'))
        except Exception as e:
            print(f"Send error: {e}")

    def broadcast_json(self, data, exclude_user=None):
        msg = json.dumps(data) + "\n"
        encoded_msg = msg.encode('utf-8')
        for user, client_sock in list(self.clients.items()):
            if user != exclude_user:
                try: client_sock.sendall(encoded_msg)
                except: pass

    def handle_client(self, client_socket, addr):
        print(f"New connection from {addr}")
        user = None
        buffer = ""
        
        try:
            while True:
                try:
                    data = client_socket.recv(1024*1024).decode('utf-8')
                except UnicodeDecodeError: continue
                
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
                            if user in self.clients:
                                try: self.clients[user].close()
                                except: pass
                            self.db.update_user_address(user, addr[0], request.get('udp_port', 0))
                            self.clients[user] = client_socket
                            self.send_json(client_socket, {"status": "success", "message": f"Welcome {user}!"})
                            time.sleep(0.1)
                            self.broadcast_json({"type": "STATUS_UPDATE", "username": user, "status": "Online"}, exclude_user=user)
                        else:
                            self.send_json(client_socket, {"status": "error", "message": "Invalid credentials"})

                    elif user:
                        if command == 'LOGOUT':
                            if user in self.clients: del self.clients[user]
                            self.broadcast_json({"type": "STATUS_UPDATE", "username": user, "status": "Offline"})
                            self.send_json(client_socket, {"status": "success"})
                            return 

                        # --- One-to-One Chat ---
                        elif command == 'SEND_MSG':
                            recipient = request['to']
                            if recipient in self.clients:
                                msg_content = request['message']
                                msg_type = request.get('msg_type', 'text')
                                filename = request.get('filename', '')
                                
                                db_content = filename if msg_type != 'text' else msg_content
                                self.db.save_message(user, recipient, db_content)
                                
                                self.send_json(self.clients[recipient], {
                                    "type": "MESSAGE",
                                    "from": user,
                                    "content": msg_content,
                                    "msg_type": msg_type,
                                    "filename": filename,
                                    "timestamp": time.ctime(),
                                    "is_group": False
                                })
                                self.send_json(client_socket, {"status": "success", "message": "Sent"})
                            else:
                                self.send_json(client_socket, {"status": "error", "message": "User Offline"})

                        # --- Group Chat Logic ---
                        elif command == 'CREATE_GROUP':
                            success = self.db.create_group(request['group_name'], user)
                            if success:
                                self.send_json(client_socket, {"status": "success", "message": "Group created"})
                            else:
                                self.send_json(client_socket, {"status": "error", "message": "Group name taken"})

                        elif command == 'ADD_TO_GROUP':
                            res = self.db.add_group_member(request['group_name'], request['member'])
                            self.send_json(client_socket, {"status": "info", "message": res})

                        elif command == 'GET_GROUPS':
                            groups = self.db.get_user_groups(user)
                            self.send_json(client_socket, {"status": "success", "data": groups, "is_group_list": True})

                        elif command == 'SEND_GROUP_MSG':
                            group_name = request['to']
                            members = self.db.get_group_members(group_name)
                            
                            msg_content = request['message']
                            msg_type = request.get('msg_type', 'text')
                            filename = request.get('filename', '')
                            
                            # Broadcast to all members except sender
                            for member in members:
                                if member != user and member in self.clients:
                                    self.send_json(self.clients[member], {
                                        "type": "MESSAGE",
                                        "from": user, # Sender
                                        "to_group": group_name, # Group context
                                        "content": msg_content,
                                        "msg_type": msg_type,
                                        "filename": filename,
                                        "timestamp": time.ctime(),
                                        "is_group": True
                                    })
                            self.send_json(client_socket, {"status": "success", "message": "Group msg sent"})

                        # --- Friend Logic ---
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

                        # --- WebRTC Signaling ---
                        elif command == 'INIT_CALL':
                            callee = request['callee']
                            call_type = request.get('call_type', 'voice')
                            if callee in self.clients:
                                self.send_json(self.clients[callee], {
                                    "type": "INCOMING_CALL", 
                                    "from": user, 
                                    "call_type": call_type
                                })
                            else:
                                self.send_json(client_socket, {"status": "error", "message": "User offline"})

                        elif command == 'WEBRTC_SIGNAL':
                            to_user = request['to']
                            if to_user in self.clients:
                                self.send_json(self.clients[to_user], {
                                    "type": "WEBRTC_SIGNAL",
                                    "from": user,
                                    "signal_data": request['signal_data']
                                })

                        elif command == 'END_CALL':
                            other_party = request['other_party']
                            if other_party in self.clients:
                                self.send_json(self.clients[other_party], {
                                    "type": "CALL_ENDED", 
                                    "from": user
                                })

        except Exception as e:
            print(f"Error with {addr}: {e}")
        finally:
            if user and user in self.clients:
                del self.clients[user]
                self.broadcast_json({"type": "STATUS_UPDATE", "username": user, "status": "Offline"})
            client_socket.close()

    def start(self):
        while True:
            try:
                client, addr = self.server_socket.accept()
                thread = threading.Thread(target=self.handle_client, args=(client, addr))
                thread.start()
            except Exception as e:
                print(f"Accept Error: {e}")

if __name__ == "__main__":
    server = ChatServer()
    server.start()