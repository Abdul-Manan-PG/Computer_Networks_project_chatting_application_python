import socket
import threading
import json
import time
from chat_db import ChatDatabase

HOST = '0.0.0.0'
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
        self.clients = {} # username -> tcp_socket
        self.udp_clients = {} # (ip, port) -> username
        self.username_to_udp = {} # username -> (ip, port)
        self.active_calls = {} # room_id -> [members]

        print(f"Chat Go Server running on {HOST}:{TCP_PORT}")

    def broadcast(self, data, exclude_user=None):
        msg = (json.dumps(data) + "\n").encode('utf-8')
        for u, sock in list(self.clients.items()):
            if u != exclude_user:
                try: sock.sendall(msg)
                except: pass

    def send_json(self, sock, data):
        try: sock.sendall((json.dumps(data) + "\n").encode('utf-8'))
        except: pass

    # --- UDP Relay for Group Calls ---
    def udp_listener(self):
        while True:
            try:
                data, addr = self.udp_sock.recvfrom(60000)
                # Packet: [ROOM_LEN (1 byte)][ROOM_STRING][PAYLOAD]
                try:
                    room_len = data[0]
                    room_name = data[1:1+room_len].decode('utf-8')
                    sender = self.udp_clients.get(addr)
                    
                    if room_name in self.active_calls:
                        for member in self.active_calls[room_name]:
                            if member != sender:
                                target = self.username_to_udp.get(member)
                                if target: self.udp_sock.sendto(data, target)
                except: pass
            except: pass

    def handle_client(self, client, addr):
        user = None
        buffer = ""
        try:
            while True:
                data = client.recv(4096).decode('utf-8')
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
                            # Verify user is in group before adding others
                            if self.db.is_member(req['group'], user):
                                res = self.db.add_group_member(req['group'], req['member'])
                                self.send_json(client, {"status": "info", "message": res})
                            else:
                                self.send_json(client, {"status": "error", "message": "Not authorized"})

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
                            # Only allow if member
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

                        # --- Call Signaling ---
                        elif cmd == 'START_CALL':
                            target = req['target']
                            is_group = req.get('is_group', False)
                            call_type = req['call_type']
                            room_id = f"{target}_{int(time.time())}" if is_group else f"{min(user, target)}_{max(user, target)}"
                            
                            members = []
                            if is_group:
                                if self.db.is_member(target, user):
                                    members = self.db.get_group_members(target)
                            else:
                                members = [user, target]

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
                                for m in self.active_calls[room]:
                                    if m in self.clients:
                                        self.send_json(self.clients[m], {"type": "CALL_ENDED", "room": room})
                                del self.active_calls[room]

        except Exception as e: print(e)
        finally:
            if user:
                if user in self.clients: del self.clients[user]
                if user in self.username_to_udp: del self.username_to_udp[user]
                self.broadcast({"type": "STATUS", "username": user, "status": "Offline"})
            client.close()

    def start(self):
        threading.Thread(target=self.udp_listener, daemon=True).start()
        while True:
            try:
                client, addr = self.tcp_sock.accept()
                threading.Thread(target=self.handle_client, args=(client, addr)).start()
            except: pass

if __name__ == "__main__":
    ChatServer().start()