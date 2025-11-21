import sqlite3
from datetime import datetime

class ChatDatabase:
    def __init__(self, db_name="chat_app.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        # Users Table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT,
                ip_address TEXT,
                udp_port INTEGER
            )
        ''')
        
        # Friends Table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS friends (
                user TEXT,
                friend TEXT,
                FOREIGN KEY(user) REFERENCES users(username),
                FOREIGN KEY(friend) REFERENCES users(username),
                UNIQUE(user, friend)
            )
        ''')

        # Messages Table (Private & Group)
        # For simplicity, if 'room_id' is NULL, it's a private chat between sender and receiver
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT,
                receiver TEXT, 
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_file BOOLEAN DEFAULT 0
            )
        ''')

        # Call Logs
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS call_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                caller TEXT,
                callee TEXT,
                start_time DATETIME,
                end_time DATETIME,
                status TEXT
            )
        ''')
        self.conn.commit()

    # --- User Management ---
    def register_user(self, username, password):
        try:
            self.cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def validate_login(self, username, password):
        self.cursor.execute("SELECT password FROM users WHERE username=?", (username,))
        res = self.cursor.fetchone()
        if res and res[0] == password:
            return True
        return False

    def update_user_address(self, username, ip, udp_port):
        self.cursor.execute("UPDATE users SET ip_address=?, udp_port=? WHERE username=?", (ip, udp_port, username))
        self.conn.commit()

    def get_user_address(self, username):
        self.cursor.execute("SELECT ip_address, udp_port FROM users WHERE username=?", (username,))
        return self.cursor.fetchone()

    # --- Friend Management ---
    def add_friend(self, user, friend):
        try:
            # Check if friend exists
            self.cursor.execute("SELECT * FROM users WHERE username=?", (friend,))
            if not self.cursor.fetchone():
                return "User does not exist."
            
            self.cursor.execute("INSERT INTO friends (user, friend) VALUES (?, ?)", (user, friend))
            self.conn.commit()
            return "Friend added."
        except sqlite3.IntegrityError:
            return "Already friends."

    def get_friends(self, user):
        self.cursor.execute("SELECT friend FROM friends WHERE user=?", (user,))
        return [row[0] for row in self.cursor.fetchall()]

    # --- Message Management ---
    def save_message(self, sender, receiver, content, is_file=False):
        self.cursor.execute("INSERT INTO messages (sender, receiver, content, is_file) VALUES (?, ?, ?, ?)",
                            (sender, receiver, content, is_file))
        self.conn.commit()

    def get_chat_history(self, user1, user2):
        # Fetch messages between two users (both directions)
        query = '''
            SELECT sender, content, timestamp FROM messages 
            WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?)
            ORDER BY timestamp ASC
        '''
        self.cursor.execute(query, (user1, user2, user2, user1))
        return self.cursor.fetchall()

    # --- Call Logs ---
    def log_call(self, caller, callee, status):
        now = datetime.now()
        self.cursor.execute("INSERT INTO call_logs (caller, callee, start_time, status) VALUES (?, ?, ?, ?)",
                            (caller, callee, now, status))
        self.conn.commit()
        return self.cursor.lastrowid

    def end_call_log(self, call_id):
        now = datetime.now()
        self.cursor.execute("UPDATE call_logs SET end_time=? WHERE id=?", (now, call_id))
        self.conn.commit()