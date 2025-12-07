import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext, simpledialog
import socket, threading, json, time, os, base64
import cv2, pyaudio, pickle, struct, wave
import platform, subprocess
from PIL import Image, ImageTk
from client_db import ClientDatabase

# --- Configuration ---
SERVER_IP = "127.0.0.1"
TCP_PORT = 5555
UDP_PORT = 5555
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

# Ensure download directory exists for file sharing
if not os.path.exists("downloads"): os.makedirs("downloads")

class SimpleEncryptor:
    """
    Advanced Feature: Basic Encryption
    Uses a simple XOR cipher to obscure message content over the network.
    """
    KEY = "ChatGoSecureKey"

    @staticmethod
    def transform(text):
        if not text: return ""
        return ''.join(chr(ord(c) ^ ord(SimpleEncryptor.KEY[i % len(SimpleEncryptor.KEY)])) for i, c in enumerate(text))

class ChatGo:
    def __init__(self, root):
        self.root = root
        self.root.title("Chat Go - HD")
        self.root.geometry("1280x720") # HD Resolution
        self.root.configure(bg="#ffffff")

        # --- Networking Setup ---
        self.tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(('0.0.0.0', 0))
        self.my_udp_port = self.udp.getsockname()[1]

        # --- State Management ---
        self.db = ClientDatabase()
        self.username = None
        self.connected = False
        self.current_chat = None 
        self.is_group = False
        self.msg_queue = []
        
        # --- Call & Audio State ---
        self.in_call = False
        self.call_room = None
        self.audio_stream = None
        self.cap = None
        self.p = pyaudio.PyAudio()
        
        # Voice Note Recording State
        self.is_recording = False
        self.audio_frames = []

        # --- Initialization ---
        self.style_setup()
        self.login_ui()
        
        # Start UI Polling Loop
        self.root.after(100, self.process_queue)

    def style_setup(self):
        style = ttk.Style()
        style.theme_use('clam')
        self.bg_color = "#ffffff"
        self.sidebar_color = "#f0f2f5"
        self.primary_color = "#0084ff"
        
        style.configure("TFrame", background=self.bg_color)
        style.configure("Sidebar.TFrame", background=self.sidebar_color)
        style.configure("TButton", font=("Segoe UI", 12, "bold"), background=self.primary_color, foreground="white", borderwidth=0)
        style.map("TButton", background=[('active', '#0073e6')])
        style.configure("Header.TLabel", font=("Segoe UI", 24, "bold"), background=self.sidebar_color, foreground=self.primary_color)

    # ==========================
    # NETWORKING LOGIC
    # ==========================

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
        buf = b""
        while self.connected:
            try:
                chunk = self.tcp.recv(4096 * 4) 
                if not chunk: break
                buf += chunk
                while b"\n" in buf:
                    msg_bytes, buf = buf.split(b"\n", 1)
                    try:
                        msg_str = msg_bytes.decode('utf-8')
                        if msg_str.strip():
                            self.msg_queue.append(json.loads(msg_str))
                    except: pass
            except: break

    def listen_udp(self):
        while self.connected:
            try:
                data, _ = self.udp.recvfrom(60000) 
                if self.in_call:
                    self.handle_udp_packet(data)
            except: pass

    def handle_udp_packet(self, data):
        if not self.call_connected:
            self.call_connected = True
            if hasattr(self, 'remote_video_lbl'):
                self.remote_video_lbl.after(0, lambda: self.remote_video_lbl.configure(text="Connected", fg="#2ecc71"))

        try:
            room_len = data[0]
            room = data[1:1+room_len].decode('utf-8')
            if room != self.call_room: return

            type_flag = chr(data[1+room_len]) 
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

    # ==========================
    # UI EVENT LOOP
    # ==========================

    def process_queue(self):
        while self.msg_queue:
            self.handle_msg(self.msg_queue.pop(0))
        self.root.after(50, self.process_queue)

    def handle_msg(self, msg):
        t = msg.get('type')
        if 'status' in msg and not t: 
            if msg['status'] == 'success':
                if "Welcome" in msg.get('message',''):
                    self.dashboard_ui()
                    self.root.after(100, self.refresh_data)
                elif "Group Created" in msg.get('message', '') or "Joined" in msg.get('message', ''):
                    self.refresh_data()
            elif msg['status'] == 'error': messagebox.showerror("Error", msg['message'])
        
        elif t in ['FRIENDS', 'JOINED_GROUPS', 'AVAILABLE_GROUPS']:
            self.update_sidebar(msg['data'], t)
        
        elif t == 'MESSAGE':
            if msg['from'] == self.username: return 

            ctx = msg.get('group') if msg.get('group') else msg['from']
            is_g = True if msg.get('group') else False
            
            content = msg['content']
            if not msg.get('is_file', False):
                content = SimpleEncryptor.transform(content)

            is_file = msg.get('is_file', False)
            filename = msg.get('filename', '')

            if is_file:
                content = self.save_received_file(content, filename)

            self.db.save_msg(ctx, msg['from'], content, is_file, msg['time'], is_g)
            if self.current_chat == ctx:
                self.render_msg(msg['from'], content, is_file, msg['time'])

        elif t == 'INCOMING_CALL':
            res = messagebox.askyesno("Incoming Call", f"{msg['from']} is calling you...")
            if res: self.start_call_ui(msg['room'], msg['call_type'])

        elif t == 'CALL_STARTED':
            self.start_call_ui(msg['room'], self.pending_call_type)

        elif t == 'CALL_ENDED':
            self.end_call_logic()

    def save_received_file(self, content_b64, filename):
        try:
            file_data = base64.b64decode(content_b64)
            filepath = os.path.join("downloads", filename)
            if os.path.exists(filepath):
                name, ext = os.path.splitext(filename)
                filename = f"{name}_{int(time.time())}{ext}"
                filepath = os.path.join("downloads", filename)
            with open(filepath, "wb") as f: f.write(file_data)
            return filename 
        except: return "[File Error]"

    def refresh_data(self):
        self.send({"command": "GET_FRIENDS"})
        self.send({"command": "GET_JOINED_GROUPS"})
        self.send({"command": "GET_AVAILABLE_GROUPS"})

    # ==========================
    # UI SCREENS
    # ==========================

    def clear(self):
        for w in self.root.winfo_children(): w.destroy()

    def login_ui(self):
        self.clear()
        f = tk.Frame(self.root, bg="white", padx=60, pady=60)
        f.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        tk.Label(f, text="Chat Go", font=("Segoe UI", 48, "bold"), fg="#0084ff", bg="white").pack(pady=30)
        self.e_user = ttk.Entry(f, width=25, font=("Segoe UI", 16))
        self.e_user.pack(pady=10, ipady=5); self.e_user.insert(0, "Username")
        self.e_pass = ttk.Entry(f, width=25, font=("Segoe UI", 16), show="*")
        self.e_pass.pack(pady=10, ipady=5); self.e_pass.insert(0, "Password")
        ttk.Button(f, text="Login", command=lambda: self.auth("LOGIN")).pack(fill=tk.X, pady=15)
        ttk.Button(f, text="Register", command=lambda: self.auth("REGISTER")).pack(fill=tk.X, pady=5)

    def auth(self, cmd):
        if not self.connected: 
            if not self.connect_server(): 
                messagebox.showerror("Error", "Server Offline")
                return
        self.username = self.e_user.get()
        self.send({"command": cmd, "username": self.username, "password": self.e_pass.get(), "udp_port": self.my_udp_port})

    def dashboard_ui(self):
        self.clear()
        self.root.title(f"Chat Go - HD {self.username}")
        
        # --- Sidebar ---
        self.sidebar = ttk.Frame(self.root, style="Sidebar.TFrame", width=350)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)
        
        h = tk.Frame(self.sidebar, bg="#f0f2f5", height=100)
        h.pack(fill=tk.X)
        ttk.Label(h, text="Chat Go", style="Header.TLabel").pack(side=tk.LEFT, padx=30, pady=30)
        
        refresh_btn = tk.Button(h, text="⟳", command=self.refresh_data, bd=0, bg="#f0f2f5", fg="#0084ff", font=("Segoe UI", 20, "bold"))
        refresh_btn.pack(side=tk.RIGHT, padx=20)
        self.make_hoverable(refresh_btn, "#e4e6eb", "#f0f2f5")
        
        act_fr = tk.Frame(self.sidebar, bg="#f0f2f5")
        act_fr.pack(fill=tk.X, padx=15)
        b_grp = tk.Button(act_fr, text="+ Group", command=self.create_group_dialog, bg="white", bd=0, fg="#0084ff", font=("Segoe UI", 12, "bold"))
        b_grp.pack(side=tk.RIGHT, padx=10, ipadx=10, ipady=5)
        self.make_hoverable(b_grp, "#f2f2f2", "white")
        b_frd = tk.Button(act_fr, text="+ Friend", command=self.add_friend, bg="white", bd=0, fg="#0084ff", font=("Segoe UI", 12, "bold"))
        b_frd.pack(side=tk.RIGHT, padx=10, ipadx=10, ipady=5)
        self.make_hoverable(b_frd, "#f2f2f2", "white")

        self.list_frame = tk.Frame(self.sidebar, bg="#f0f2f5")
        self.list_frame.pack(fill=tk.BOTH, expand=True, pady=20)
        self.create_section("JOINED GROUPS", "joined_groups")
        self.create_section("AVAILABLE GROUPS", "avail_groups")
        self.create_section("FRIENDS", "friends")

        logout_btn = tk.Button(self.sidebar, text="Logout", bg="#ff4d4d", fg="white", bd=0, font=("Segoe UI", 12, "bold"), command=self.logout)
        logout_btn.pack(fill=tk.X, side=tk.BOTTOM)
        self.make_hoverable(logout_btn, "#cc0000", "#ff4d4d")

        # --- Main Chat (Using GRID to fix layout issues) ---
        self.main = tk.Frame(self.root, bg="white")
        self.main.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Configure Grid Rows
        self.main.grid_rowconfigure(1, weight=1) # Chat History expands
        self.main.grid_columnconfigure(0, weight=1)

        # 1. Header (Row 0)
        self.head_fr = tk.Frame(self.main, bg="white", height=80, bd=1, relief="solid")
        self.head_fr.grid(row=0, column=0, sticky="ew")
        self.head_fr.grid_propagate(False) # Force height
        
        self.head_lbl = tk.Label(self.head_fr, text="", font=("Segoe UI", 18, "bold"), bg="white", padx=30)
        self.head_lbl.pack(side=tk.LEFT, pady=20)
        
        self.act_box = tk.Frame(self.head_fr, bg="white")
        self.act_box.pack(side=tk.RIGHT, padx=30)
        self.b_call = tk.Button(self.act_box, text="📞", command=lambda: self.init_call('audio'), bd=0, bg="white", font=("Segoe UI", 20))
        self.make_hoverable(self.b_call, "#f0f2f5", "white")
        self.b_vid = tk.Button(self.act_box, text="🎥", command=lambda: self.init_call('video'), bd=0, bg="white", font=("Segoe UI", 20))
        self.make_hoverable(self.b_vid, "#f0f2f5", "white")

        # 2. History Area (Row 1 - Expands)
        self.txt_area = scrolledtext.ScrolledText(self.main, bg="white", font=("Segoe UI", 14), bd=0, state='disabled', padx=30, pady=30)
        self.txt_area.grid(row=1, column=0, sticky="nsew")
        self.config_tags()

        # 3. Input Area (Row 2 - Fixed Height at Bottom)
        inp_fr = tk.Frame(self.main, bg="white", height=90)
        inp_fr.grid(row=2, column=0, sticky="ew", padx=30, pady=20)
        inp_fr.pack_propagate(False) # Force height
        
        clip_btn = tk.Button(inp_fr, text="📎", command=self.send_file, bd=0, bg="white", font=("Segoe UI", 24))
        clip_btn.pack(side=tk.LEFT)
        self.make_hoverable(clip_btn, "#f0f2f5", "white")
        
        self.btn_mic = tk.Button(inp_fr, text="🎤", command=self.toggle_voice_note, bd=0, bg="white", font=("Segoe UI", 24))
        self.btn_mic.pack(side=tk.LEFT, padx=10)
        self.make_hoverable(self.btn_mic, "#f0f2f5", "white")
        
        self.e_msg = tk.Entry(inp_fr, font=("Segoe UI", 14), bd=0, bg="#f0f2f5", width=50)
        self.e_msg.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=20, ipady=12)
        self.e_msg.bind("<Return>", lambda e: self.send_msg())
        
        send_btn = tk.Button(inp_fr, text="➤", command=self.send_msg, bd=0, bg="white", fg="#0084ff", font=("Segoe UI", 24))
        send_btn.pack(side=tk.RIGHT)
        self.make_hoverable(send_btn, "#f0f2f5", "white")

    def config_tags(self):
        self.txt_area.tag_config("me", justify='right', background="#0084ff", foreground="white", lmargin1=100, rmargin=10, spacing1=10, spacing3=10)
        self.txt_area.tag_config("other", justify='left', background="#e4e6eb", foreground="black", rmargin=100, lmargin1=10, spacing1=10, spacing3=10)
        self.txt_area.tag_config("meta", font=("Segoe UI", 10), foreground="#65676b")
        self.txt_area.tag_config("name", font=("Segoe UI", 11, "bold"), foreground="#65676b")
        self.txt_area.tag_config("file", foreground="#0056b3", underline=1)
        self.txt_area.tag_bind("file", "<Button-1>", self.open_file_click)
        self.txt_area.tag_config("audio", foreground="#d35400", underline=1, font=("Segoe UI", 12, "bold"))
        self.txt_area.tag_bind("audio", "<Button-1>", self.play_voice_note_click)

    def create_section(self, title, tag):
        tk.Label(self.list_frame, text=title, bg="#f0f2f5", fg="gray", font=("Segoe UI", 11, "bold"), anchor="w").pack(fill=tk.X, padx=20, pady=(10,5))
        frame = tk.Frame(self.list_frame, bg="#f0f2f5")
        frame.pack(fill=tk.X)
        setattr(self, f"{tag}_w", frame)

    def make_hoverable(self, widget, hover_color, default_color):
        widget.bind("<Enter>", lambda e: widget.config(bg=hover_color))
        widget.bind("<Leave>", lambda e: widget.config(bg=default_color))

    def update_sidebar(self, data, type_):
        target = None
        is_avail = False
        is_friend = False
        if type_ == 'FRIENDS': target = self.friends_w; is_friend=True
        elif type_ == 'JOINED_GROUPS': target = self.joined_groups_w
        elif type_ == 'AVAILABLE_GROUPS': target = self.avail_groups_w; is_avail=True
        
        if not target: return
        for w in target.winfo_children(): w.destroy()

        for item in data:
            name = item['name'] if is_friend else item
            status = item.get('status', '') if is_friend else ''
            
            f = tk.Frame(target, bg="#f0f2f5", cursor="hand2")
            f.pack(fill=tk.X, pady=2, padx=15)
            self.make_hoverable(f, "#e4e6eb", "#f0f2f5")
            
            icon = "●" if is_friend else ("🔓" if is_avail else "#")
            color = "#31a24c" if status == 'Online' else ("#e67e22" if is_avail else "black")
            if not is_friend and not is_avail: color = "black"

            tk.Label(f, text=icon, fg=color, bg="#f0f2f5", font=("Segoe UI", 16)).pack(side=tk.LEFT)
            tk.Label(f, text=name, bg="#f0f2f5", font=("Segoe UI", 14)).pack(side=tk.LEFT, padx=15)
            
            if is_avail:
                f.bind("<Button-1>", lambda e, n=name: self.join_group_dialog(n))
                for child in f.winfo_children(): 
                    child.bind("<Button-1>", lambda e, n=name: self.join_group_dialog(n))
            else:
                is_g = not is_friend
                f.bind("<Button-1>", lambda e, n=name, g=is_g: self.open_chat(n, g))
                for child in f.winfo_children(): 
                    child.bind("<Button-1>", lambda e, n=name, g=is_g: self.open_chat(n, g))

    def open_chat(self, name, is_group):
        self.current_chat = name
        self.is_group = is_group
        self.head_lbl.config(text=name)
        if is_group: 
            self.b_call.pack_forget(); self.b_vid.pack_forget()
        else: 
            self.b_call.pack(side=tk.LEFT, padx=10); self.b_vid.pack(side=tk.LEFT, padx=10)
        
        self.txt_area.config(state='normal')
        self.txt_area.delete(1.0, tk.END)
        self.txt_area.config(state='disabled')
        hist = self.db.get_history(name)
        for sender, content, is_file, t in hist:
            self.render_msg(sender, content, is_file, t)

    def render_msg(self, sender, content, is_file, time):
        self.txt_area.config(state='normal')
        tag = "me" if sender == self.username else "other"
        
        if self.is_group and tag == "other": self.txt_area.insert(tk.END, f"\n{sender}", "name")
        
        if is_file:
            if content.lower().endswith('.wav'):
                self.txt_area.insert(tk.END, f" ▶ Play Voice Message ({content}) ", (tag, "audio"))
            else:
                self.txt_area.insert(tk.END, f" 📄 {content} (Click to Open) ", (tag, "file"))
        else:
            self.txt_area.insert(tk.END, f" {content} ", tag)
            
        self.txt_area.insert(tk.END, f"\n{time}\n", "meta")
        self.txt_area.see(tk.END)
        self.txt_area.config(state='disabled')

    def open_file_click(self, event):
        try:
            index = self.txt_area.index(f"@{event.x},{event.y}")
            line = self.txt_area.get(f"{index} linestart", f"{index} lineend")
            if "📄" in line:
                start = line.find("📄") + 2
                end = line.find("(Click to Open)")
                filename = line[start:end].strip()
                filepath = os.path.abspath(os.path.join("downloads", filename))
                if os.path.exists(filepath):
                    if platform.system() == 'Darwin': subprocess.call(('open', filepath))
                    elif platform.system() == 'Windows': os.startfile(filepath)
                    else: subprocess.call(('xdg-open', filepath))
                else: messagebox.showerror("Error", "File not found.")
        except: pass

    def send_msg(self):
        txt = self.e_msg.get()
        if not self.current_chat: messagebox.showwarning("Warning", "Select chat!"); return
        if not txt: return
        
        enc_txt = SimpleEncryptor.transform(txt)
        cmd = "SEND_GROUP_MSG" if self.is_group else "SEND_MSG"
        self.send({"command": cmd, "to": self.current_chat, "msg": enc_txt})
        
        self.db.save_msg(self.current_chat, self.username, txt, False, time.ctime(), self.is_group)
        self.render_msg(self.username, txt, False, time.ctime())
        self.e_msg.delete(0, tk.END)

    def send_file(self):
        if not self.current_chat: messagebox.showwarning("Warning", "Select chat!"); return
        path = filedialog.askopenfilename()
        if not path: return
        fname = os.path.basename(path)
        with open(path, "rb") as f: enc = base64.b64encode(f.read()).decode('utf-8')
        cmd = "SEND_GROUP_MSG" if self.is_group else "SEND_MSG"
        self.send({"command": cmd, "to": self.current_chat, "msg": enc, "is_file": True, "filename": fname})
        dest = os.path.join("downloads", fname)
        if os.path.abspath(path) != os.path.abspath(dest):
            try: 
                with open(path, "rb") as s, open(dest, "wb") as d: d.write(s.read())
            except: pass
        self.db.save_msg(self.current_chat, self.username, fname, True, time.ctime(), self.is_group)
        self.render_msg(self.username, fname, True, time.ctime())

    # --- VOICE & CALL ---
    def toggle_voice_note(self):
        if not self.current_chat: return
        if not self.is_recording:
            self.is_recording = True
            self.btn_mic.config(fg="red")
            self.audio_frames = []
            threading.Thread(target=self.record_audio_thread, daemon=True).start()
        else:
            self.is_recording = False
            self.btn_mic.config(fg="black")

    def record_audio_thread(self):
        stream = self.p.open(format=pyaudio.paInt16, channels=1, rate=44100, input=True, frames_per_buffer=1024)
        while self.is_recording: self.audio_frames.append(stream.read(1024))
        stream.stop_stream(); stream.close()
        self.save_and_send_voice()

    def save_and_send_voice(self):
        if not self.audio_frames: return
        filename = f"voice_{int(time.time())}.wav"
        filepath = os.path.join("downloads", filename)
        wf = wave.open(filepath, 'wb')
        wf.setnchannels(1); wf.setsampwidth(self.p.get_sample_size(pyaudio.paInt16)); wf.setframerate(44100)
        wf.writeframes(b''.join(self.audio_frames)); wf.close()
        with open(filepath, "rb") as f: enc = base64.b64encode(f.read()).decode('utf-8')
        cmd = "SEND_GROUP_MSG" if self.is_group else "SEND_MSG"
        self.send({"command": cmd, "to": self.current_chat, "msg": enc, "is_file": True, "filename": filename})
        self.db.save_msg(self.current_chat, self.username, filename, True, time.ctime(), self.is_group)
        self.root.after(0, lambda: self.render_msg(self.username, filename, True, time.ctime()))

    def play_voice_note_click(self, event):
        try:
            index = self.txt_area.index(f"@{event.x},{event.y}")
            line = self.txt_area.get(f"{index} linestart", f"{index} lineend")
            if ".wav" in line:
                start = line.find("(") + 1; end = line.find(")")
                filename = line[start:end].strip()
                filepath = os.path.join("downloads", filename)
                if os.path.exists(filepath): threading.Thread(target=self.play_audio_file, args=(filepath,), daemon=True).start()
        except: pass

    def play_audio_file(self, filepath):
        wf = wave.open(filepath, 'rb')
        stream = self.p.open(format=self.p.get_format_from_width(wf.getsampwidth()), channels=wf.getnchannels(), rate=wf.getframerate(), output=True)
        data = wf.readframes(1024)
        while data: stream.write(data); data = wf.readframes(1024)
        stream.stop_stream(); stream.close(); wf.close()

    def init_call(self, type_):
        if not self.current_chat: return
        self.pending_call_type = type_
        self.send({"command": "START_CALL", "target": self.current_chat, "is_group": self.is_group, "call_type": type_})

    def start_call_ui(self, room, type_):
        self.in_call = True
        self.call_connected = False
        self.call_room = room
        self.win_call = tk.Toplevel(self.root)
        self.win_call.title(f"{type_.upper()} Call")
        self.win_call.geometry("900x700")
        self.win_call.configure(bg="black")
        self.remote_video_lbl = tk.Label(self.win_call, text="Calling...", bg="black", fg="white", font=("Segoe UI", 20))
        self.remote_video_lbl.pack(fill=tk.BOTH, expand=True)
        tk.Button(self.win_call, text="End Call", bg="red", fg="white", command=self.end_call_action, font=("Segoe UI", 14)).pack(pady=20)
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
                frame = cv2.resize(frame, (640, 480))
                _, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
                data = pickle.dumps(buffer)
                room_b = self.call_room.encode('utf-8')
                header = bytes([len(room_b)]) + room_b + b'v'
                try: self.udp.sendto(header + data, (SERVER_IP, UDP_PORT))
                except: pass
            time.sleep(0.04)

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
        self.call_connected = False
        if hasattr(self, 'win_call'): self.win_call.destroy()
        if self.cap: self.cap.release()
        if self.audio_stream: self.audio_stream.stop_stream(); self.audio_stream.close()
        if self.audio_out: self.audio_out.stop_stream(); self.audio_out.close()

    def add_friend(self):
        n = simpledialog.askstring("Add Friend", "Username:")
        if n: self.send({"command": "ADD_FRIEND", "friend": n})

    def create_group_dialog(self):
        d = tk.Toplevel(self.root)
        d.title("Create Group")
        d.geometry("300x200")
        tk.Label(d, text="Group Name:").pack()
        name_e = tk.Entry(d); name_e.pack()
        tk.Label(d, text="Password:").pack()
        pass_e = tk.Entry(d, show="*"); pass_e.pack()
        def sub():
            if name_e.get() and pass_e.get():
                self.send({"command": "CREATE_GROUP", "name": name_e.get(), "password": pass_e.get()})
                d.destroy()
        tk.Button(d, text="Create", command=sub).pack(pady=10)

    def join_group_dialog(self, group_name):
        pwd = simpledialog.askstring("Join Group", f"Enter password for {group_name}:", show='*')
        if pwd: self.send({"command": "JOIN_GROUP", "group": group_name, "password": pwd})

    def logout(self):
        self.send({"command": "LOGOUT"})
        self.connected = False
        self.login_ui()

if __name__ == "__main__":
    root = tk.Tk()
    app = ChatGo(root)
    root.mainloop()