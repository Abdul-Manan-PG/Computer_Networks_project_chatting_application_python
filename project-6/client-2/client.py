import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, simpledialog
import socket
import threading
import json
import time
import os
import base64
import platform
import subprocess
from client_db import ClientDatabase

# Configuration
TCP_PORT = 5555
UDP_PORT = 0
UPLOAD_FOLDER = 'client_downloads'

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

class ChatGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Python Messenger")
        self.root.geometry("1000x700")
        self.root.configure(bg="white")

        # --- Backend State ---
        self.tcp_socket = None
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_socket.bind(('0.0.0.0', UDP_PORT))
        self.my_udp_port = self.udp_socket.getsockname()[1]
        
        self.connected = False
        self.username = None
        self.db = ClientDatabase()
        self.friend_statuses = {}
        self.current_chat_user = None
        self.is_current_chat_group = False
        
        self.in_call = False
        self.target_ip = None
        self.target_udp_port = None

        # --- UI Colors & Fonts (Messenger Style) ---
        self.colors = {
            "primary": "#0084ff",       # Messenger Blue
            "received": "#e4e6eb",      # Light Gray for received
            "text_received": "black",
            "text_sent": "white",
            "bg": "white",
            "sidebar_bg": "#f0f2f5",
            "header_bg": "white",
            "text_color": "#050505",
            "status_online": "#31a24c",
            "status_offline": "#bcc0c4"
        }
        self.fonts = {
            "header": ("Segoe UI", 16, "bold"),
            "sub_header": ("Segoe UI", 10, "bold"),
            "body": ("Segoe UI", 11),
            "small": ("Segoe UI", 9)
        }

        # --- Styles ---
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        self.style.configure("Login.TFrame", background="white")
        self.style.configure("Login.TLabel", background="white", font=self.fonts["body"])
        self.style.configure("Login.TButton", font=self.fonts["sub_header"], padding=10, background=self.colors["primary"], foreground="white")
        self.style.map("Login.TButton", background=[("active", "#0073e6")])

        self.show_login_screen()
        
        self.msg_queue = []
        self.root.after(100, self.process_queue)

    # ======================= UI SCREENS =======================

    def show_login_screen(self):
        self.clear_window()
        self.root.configure(bg="white")
        
        # Center Frame
        frame = ttk.Frame(self.root, style="Login.TFrame")
        frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        # Logo/Header
        tk.Label(frame, text="Messenger", font=("Segoe UI", 24, "bold"), fg=self.colors["primary"], bg="white").pack(pady=(0, 10))
        tk.Label(frame, text="Connect with friends and the world around you.", font=("Segoe UI", 12), fg="gray", bg="white").pack(pady=(0, 30))

        # Inputs
        tk.Label(frame, text="Server IP", font=self.fonts["sub_header"], bg="white", fg="gray").pack(anchor=tk.W)
        self.entry_ip = ttk.Entry(frame, width=40, font=self.fonts["body"])
        self.entry_ip.insert(0, "127.0.0.1")
        self.entry_ip.pack(pady=(0, 15), ipady=3)

        tk.Label(frame, text="Username", font=self.fonts["sub_header"], bg="white", fg="gray").pack(anchor=tk.W)
        self.entry_user = ttk.Entry(frame, width=40, font=self.fonts["body"])
        self.entry_user.pack(pady=(0, 15), ipady=3)

        tk.Label(frame, text="Password", font=self.fonts["sub_header"], bg="white", fg="gray").pack(anchor=tk.W)
        self.entry_pass = ttk.Entry(frame, width=40, font=self.fonts["body"], show="*")
        self.entry_pass.pack(pady=(0, 25), ipady=3)

        # Buttons
        btn_frame = tk.Frame(frame, bg="white")
        btn_frame.pack(fill=tk.X)
        
        login_btn = tk.Button(btn_frame, text="Log In", font=self.fonts["sub_header"], bg=self.colors["primary"], fg="white", 
                              bd=0, padx=20, pady=10, cursor="hand2", command=lambda: self.connect_and_auth("LOGIN"))
        login_btn.pack(fill=tk.X, pady=5)
        
        reg_btn = tk.Button(btn_frame, text="Create New Account", font=self.fonts["sub_header"], bg="#42b72a", fg="white", 
                            bd=0, padx=20, pady=10, cursor="hand2", command=lambda: self.connect_and_auth("REGISTER"))
        reg_btn.pack(fill=tk.X, pady=5)

    def show_dashboard(self):
        self.clear_window()
        
        # --- Main Container ---
        container = tk.Frame(self.root, bg="white")
        container.pack(fill=tk.BOTH, expand=True)

        # --- Left Sidebar ---
        sidebar = tk.Frame(container, width=300, bg=self.colors["sidebar_bg"])
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        # Sidebar Header (User Profile & Refresh)
        sb_header = tk.Frame(sidebar, bg=self.colors["sidebar_bg"], height=60)
        sb_header.pack(fill=tk.X, padx=10, pady=15)
        
        # User Avatar Placeholder (Circle)
        avatar = tk.Label(sb_header, text=self.username[0].upper(), font=("Segoe UI", 14, "bold"), 
                          bg="gray", fg="white", width=3, height=1)
        avatar.pack(side=tk.LEFT)
        
        tk.Label(sb_header, text="Chats", font=("Segoe UI", 20, "bold"), bg=self.colors["sidebar_bg"], fg="black").pack(side=tk.LEFT, padx=10)

        # Refresh Button (Icon style)
        refresh_btn = tk.Button(sb_header, text="⟳", font=("Segoe UI", 14, "bold"), bg="#e4e6eb", fg="black", 
                                bd=0, width=3, cursor="hand2", command=self.request_data)
        refresh_btn.pack(side=tk.RIGHT)

        # Search/Add Bar
        action_bar = tk.Frame(sidebar, bg=self.colors["sidebar_bg"])
        action_bar.pack(fill=tk.X, padx=10, pady=5)
        
        self.entry_friend = tk.Entry(action_bar, bg="white", relief=tk.FLAT, font=self.fonts["body"])
        self.entry_friend.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5, padx=(0,5))
        
        add_btn = tk.Button(action_bar, text="+", bg="#e4e6eb", bd=0, width=3, command=self.add_friend)
        add_btn.pack(side=tk.LEFT)

        # New Group Button
        tk.Button(sidebar, text="+ Create New Group", bg=self.colors["sidebar_bg"], fg=self.colors["primary"], 
                  font=("Segoe UI", 9, "bold"), bd=0, cursor="hand2", command=self.create_group_dialog, anchor="w").pack(fill=tk.X, padx=15, pady=5)

        # Chat List (Scrollable)
        self.canvas_list = tk.Canvas(sidebar, bg=self.colors["sidebar_bg"], bd=0, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(sidebar, orient="vertical", command=self.canvas_list.yview)
        self.list_frame = tk.Frame(self.canvas_list, bg=self.colors["sidebar_bg"])
        
        self.list_frame.bind("<Configure>", lambda e: self.canvas_list.configure(scrollregion=self.canvas_list.bbox("all")))
        self.canvas_list.create_window((0, 0), window=self.list_frame, anchor="nw", width=300)
        self.canvas_list.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas_list.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Logout Button (Bottom of Sidebar)
        logout_btn = tk.Button(sidebar, text="Log Out", bg="#e4e6eb", fg="black", font=("Segoe UI", 10, "bold"),
                               bd=0, pady=10, cursor="hand2", command=self.logout)
        logout_btn.pack(side=tk.BOTTOM, fill=tk.X)

        # --- Right Chat Area ---
        self.main_area = tk.Frame(container, bg="white")
        self.main_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Chat Header
        self.header_frame = tk.Frame(self.main_area, bg="white", height=60, bd=1, relief=tk.RIDGE)
        self.header_frame.pack(fill=tk.X)
        
        self.header_label = tk.Label(self.header_frame, text="Select a chat", font=("Segoe UI", 14, "bold"), bg="white", fg="black")
        self.header_label.pack(side=tk.LEFT, padx=20, pady=15)
        
        # Header Actions
        self.btn_frame_header = tk.Frame(self.header_frame, bg="white")
        self.btn_frame_header.pack(side=tk.RIGHT, padx=20)
        
        self.btn_add_member = tk.Button(self.btn_frame_header, text="Add Member", state=tk.DISABLED, 
                                        command=self.add_member_dialog, bg="#e4e6eb", bd=0, padx=10, pady=5, cursor="hand2")
        self.btn_add_member.pack(side=tk.RIGHT, padx=5)
        
        self.btn_call = tk.Button(self.btn_frame_header, text="📞", state=tk.DISABLED, font=("Segoe UI", 12),
                                  command=self.init_call, bg="white", fg=self.colors["primary"], bd=0, cursor="hand2")
        self.btn_call.pack(side=tk.RIGHT, padx=5)

        # Message Display Area
        self.chat_display = scrolledtext.ScrolledText(self.main_area, bg="white", font=("Segoe UI Emoji", 11), 
                                                      state=tk.DISABLED, wrap=tk.WORD, bd=0, padx=20, pady=20)
        self.chat_display.pack(fill=tk.BOTH, expand=True)
        
        # Message Tags (Bubbles simulation)
        self.chat_display.tag_config("me", justify='right', rmargin=10, lmargin1=100)
        self.chat_display.tag_config("other", justify='left', lmargin1=10, rmargin=100)
        
        # "Bubbles" are hard in Tkinter Text, we use colors
        self.chat_display.tag_config("bubble_me", background=self.colors["primary"], foreground="white", borderwidth=5, relief="flat")
        self.chat_display.tag_config("bubble_other", background=self.colors["received"], foreground="black", borderwidth=5, relief="flat")
        
        self.chat_display.tag_config("group_sender", font=("Segoe UI", 8, "bold"), foreground="gray", justify='left', lmargin1=15)
        self.chat_display.tag_config("timestamp_me", font=("Segoe UI", 7), foreground="gray", justify='right', rmargin=15)
        self.chat_display.tag_config("timestamp_other", font=("Segoe UI", 7), foreground="gray", justify='left', lmargin1=15)
        self.chat_display.tag_config("file", underline=1, font=("Segoe UI", 10, "bold"))
        self.chat_display.tag_bind("file", "<Button-1>", self.open_file)

        # Input Area
        input_wrapper = tk.Frame(self.main_area, bg="white", pady=10)
        input_wrapper.pack(fill=tk.X)
        
        input_frame = tk.Frame(input_wrapper, bg="#f0f2f5", bd=0, padx=5, pady=5, relief=tk.FLAT)
        input_frame.pack(fill=tk.X, padx=20, pady=10)
        
        # File Button
        tk.Button(input_frame, text="📎", command=self.send_file, bg="#f0f2f5", fg=self.colors["primary"], 
                  bd=0, font=("Segoe UI", 14), cursor="hand2").pack(side=tk.LEFT, padx=5)
        
        # Entry
        self.msg_entry = tk.Entry(input_frame, font=("Segoe UI", 11), bg="#f0f2f5", bd=0)
        self.msg_entry.bind("<Return>", lambda e: self.send_msg())
        self.msg_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10, ipady=5)
        
        # Send Button
        self.btn_send = tk.Button(input_frame, text="➤", command=self.send_msg, bg="#f0f2f5", fg=self.colors["primary"], 
                                  bd=0, font=("Segoe UI", 14), cursor="hand2")
        self.btn_send.pack(side=tk.RIGHT, padx=5)

        self.request_data()

    # ======================= LOGIC & NETWORK =======================

    def connect_and_auth(self, action):
        ip = self.entry_ip.get()
        user = self.entry_user.get()
        pwd = self.entry_pass.get()

        if not self.connected:
            try:
                self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.tcp_socket.settimeout(5)
                self.tcp_socket.connect((ip, TCP_PORT))
                self.tcp_socket.settimeout(None)
                self.connected = True
                threading.Thread(target=self.listen_tcp, daemon=True).start()
            except Exception as e:
                messagebox.showerror("Error", f"Could not connect: {e}")
                return

        payload = {"command": action, "username": user, "password": pwd, "udp_port": self.my_udp_port}
        self.send_json(payload)

    def send_json(self, data):
        if self.connected:
            try:
                msg = json.dumps(data) + "\n"
                self.tcp_socket.sendall(msg.encode('utf-8'))
            except:
                self.connected = False
                messagebox.showerror("Error", "Disconnected from server")

    def listen_tcp(self):
        buffer = ""
        while self.connected:
            try:
                data = self.tcp_socket.recv(1024*1024).decode('utf-8')
                if not data:
                    self.connected = False
                    break
                buffer += data
                while "\n" in buffer:
                    message_str, buffer = buffer.split("\n", 1)
                    if not message_str.strip(): continue
                    try: self.msg_queue.append(json.loads(message_str))
                    except: pass
            except:
                self.connected = False
                break

    # ======================= UI UPDATES =======================

    def process_queue(self):
        while len(self.msg_queue) > 0:
            self.handle_message(self.msg_queue.pop(0))
        self.root.after(100, self.process_queue)

    def handle_message(self, msg):
        type_ = msg.get('type')

        if 'status' in msg and 'message' in msg and not type_ and 'data' not in msg:
            if msg['status'] == 'success':
                if "Welcome" in msg['message']: 
                    self.username = self.entry_user.get()
                    self.show_dashboard()
                elif "Group created" in msg['message']:
                    self.request_data() # Refresh list
            elif msg['status'] == 'error':
                messagebox.showerror("Error", msg['message'])
        
        elif type_ == 'MESSAGE':
            sender = msg['from']
            content = msg['content']
            msg_type = msg.get('msg_type', 'text')
            filename = msg.get('filename', '')
            is_group = msg.get('is_group', False)
            to_group = msg.get('to_group', None)

            if msg_type != 'text':
                try:
                    file_data = base64.b64decode(content)
                    filepath = os.path.join(UPLOAD_FOLDER, filename)
                    if os.path.exists(filepath):
                        filename = f"{int(time.time())}_{filename}"
                        filepath = os.path.join(UPLOAD_FOLDER, filename)
                    with open(filepath, "wb") as f: f.write(file_data)
                    content = filename
                except: content = "[File Error]"

            other_user = to_group if is_group else sender
            if self.username:
                self.db.save_message(self.username, other_user, sender, content, msg_type, msg['timestamp'], is_group)

            if self.current_chat_user == other_user:
                self.display_chat_message(sender, content, msg_type, msg['timestamp'], is_group)

        elif msg.get('status') == 'success' and 'data' in msg:
            data = msg['data']
            is_group_list = msg.get('is_group_list', False)
            
            if is_group_list:
                for g in data: self.db.add_group(self.username, g)
                self.update_sidebar_list()
            
            elif isinstance(data, list) and (len(data) == 0 or isinstance(data[0], dict)):
                for f in data:
                    self.db.add_friend(self.username, f['username'])
                    self.friend_statuses[f['username']] = f['status']
                self.update_sidebar_list()

    # ======================= CHAT LOGIC =======================

    def request_data(self):
        if self.connected:
            self.send_json({"command": "GET_FRIENDS"})
            self.send_json({"command": "GET_GROUPS"})

    def update_sidebar_list(self):
        for widget in self.list_frame.winfo_children(): widget.destroy()

        friends = self.db.get_friends(self.username)
        groups = self.db.get_groups(self.username)

        # Groups
        if groups:
            tk.Label(self.list_frame, text="GROUPS", bg=self.colors["sidebar_bg"], fg="gray", font=("Segoe UI", 9, "bold"), anchor="w").pack(fill=tk.X, padx=15, pady=(10,2))
            for g in groups:
                self.create_sidebar_btn(f"# {g}", True, lambda n=g: self.select_chat(n, True))

        # Friends
        tk.Label(self.list_frame, text="FRIENDS", bg=self.colors["sidebar_bg"], fg="gray", font=("Segoe UI", 9, "bold"), anchor="w").pack(fill=tk.X, padx=15, pady=(10,2))
        for f in friends:
            status = self.friend_statuses.get(f, "Offline")
            self.create_sidebar_btn(f, False, lambda n=f: self.select_chat(n, False), status)

    def create_sidebar_btn(self, name, is_group, command, status="Offline"):
        frame = tk.Frame(self.list_frame, bg=self.colors["sidebar_bg"], cursor="hand2")
        frame.pack(fill=tk.X, pady=1, padx=5)
        
        # Avatar
        initial = name[0].upper() if not is_group else "#"
        av_bg = "gray" if is_group else (self.colors["status_online"] if status == "Online" else self.colors["status_offline"])
        av_lbl = tk.Label(frame, text=initial, font=("Segoe UI", 10, "bold"), bg=av_bg, fg="white", width=3)
        av_lbl.pack(side=tk.LEFT, padx=(5, 10), pady=5)
        
        # Name
        name_lbl = tk.Label(frame, text=name, font=("Segoe UI", 11), bg=self.colors["sidebar_bg"], fg="black")
        name_lbl.pack(side=tk.LEFT)
        
        # Bind Click
        for w in [frame, av_lbl, name_lbl]:
            w.bind("<Button-1>", lambda e: command())

    def select_chat(self, name, is_group):
        self.current_chat_user = name
        self.is_current_chat_group = is_group
        
        self.header_label.config(text=name)
        
        self.btn_call.config(state=tk.DISABLED if is_group else tk.NORMAL)
        self.btn_add_member.config(state=tk.NORMAL if is_group else tk.DISABLED)
        self.toggle_inputs("Online" if is_group else self.friend_statuses.get(name, "Offline"))

        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.delete(1.0, tk.END)
        self.chat_display.config(state=tk.DISABLED)
        
        msgs = self.db.get_history(self.username, name)
        for m in msgs:
            self.display_chat_message(m[0], m[1], m[2], m[3], m[4])

    def display_chat_message(self, sender, content, msg_type, timestamp, is_group):
        self.chat_display.config(state=tk.NORMAL)
        
        is_me = (sender == self.username)
        align = "me" if is_me else "other"
        bubble_tag = "bubble_me" if is_me else "bubble_other"
        ts_tag = "timestamp_me" if is_me else "timestamp_other"
        
        # Group Sender Name
        if is_group and not is_me:
            self.chat_display.insert(tk.END, f"{sender}\n", "group_sender")
        
        # Message Content (Simulating padding with spaces)
        padded_content = f"  {content}  " 
        
        if msg_type == 'text':
            self.chat_display.insert(tk.END, padded_content + "\n", (align, bubble_tag))
        else:
            self.chat_display.insert(tk.END, f"  📄 {content}  \n", (align, bubble_tag, "file"))
            
        self.chat_display.insert(tk.END, f"{timestamp}\n\n", ts_tag)
            
        self.chat_display.see(tk.END)
        self.chat_display.config(state=tk.DISABLED)

    def send_msg(self):
        txt = self.msg_entry.get()
        if not txt or not self.current_chat_user: return
        
        if self.is_current_chat_group:
            self.send_json({"command": "SEND_GROUP_MSG", "to": self.current_chat_user, "message": txt})
        else:
            if self.friend_statuses.get(self.current_chat_user) == "Offline": return
            self.send_json({"command": "SEND_MSG", "to": self.current_chat_user, "message": txt})
        
        t = time.strftime("%H:%M:%S")
        self.db.save_message(self.username, self.current_chat_user, self.username, txt, "text", t, self.is_current_chat_group)
        self.display_chat_message(self.username, txt, "text", t, self.is_current_chat_group)
        self.msg_entry.delete(0, tk.END)

    # ======================= GROUP FEATURES =======================

    def create_group_dialog(self):
        name = simpledialog.askstring("New Group", "Enter Group Name:")
        if name:
            self.send_json({"command": "CREATE_GROUP", "group_name": name})

    def add_member_dialog(self):
        member = simpledialog.askstring("Add Member", f"Enter username to add to {self.current_chat_user}:")
        if member:
            self.send_json({"command": "ADD_TO_GROUP", "group_name": self.current_chat_user, "member": member})

    # ======================= HELPERS =======================
    
    def add_friend(self):
        name = self.entry_friend.get()
        if name:
            self.send_json({"command": "ADD_FRIEND", "friend_name": name})
            self.entry_friend.delete(0, tk.END)
            self.root.after(500, self.request_data)

    def send_file(self):
        if not self.current_chat_user: return
        path = filedialog.askopenfilename()
        if not path: return
        filename = os.path.basename(path)
        with open(path, "rb") as f: enc = base64.b64encode(f.read()).decode('utf-8')
        
        cmd = "SEND_GROUP_MSG" if self.is_current_chat_group else "SEND_MSG"
        self.send_json({"command": cmd, "to": self.current_chat_user, "message": enc, "msg_type": "file", "filename": filename})
        
        t = time.strftime("%H:%M:%S")
        self.db.save_message(self.username, self.current_chat_user, self.username, filename, "file", t, self.is_current_chat_group)
        self.display_chat_message(self.username, filename, "file", t, self.is_current_chat_group)

    def open_file(self, event):
        try:
            idx = self.chat_display.index(f"@{event.x},{event.y}")
            line = self.chat_display.get(f"{idx} linestart", f"{idx} lineend")
            # Adjust parsing logic for messenger style bubble
            if "📄" in line:
                filename = line.split("📄")[1].strip()
                filepath = os.path.join(UPLOAD_FOLDER, filename)
                if os.path.exists(filepath):
                    if platform.system() == 'Darwin': subprocess.call(('open', filepath))
                    elif platform.system() == 'Windows': os.startfile(filepath)
                    else: subprocess.call(('xdg-open', filepath))
                else: messagebox.showerror("Error", "File not found.")
        except: pass

    def init_call(self):
        if not self.current_chat_user or self.is_current_chat_group: return
        self.send_json({"command": "INIT_CALL", "callee": self.current_chat_user, "call_type": "voice"})
        messagebox.showinfo("Call", "Calling... (Simulated)")

    def logout(self):
        self.send_json({"command": "LOGOUT"})
        self.connected = False
        self.show_login_screen()

    def toggle_inputs(self, status):
        state = tk.NORMAL if (status == "Online" or self.is_current_chat_group) else tk.DISABLED
        self.msg_entry.config(state=state)
        self.btn_send.config(state=state)

    def clear_window(self):
        for widget in self.root.winfo_children(): widget.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = ChatGUI(root)
    root.mainloop()