import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext, simpledialog
import socket, threading, json, time, os, base64
import cv2, pyaudio, pickle, struct
from PIL import Image, ImageTk
from client_db import ClientDatabase

# --- Config ---
SERVER_IP = "127.0.0.1"
TCP_PORT = 5555
UDP_PORT = 5555
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

if not os.path.exists("downloads"): os.makedirs("downloads")

class ChatGo:
    def __init__(self, root):
        self.root = root
        self.root.title("Chat Go")
        self.root.geometry("1100x750")
        self.root.configure(bg="#ffffff")

        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(('0.0.0.0', 0))
        self.my_udp_port = self.udp.getsockname()[1]

        self.db = ClientDatabase()
        self.username = None
        self.connected = False
        self.current_chat = None 
        self.is_group = False
        self.msg_queue = []
        
        # Call State
        self.in_call = False
        self.call_room = None
        self.audio_stream = None
        self.cap = None
        self.p = pyaudio.PyAudio()

        self.style_setup()
        self.login_ui()
        
        self.root.after(100, self.process_queue)

    def style_setup(self):
        style = ttk.Style()
        style.theme_use('clam')
        # Colors
        self.bg_color = "#ffffff"
        self.sidebar_color = "#f0f2f5"
        self.primary_color = "#0084ff"
        self.text_color = "#050505"
        
        style.configure("TFrame", background=self.bg_color)
        style.configure("Sidebar.TFrame", background=self.sidebar_color)
        
        style.configure("TButton", font=("Segoe UI", 10, "bold"), background=self.primary_color, foreground="white", borderwidth=0)
        style.map("TButton", background=[('active', '#0073e6')])
        
        style.configure("Header.TLabel", font=("Segoe UI", 20, "bold"), background=self.sidebar_color, foreground=self.primary_color)

    # --- Networking ---
    def connect_server(self):
        try:
            self.tcp.connect((SERVER_IP, TCP_PORT))
            self.connected = True
            threading.Thread(target=self.listen_tcp, daemon=True).start()
            threading.Thread(target=self.listen_udp, daemon=True).start()
            return True
        except: return False

    def send(self, data):
        try: self.tcp.sendall((json.dumps(data)+"\n").encode('utf-8'))
        except: pass

    def listen_tcp(self):
        buf = ""
        while self.connected:
            try:
                data = self.tcp.recv(4096).decode('utf-8')
                if not data: break
                buf += data
                while "\n" in buf:
                    msg, buf = buf.split("\n", 1)
                    if msg: self.msg_queue.append(json.loads(msg))
            except: break

    def listen_udp(self):
        while self.connected:
            try:
                data, _ = self.udp.recvfrom(60000)
                if self.in_call:
                    room_len = data[0]
                    room = data[1:1+room_len].decode('utf-8')
                    if room != self.call_room: continue

                    type_flag = chr(data[1+room_len]) # 'v' or 'a'
                    payload = data[1+room_len+1:]

                    if type_flag == 'a':
                        if self.audio_out: self.audio_out.write(payload)
                    elif type_flag == 'v':
                        try:
                            frame_data = pickle.loads(payload)
                            img = cv2.imdecode(frame_data, cv2.IMREAD_COLOR)
                            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                            img = Image.fromarray(img)
                            imgtk = ImageTk.PhotoImage(image=img)
                            if self.remote_video_lbl:
                                self.remote_video_lbl.config(image=imgtk)
                                self.remote_video_lbl.image = imgtk
                        except: pass
            except: pass

    # --- UI Logic ---
    def process_queue(self):
        while self.msg_queue:
            self.handle_msg(self.msg_queue.pop(0))
        self.root.after(50, self.process_queue)

    def handle_msg(self, msg):
        t = msg.get('type')
        if 'status' in msg and not t: 
            if msg['status'] == 'success' and "Welcome" in msg.get('message',''):
                self.dashboard_ui()
                # Delay fetching slightly to ensure UI is ready
                self.root.after(100, lambda: self.send({"command": "GET_FRIENDS"}))
                self.root.after(200, lambda: self.send({"command": "GET_GROUPS"}))
            elif msg['status'] == 'error': messagebox.showerror("Error", msg['message'])
            elif "Group Created" in msg.get('message', ''): 
                self.send({"command": "GET_GROUPS"})
        
        elif t in ['FRIENDS', 'GROUPS']:
            self.update_sidebar(msg['data'], msg['type'])
        
        elif t == 'MESSAGE':
            ctx = msg.get('group') if msg.get('group') else msg['from']
            is_g = True if msg.get('group') else False
            self.db.save_msg(ctx, msg['from'], msg['content'], msg['is_file'], msg['time'], is_g)
            if self.current_chat == ctx:
                self.render_msg(msg['from'], msg['content'], msg['is_file'], msg['time'])

        elif t == 'INCOMING_CALL':
            res = messagebox.askyesno("Incoming Call", f"{msg['from']} is calling you in {msg.get('group_name', 'Private')}...")
            if res: self.start_call_ui(msg['room'], msg['call_type'])

        elif t == 'CALL_STARTED':
            self.start_call_ui(msg['room'], self.pending_call_type)

        elif t == 'CALL_ENDED':
            self.end_call_logic()

    # --- Screens ---
    def clear(self):
        for w in self.root.winfo_children(): w.destroy()

    def login_ui(self):
        self.clear()
        f = tk.Frame(self.root, bg="white", padx=40, pady=40)
        f.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        tk.Label(f, text="Chat Go", font=("Segoe UI", 28, "bold"), fg="#0084ff", bg="white").pack(pady=20)
        
        self.e_user = ttk.Entry(f, width=30, font=("Segoe UI", 12))
        self.e_user.pack(pady=5)
        self.e_user.insert(0, "Username")
        
        self.e_pass = ttk.Entry(f, width=30, font=("Segoe UI", 12), show="*")
        self.e_pass.pack(pady=5)
        self.e_pass.insert(0, "Password")

        ttk.Button(f, text="Login", command=lambda: self.auth("LOGIN")).pack(fill=tk.X, pady=10)
        ttk.Button(f, text="Register", command=lambda: self.auth("REGISTER")).pack(fill=tk.X, pady=0)

    def auth(self, cmd):
        if not self.connected: 
            if not self.connect_server(): 
                messagebox.showerror("Error", "Server Offline")
                return
        self.username = self.e_user.get()
        self.send({"command": cmd, "username": self.username, "password": self.e_pass.get(), "udp_port": self.my_udp_port})

    def dashboard_ui(self):
        self.clear()
        # Sidebar
        self.sidebar = ttk.Frame(self.root, style="Sidebar.TFrame", width=280)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)
        
        # Header
        h = tk.Frame(self.sidebar, bg="#f0f2f5", height=80)
        h.pack(fill=tk.X)
        ttk.Label(h, text="Chat Go", style="Header.TLabel").pack(side=tk.LEFT, padx=20, pady=20)
        
        # Refresh Button (FIXED)
        tk.Button(h, text="⟳", command=self.refresh_data, bd=0, bg="#f0f2f5", fg="#0084ff", font=("Segoe UI", 16, "bold")).pack(side=tk.RIGHT, padx=15)
        
        # Action Buttons
        act_fr = tk.Frame(self.sidebar, bg="#f0f2f5")
        act_fr.pack(fill=tk.X, padx=10)
        
        b_grp = tk.Button(act_fr, text="+ Group", command=self.create_group, bg="white", bd=0, fg="#0084ff", font=("Segoe UI", 10, "bold"))
        b_grp.pack(side=tk.RIGHT, padx=5, ipadx=5, ipady=2)
        b_frd = tk.Button(act_fr, text="+ Friend", command=self.add_friend, bg="white", bd=0, fg="#0084ff", font=("Segoe UI", 10, "bold"))
        b_frd.pack(side=tk.RIGHT, padx=5, ipadx=5, ipady=2)

        # Lists Container (FIXED: Re-initializing structure)
        self.list_frame = tk.Frame(self.sidebar, bg="#f0f2f5")
        self.list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # Create fixed labels and containers for Groups/Friends to avoid 'missing widget' errors
        tk.Label(self.list_frame, text="GROUPS", bg="#f0f2f5", fg="gray", font=("Segoe UI", 9, "bold"), anchor="w").pack(fill=tk.X, padx=15, pady=(5,2))
        self.gr_list_w = tk.Frame(self.list_frame, bg="#f0f2f5")
        self.gr_list_w.pack(fill=tk.X)
        
        tk.Label(self.list_frame, text="FRIENDS", bg="#f0f2f5", fg="gray", font=("Segoe UI", 9, "bold"), anchor="w").pack(fill=tk.X, padx=15, pady=(10,2))
        self.fr_list_w = tk.Frame(self.list_frame, bg="#f0f2f5")
        self.fr_list_w.pack(fill=tk.X)

        tk.Button(self.sidebar, text="Logout", bg="#ff4d4d", fg="white", bd=0, font=("Segoe UI", 10, "bold"), command=self.logout).pack(fill=tk.X, side=tk.BOTTOM)

        # Main Chat Area
        self.main = tk.Frame(self.root, bg="white")
        self.main.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Top Bar
        self.head_fr = tk.Frame(self.main, bg="white", height=60, bd=1, relief="solid")
        self.head_fr.pack(fill=tk.X)
        self.head_lbl = tk.Label(self.head_fr, text="", font=("Segoe UI", 14, "bold"), bg="white", padx=20)
        self.head_lbl.pack(side=tk.LEFT, pady=15)
        
        # Chat Actions
        self.act_box = tk.Frame(self.head_fr, bg="white")
        self.act_box.pack(side=tk.RIGHT, padx=20)
        
        self.b_add = tk.Button(self.act_box, text="Add Member", command=self.add_member, bd=0, bg="#f0f2f5")
        self.b_call = tk.Button(self.act_box, text="📞", command=lambda: self.init_call('audio'), bd=0, bg="white", font=("Segoe UI", 14))
        self.b_vid = tk.Button(self.act_box, text="🎥", command=lambda: self.init_call('video'), bd=0, bg="white", font=("Segoe UI", 14))

        # Messages Area
        self.txt_area = scrolledtext.ScrolledText(self.main, bg="white", font=("Segoe UI", 11), bd=0, state='disabled', padx=20, pady=20)
        self.txt_area.pack(fill=tk.BOTH, expand=True)
        
        self.txt_area.tag_config("me", justify='right', background="#0084ff", foreground="white", lmargin1=200, rmargin=10, spacing1=5, spacing3=5)
        self.txt_area.tag_config("other", justify='left', background="#e4e6eb", foreground="black", rmargin=200, lmargin1=10, spacing1=5, spacing3=5)
        self.txt_area.tag_config("meta", font=("Segoe UI", 8), foreground="#65676b")
        self.txt_area.tag_config("name", font=("Segoe UI", 9, "bold"), foreground="#65676b")

        # Input
        inp_fr = tk.Frame(self.main, bg="white", height=60)
        inp_fr.pack(fill=tk.X, padx=20, pady=10)
        
        tk.Button(inp_fr, text="📎", command=self.send_file, bd=0, bg="white", font=("Segoe UI", 16)).pack(side=tk.LEFT)
        
        self.e_msg = tk.Entry(inp_fr, font=("Segoe UI", 11), bd=0, bg="#f0f2f5", width=50)
        self.e_msg.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10, ipady=8)
        self.e_msg.bind("<Return>", lambda e: self.send_msg())
        
        tk.Button(inp_fr, text="➤", command=self.send_msg, bd=0, bg="white", fg="#0084ff", font=("Segoe UI", 16)).pack(side=tk.RIGHT)

    def refresh_data(self):
        self.send({"command": "GET_FRIENDS"})
        self.send({"command": "GET_GROUPS"})

    def update_sidebar(self, data, type_):
        # Safely check if widget exists, otherwise rebuild dashboard or return
        if not hasattr(self, 'fr_list_w') or not self.fr_list_w.winfo_exists():
            return

        target = self.fr_list_w if type_ == 'FRIENDS' else self.gr_list_w
        for w in target.winfo_children(): w.destroy()

        for item in data:
            name = item['name'] if type_ == 'FRIENDS' else item
            status = item.get('status', '') if type_ == 'FRIENDS' else ''
            color = "#31a24c" if status == 'Online' else "#bcc0c4"
            
            f = tk.Frame(target, bg="#f0f2f5", cursor="hand2")
            f.pack(fill=tk.X, pady=1, padx=10)
            
            # Icon
            tk.Label(f, text="#" if type_ == 'GROUPS' else "●", fg="black" if type_=='GROUPS' else color, bg="#f0f2f5", font=("Segoe UI", 12)).pack(side=tk.LEFT)
            tk.Label(f, text=name, bg="#f0f2f5", font=("Segoe UI", 11)).pack(side=tk.LEFT, padx=10)
            
            f.bind("<Button-1>", lambda e, n=name, g=(type_=='GROUPS'): self.open_chat(n, g))
            for child in f.winfo_children():
                child.bind("<Button-1>", lambda e, n=name, g=(type_=='GROUPS'): self.open_chat(n, g))

    def open_chat(self, name, is_group):
        self.current_chat = name
        self.is_group = is_group
        self.head_lbl.config(text=name)
        
        if is_group: self.b_add.pack(side=tk.LEFT, padx=5)
        else: self.b_add.pack_forget()
        self.b_call.pack(side=tk.LEFT, padx=5)
        self.b_vid.pack(side=tk.LEFT, padx=5)

        self.txt_area.config(state='normal')
        self.txt_area.delete(1.0, tk.END)
        self.txt_area.config(state='disabled')
        
        hist = self.db.get_history(name)
        for sender, content, is_file, t in hist:
            self.render_msg(sender, content, is_file, t)

    def render_msg(self, sender, content, is_file, time):
        self.txt_area.config(state='normal')
        tag = "me" if sender == self.username else "other"
        
        if self.is_group and tag == "other":
            self.txt_area.insert(tk.END, f"\n{sender}", "name")
        
        msg_text = f" 📄 {content} " if is_file else f" {content} "
        self.txt_area.insert(tk.END, f"\n{msg_text}\n", tag)
        self.txt_area.insert(tk.END, f"{time}\n", "meta")
            
        self.txt_area.see(tk.END)
        self.txt_area.config(state='disabled')

    def send_msg(self):
        txt = self.e_msg.get()
        if not txt or not self.current_chat: return
        
        cmd = "SEND_GROUP_MSG" if self.is_group else "SEND_MSG"
        self.send({"command": cmd, "to": self.current_chat, "msg": txt})
        
        self.db.save_msg(self.current_chat, self.username, txt, False, time.ctime(), self.is_group)
        self.render_msg(self.username, txt, False, time.ctime())
        self.e_msg.delete(0, tk.END)

    def send_file(self):
        if not self.current_chat: return
        path = filedialog.askopenfilename()
        if not path: return
        fname = os.path.basename(path)
        with open(path, "rb") as f: enc = base64.b64encode(f.read()).decode('utf-8')
        
        cmd = "SEND_GROUP_MSG" if self.is_group else "SEND_MSG"
        self.send({"command": cmd, "to": self.current_chat, "msg": enc, "is_file": True, "filename": fname})
        
        self.db.save_msg(self.current_chat, self.username, fname, True, time.ctime(), self.is_group)
        self.render_msg(self.username, fname, True, time.ctime())

    def init_call(self, type_):
        if not self.current_chat: return
        self.pending_call_type = type_
        self.send({"command": "START_CALL", "target": self.current_chat, "is_group": self.is_group, "call_type": type_})

    def start_call_ui(self, room, type_):
        self.in_call = True
        self.call_room = room
        
        self.win_call = tk.Toplevel(self.root)
        self.win_call.title(f"{type_.upper()} Call")
        self.win_call.geometry("600x500")
        self.win_call.configure(bg="black")
        
        self.remote_video_lbl = tk.Label(self.win_call, text="Connecting...", bg="black", fg="white")
        self.remote_video_lbl.pack(fill=tk.BOTH, expand=True)
        
        tk.Button(self.win_call, text="End Call", bg="red", fg="white", command=self.end_call_action).pack(pady=10)

        self.audio_stream = self.p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
        self.audio_out = self.p.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True)
        
        if type_ == 'video':
            self.cap = cv2.VideoCapture(0)
            threading.Thread(target=self.video_stream_out, daemon=True).start()
        
        threading.Thread(target=self.audio_stream_out, daemon=True).start()

    def video_stream_out(self):
        while self.in_call and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                frame = cv2.resize(frame, (320, 240))
                _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
                data = pickle.dumps(buffer)
                
                room_b = self.call_room.encode('utf-8')
                header = bytes([len(room_b)]) + room_b + b'v'
                try: self.udp.sendto(header + data, (SERVER_IP, UDP_PORT))
                except: pass
            time.sleep(0.05)

    def audio_stream_out(self):
        while self.in_call:
            try:
                data = self.audio_stream.read(CHUNK)
                room_b = self.call_room.encode('utf-8')
                header = bytes([len(room_b)]) + room_b + b'a'
                self.udp.sendto(header + data, (SERVER_IP, UDP_PORT))
            except: pass

    def end_call_action(self):
        self.send({"command": "END_CALL", "room": self.call_room})
        self.end_call_logic()

    def end_call_logic(self):
        self.in_call = False
        if hasattr(self, 'win_call'): self.win_call.destroy()
        if self.cap: self.cap.release()
        if self.audio_stream: self.audio_stream.stop_stream(); self.audio_stream.close()
        if self.audio_out: self.audio_out.stop_stream(); self.audio_out.close()

    # --- Helpers ---
    def add_friend(self):
        n = simpledialog.askstring("Add Friend", "Username:")
        if n: self.send({"command": "ADD_FRIEND", "friend": n})

    def create_group(self):
        n = simpledialog.askstring("Create Group", "Group Name:")
        if n: self.send({"command": "CREATE_GROUP", "name": n})

    def add_member(self):
        n = simpledialog.askstring("Add Member", "Username:")
        if n: self.send({"command": "ADD_MEMBER", "group": self.current_chat, "member": n})

    def logout(self):
        self.send({"command": "LOGOUT"})
        self.connected = False
        self.login_ui()

if __name__ == "__main__":
    root = tk.Tk()
    app = ChatGo(root)
    root.mainloop()