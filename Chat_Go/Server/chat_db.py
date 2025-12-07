import sqlite3
import threading
from datetime import datetime

class ChatDatabase:
    def __init__(self, db_name="chat_app.db"):
        self.db_name = db_name
        self.lock = threading.Lock()
        self.create_tables()

    def get_connection(self):
        # Always create a fresh connection per operation for thread safety
        return sqlite3.connect(self.db_name, check_same_thread=False)

    def create_tables(self):
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, ip_address TEXT, udp_port INTEGER)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS friends (user TEXT, friend TEXT, UNIQUE(user, friend))''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY, group_name TEXT UNIQUE, password TEXT, created_by TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS group_members (group_name TEXT, member_name TEXT, UNIQUE(group_name, member_name))''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, sender TEXT, receiver TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, is_file BOOLEAN DEFAULT 0)''')
            conn.commit()
            conn.close()

    def register_user(self, username, password):
        with self.lock:
            conn = self.get_connection()
            try:
                conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
                conn.commit()
                return True
            except: return False
            finally: conn.close()

    def validate_login(self, username, password):
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT password FROM users WHERE username=?", (username,))
            res = cursor.fetchone()
            conn.close()
            return res and res[0] == password

    def update_user_address(self, username, ip, udp_port):
        with self.lock:
            conn = self.get_connection()
            conn.execute("UPDATE users SET ip_address=?, udp_port=? WHERE username=?", (ip, udp_port, username))
            conn.commit()
            conn.close()

    def add_friend(self, user, friend):
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT 1 FROM users WHERE username=?", (friend,))
                if not cursor.fetchone(): return "User not found"
                cursor.execute("INSERT INTO friends (user, friend) VALUES (?, ?)", (user, friend))
                conn.commit()
                return "Friend added"
            except: return "Already friends"
            finally: conn.close()

    def get_friends(self, user):
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT friend FROM friends WHERE user=?", (user,))
            res = [row[0] for row in cursor.fetchall()]
            conn.close()
            return res

    def create_group(self, group_name, password, creator):
        with self.lock:
            conn = self.get_connection()
            try:
                conn.execute("INSERT INTO groups (group_name, password, created_by) VALUES (?, ?, ?)", (group_name, password, creator))
                conn.execute("INSERT INTO group_members (group_name, member_name) VALUES (?, ?)", (group_name, creator))
                conn.commit()
                return True
            except: return False
            finally: conn.close()

    def get_joined_groups(self, user):
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT group_name FROM group_members WHERE member_name=?", (user,))
            res = [row[0] for row in cursor.fetchall()]
            conn.close()
            return res

    def get_available_groups(self, user):
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''SELECT group_name FROM groups WHERE group_name NOT IN (SELECT group_name FROM group_members WHERE member_name=?)''', (user,))
            res = [row[0] for row in cursor.fetchall()]
            conn.close()
            return res

    def join_group(self, group_name, user, password):
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT password FROM groups WHERE group_name=?", (group_name,))
                res = cursor.fetchone()
                if not res: return "Group not found"
                
                if res[0] == password:
                    try:
                        cursor.execute("INSERT INTO group_members (group_name, member_name) VALUES (?, ?)", (group_name, user))
                        conn.commit()
                        return "Success"
                    except: return "Already joined"
                else: return "Incorrect Password"
            finally: conn.close()

    def get_group_members(self, group_name):
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT member_name FROM group_members WHERE group_name=?", (group_name,))
            res = [row[0] for row in cursor.fetchall()]
            conn.close()
            return res

    def is_member(self, group_name, user):
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM group_members WHERE group_name=? AND member_name=?", (group_name, user))
            res = cursor.fetchone() is not None
            conn.close()
            return res

    def save_message(self, sender, receiver, content, is_file=False):
        with self.lock:
            conn = self.get_connection()
            conn.execute("INSERT INTO messages (sender, receiver, content, is_file) VALUES (?, ?, ?, ?)", (sender, receiver, content, is_file))
            conn.commit()
            conn.close()

    def get_chat_history(self, user1, user2):
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT sender, content, timestamp FROM messages WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?) ORDER BY timestamp ASC", (user1, user2, user2, user1))
            res = cursor.fetchall()
            conn.close()
            return res