import socket
import threading
import json
import time
from server_db import ChatDatabase

HOST = '0.0.0.0'
TCP_PORT = 5555

class ChatServer:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((HOST, TCP_PORT))
        self.sock.listen()
        self.db = ChatDatabase()
        self.clients = {} # username -> socket
        
        # Room State: { "group_name": ["user1", "user2"] }
        # For 1v1, name is "user1_user2" (sorted)
        self.active_rooms = {} 

        print(f"Chat Go Server running on {HOST}:{TCP_PORT}")

    def send_json(self, sock, data):
        try: sock.sendall((json.dumps(data) + "\n").encode('utf-8'))
        except: pass

    def broadcast(self, data, exclude=None):
        msg = (json.dumps(data) + "\n").encode('utf-8')
        for u, s in list(self.clients.items()):
            if u != exclude:
                try: s.sendall(msg)
                except: pass

    def handle_client(self, client, addr):
        user = None
        buf = ""
        try:
            while True:
                data = client.recv(1024*1024).decode('utf-8')
                if not data: break
                buf += data
                while "\n" in buf:
                    msg_str, buf = buf.split("\n", 1)
                    if not msg_str.strip(): continue
                    try: req = json.loads(msg_str)
                    except: continue
                    
                    cmd = req.get('command')

                    # --- Auth ---
                    if cmd == 'REGISTER':
                        res = self.db.register_user(req['username'], req['password'])
                        self.send_json(client, {"status": "success" if res else "error", "message": "Registered" if res else "Taken"})

                    elif cmd == 'LOGIN':
                        if self.db.validate_login(req['username'], req['password']):
                            user = req['username']
                            if user in self.clients: 
                                try: self.clients[user].close()
                                except: pass
                            self.clients[user] = client
                            self.send_json(client, {"status": "success", "message": f"Welcome {user}"})
                            self.broadcast({"type": "STATUS", "username": user, "status": "Online"}, exclude=user)
                        else:
                            self.send_json(client, {"status": "error", "message": "Invalid Login"})

                    # --- Authorized Ops ---
                    elif user:
                        if cmd == 'GET_FRIENDS':
                            friends = self.db.get_friends(user)
                            data = [{"name": f, "status": "Online" if f in self.clients else "Offline"} for f in friends]
                            self.send_json(client, {"status": "success", "data": data, "type": "FRIENDS"})

                        elif cmd == 'GET_GROUPS':
                            groups = self.db.get_user_groups(user)
                            self.send_json(client, {"status": "success", "data": groups, "type": "GROUPS"})

                        elif cmd == 'ADD_FRIEND':
                            res = self.db.add_friend(user, req['friend'])
                            self.send_json(client, {"status": "info", "message": res})

                        elif cmd == 'CREATE_GROUP':
                            res = self.db.create_group(req['name'], user)
                            self.send_json(client, {"status": "success" if res else "error", "message": "Group Created" if res else "Failed"})

                        elif cmd == 'ADD_MEMBER':
                            if self.db.is_member(req['group'], user):
                                res = self.db.add_group_member(req['group'], req['member'])
                                self.send_json(client, {"status": "info", "message": res})
                            else: self.send_json(client, {"status": "error", "message": "Not Authorized"})

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
                            else: self.send_json(client, {"status": "error", "message": "Not member"})

                        elif cmd == 'GET_HISTORY':
                            friend = req['of_user']
                            hist = self.db.get_chat_history(user, friend)
                            self.send_json(client, {"status": "success", "data": hist, "with_user": friend, "type": "HISTORY"})

                        # --- WebRTC Signaling ---
                        # We rely on routing via 'to' field.
                        # For groups, client sends individual signals to peers they want to connect to.
                        
                        elif cmd == 'JOIN_CALL':
                            # User joins a "Room". We notify others in that room.
                            room = req['room']
                            call_type = req['call_type']
                            
                            if room not in self.active_rooms: self.active_rooms[room] = []
                            if user not in self.active_rooms[room]: self.active_rooms[room].append(user)
                            
                            # Notify others in room that a new peer joined
                            for peer in self.active_rooms[room]:
                                if peer != user and peer in self.clients:
                                    # Tell existing peer about new user
                                    self.send_json(self.clients[peer], {
                                        "type": "PEER_JOINED", "peer": user, "room": room
                                    })
                                    # Tell new user about existing peer
                                    self.send_json(client, {
                                        "type": "EXISTING_PEER", "peer": peer, "room": room
                                    })

                        elif cmd == 'SIGNAL':
                            target = req['to']
                            if target in self.clients:
                                self.send_json(self.clients[target], {
                                    "type": "SIGNAL", "from": user, "signal": req['signal']
                                })

                        elif cmd == 'LEAVE_CALL':
                            room = req['room']
                            if room in self.active_rooms:
                                if user in self.active_rooms[room]: 
                                    self.active_rooms[room].remove(user)
                                # Notify others
                                for peer in self.active_rooms[room]:
                                    if peer in self.clients:
                                        self.send_json(self.clients[peer], {"type": "PEER_LEFT", "peer": user})

        except Exception as e: print(e)
        finally:
            if user:
                if user in self.clients: del self.clients[user]
                # Cleanup rooms
                for r in list(self.active_rooms.keys()):
                    if user in self.active_rooms[r]: self.active_rooms[r].remove(user)
                self.broadcast({"type": "STATUS", "username": user, "status": "Offline"})
            client.close()

    def start(self):
        while True:
            try:
                c, a = self.sock.accept()
                threading.Thread(target=self.handle_client, args=(c, a)).start()
            except: pass

if __name__ == "__main__":
    ChatServer().start()