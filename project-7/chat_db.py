import sqlite3
from datetime import datetime

class ChatDatabase:
    def __init__(self, db_name="chat_app.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, ip_address TEXT, udp_port INTEGER)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS friends (user TEXT, friend TEXT, UNIQUE(user, friend))''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY, group_name TEXT UNIQUE, created_by TEXT)''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS group_members (group_name TEXT, member_name TEXT, UNIQUE(group_name, member_name))''')
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, sender TEXT, receiver TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, is_file BOOLEAN DEFAULT 0)''')
        self.conn.commit()

    def register_user(self, username, password):
        try:
            self.cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
            self.conn.commit()
            return True
        except: return False

    def validate_login(self, username, password):
        self.cursor.execute("SELECT password FROM users WHERE username=?", (username,))
        res = self.cursor.fetchone()
        return res and res[0] == password

    def update_user_address(self, username, ip, udp_port):
        self.cursor.execute("UPDATE users SET ip_address=?, udp_port=? WHERE username=?", (ip, udp_port, username))
        self.conn.commit()

    def get_user_address(self, username):
        self.cursor.execute("SELECT ip_address, udp_port FROM users WHERE username=?", (username,))
        return self.cursor.fetchone()

    def add_friend(self, user, friend):
        try:
            self.cursor.execute("SELECT 1 FROM users WHERE username=?", (friend,))
            if not self.cursor.fetchone(): return "User not found"
            self.cursor.execute("INSERT INTO friends (user, friend) VALUES (?, ?)", (user, friend))
            self.conn.commit()
            return "Friend added"
        except: return "Already friends"

    def get_friends(self, user):
        self.cursor.execute("SELECT friend FROM friends WHERE user=?", (user,))
        return [row[0] for row in self.cursor.fetchall()]

    def create_group(self, group_name, creator):
        try:
            self.cursor.execute("INSERT INTO groups (group_name, created_by) VALUES (?, ?)", (group_name, creator))
            self.cursor.execute("INSERT INTO group_members (group_name, member_name) VALUES (?, ?)", (group_name, creator))
            self.conn.commit()
            return True
        except: return False

    def add_group_member(self, group_name, member_name):
        try:
            self.cursor.execute("SELECT 1 FROM groups WHERE group_name=?", (group_name,))
            if not self.cursor.fetchone(): return "Group not found"
            self.cursor.execute("SELECT 1 FROM users WHERE username=?", (member_name,))
            if not self.cursor.fetchone(): return "User not found"
            self.cursor.execute("INSERT INTO group_members (group_name, member_name) VALUES (?, ?)", (group_name, member_name))
            self.conn.commit()
            return "Member added"
        except: return "Already in group"

    def get_user_groups(self, user):
        self.cursor.execute("SELECT group_name FROM group_members WHERE member_name=?", (user,))
        return [row[0] for row in self.cursor.fetchall()]

    def get_group_members(self, group_name):
        self.cursor.execute("SELECT member_name FROM group_members WHERE group_name=?", (group_name,))
        return [row[0] for row in self.cursor.fetchall()]

    def is_member(self, group_name, user):
        self.cursor.execute("SELECT 1 FROM group_members WHERE group_name=? AND member_name=?", (group_name, user))
        return self.cursor.fetchone() is not None

    def save_message(self, sender, receiver, content, is_file=False):
        self.cursor.execute("INSERT INTO messages (sender, receiver, content, is_file) VALUES (?, ?, ?, ?)", (sender, receiver, content, is_file))
        self.conn.commit()

    def get_chat_history(self, user1, user2):
        self.cursor.execute("SELECT sender, content, timestamp FROM messages WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?) ORDER BY timestamp ASC", (user1, user2, user2, user1))
        return self.cursor.fetchall()