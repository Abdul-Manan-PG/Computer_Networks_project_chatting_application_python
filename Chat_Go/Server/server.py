import socket
import threading
import json
import time
from chat_db import ChatDatabase

HOST = '10.75.51.26'
TCP_PORT = 5555
UDP_PORT = 5555

class ChatServer:
    def __init__(self):
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.tcp_sock.bind((HOST, TCP_PORT))
        self.tcp_sock.listen()

        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_sock.bind((HOST, UDP_PORT))

        self.db = ChatDatabase()
        self.clients = {} 
        self.udp_clients = {} 
        self.username_to_udp = {} 
        self.active_calls = {} 

        print(f"Chat Go Server running on {HOST}:{TCP_PORT} (TCP) & {UDP_PORT} (UDP)")

    def broadcast(self, data, exclude_user=None):
        msg = (json.dumps(data) + "\n").encode('utf-8')
        for u, sock in list(self.clients.items()):
            if u != exclude_user:
                try: sock.sendall(msg)
                except: pass

    def send_json(self, sock, data):
        try: sock.sendall((json.dumps(data) + "\n").encode('utf-8'))
        except: pass

    def udp_listener(self):
        while True:
            try:
                data, addr = self.udp_sock.recvfrom(60000) 
                try:
                    room_len = data[0]
                    room_name = data[1:1+room_len].decode('utf-8')
                    sender_user = self.udp_clients.get(addr)
                    
                    if room_name in self.active_calls:
                        members = self.active_calls[room_name]
                        for member in members:
                            if member != sender_user:
                                target_addr = self.username_to_udp.get(member)
                                if target_addr:
                                    self.udp_sock.sendto(data, target_addr)
                except: pass 
            except: pass

    def handle_client(self, client, addr):
        print(f"New connection from {addr}")
        user = None
        buffer = ""
        try:
            while True:
                try:
                    data = client.recv(1024*1024).decode('utf-8')
                except UnicodeDecodeError: continue
                
                if not data: break
                buffer += data
                
                while "\n" in buffer:
                    msg_str, buffer = buffer.split("\n", 1)
                    if not msg_str.strip(): continue
                    try: req = json.loads(msg_str)
                    except: continue
                    
                    cmd = req.get('command')

                    if cmd == 'REGISTER':
                        res = self.db.register_user(req['username'], req['password'])
                        self.send_json(client, {"status": "success" if res else "error", "message": "Registered" if res else "Taken"})

                    elif cmd == 'LOGIN':
                        if self.db.validate_login(req['username'], req['password']):
                            user = req['username']
                            udp_port = req.get('udp_port')
                            if udp_port:
                                self.udp_clients[(addr[0], udp_port)] = user
                                self.username_to_udp[user] = (addr[0], udp_port)
                            self.clients[user] = client
                            self.send_json(client, {"status": "success", "message": f"Welcome {user}"})
                            self.broadcast({"type": "STATUS", "username": user, "status": "Online"}, exclude_user=user)
                        else:
                            self.send_json(client, {"status": "error", "message": "Invalid Login"})

                    elif user:
                        if cmd == 'LOGOUT': break

                        elif cmd == 'GET_FRIENDS':
                            friends = self.db.get_friends(user)
                            data = [{"name": f, "status": "Online" if f in self.clients else "Offline"} for f in friends]
                            self.send_json(client, {"status": "success", "data": data, "type": "FRIENDS"})

                        elif cmd == 'GET_JOINED_GROUPS':
                            groups = self.db.get_joined_groups(user)
                            self.send_json(client, {"status": "success", "data": groups, "type": "JOINED_GROUPS"})

                        elif cmd == 'GET_AVAILABLE_GROUPS':
                            groups = self.db.get_available_groups(user)
                            self.send_json(client, {"status": "success", "data": groups, "type": "AVAILABLE_GROUPS"})

                        elif cmd == 'ADD_FRIEND':
                            res = self.db.add_friend(user, req['friend'])
                            self.send_json(client, {"status": "info", "message": res})

                        elif cmd == 'CREATE_GROUP':
                            res = self.db.create_group(req['name'], req['password'], user)
                            self.send_json(client, {"status": "success" if res else "error", "message": "Group Created" if res else "Name taken"})

                        elif cmd == 'JOIN_GROUP':
                            res = self.db.join_group(req['group'], user, req['password'])
                            if res == "Success":
                                self.send_json(client, {"status": "success", "message": f"Joined {req['group']}"})
                            else:
                                self.send_json(client, {"status": "error", "message": res})

                        elif cmd == 'SEND_MSG':
                            to = req['to']
                            if to in self.clients:
                                self.send_json(self.clients[to], {
                                    "type": "MESSAGE", "from": user, "content": req['msg'], 
                                    "is_file": req.get('is_file', False), "filename": req.get('filename'), "time": time.ctime()
                                })
                            self.db.save_message(user, to, req['msg'], req.get('is_file', False))

                        elif cmd == 'SEND_GROUP_MSG':
                            group = req['to']
                            if self.db.is_member(group, user):
                                members = self.db.get_group_members(group)
                                for m in members:
                                    if m != user and m in self.clients:
                                        self.send_json(self.clients[m], {
                                            "type": "MESSAGE", "from": user, "group": group, "content": req['msg'],
                                            "is_file": req.get('is_file', False), "filename": req.get('filename'), "time": time.ctime()
                                        })
                            else:
                                self.send_json(client, {"status": "error", "message": "Not a member"})

                        elif cmd == 'GET_HISTORY':
                            friend = req['of_user']
                            hist = self.db.get_chat_history(user, friend)
                            self.send_json(client, {"status": "success", "data": hist, "with_user": friend, "type": "HISTORY"})

                        # --- Call Signaling ---
                        elif cmd == 'START_CALL':
                            target = req['target']
                            is_group = req.get('is_group', False)
                            call_type = req['call_type']
                            room_id = f"{target}_{int(time.time())}" if is_group else f"{min(user, target)}_{max(user, target)}"
                            
                            members = []
                            if is_group:
                                if self.db.is_member(target, user): members = self.db.get_group_members(target)
                            else: members = [user, target]

                            if members:
                                self.active_calls[room_id] = members
                                for m in members:
                                    if m != user and m in self.clients:
                                        self.send_json(self.clients[m], {
                                            "type": "INCOMING_CALL", "from": user, "room": room_id, 
                                            "call_type": call_type, "is_group": is_group, "group_name": target
                                        })
                                self.send_json(client, {"type": "CALL_STARTED", "room": room_id})

                        elif cmd == 'END_CALL':
                            room = req['room']
                            if room in self.active_calls:
                                members = self.active_calls[room]
                                for m in members:
                                    if m in self.clients:
                                        self.send_json(self.clients[m], {"type": "CALL_ENDED", "room": room})
                                del self.active_calls[room]

        except Exception as e: print(f"Client Error: {e}")
        finally:
            if user:
                if user in self.clients: del self.clients[user]
                if user in self.username_to_udp: del self.username_to_udp[user]
                
                # CLEANUP: Remove user from active call lists to prevent sending UDP to closed socket
                for r in list(self.active_calls.keys()):
                    if user in self.active_calls[r]: 
                        self.active_calls[r].remove(user)
                        
                self.broadcast({"type": "STATUS", "username": user, "status": "Offline"})
            client.close()

    def start(self):
        threading.Thread(target=self.udp_listener, daemon=True).start()
        print("Waiting for TCP connections...")
        while True:
            try:
                client, addr = self.tcp_sock.accept()
                threading.Thread(target=self.handle_client, args=(client, addr)).start()
            except: pass

if __name__ == "__main__":
    ChatServer().start()