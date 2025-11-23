import sqlite3
import threading

class ClientDatabase:
    def __init__(self, db_name="client_data.db"):
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        with self.lock:
            self.conn.execute("CREATE TABLE IF NOT EXISTS msgs (id INTEGER PRIMARY KEY, contact TEXT, sender TEXT, content TEXT, is_file BOOLEAN, time TEXT, is_group BOOLEAN)")
            self.conn.execute("CREATE TABLE IF NOT EXISTS friends (name TEXT)")
            self.conn.execute("CREATE TABLE IF NOT EXISTS groups (name TEXT)")
            self.conn.commit()

    def save_msg(self, contact, sender, content, is_file, time, is_group):
        with self.lock:
            self.conn.execute("INSERT INTO msgs (contact, sender, content, is_file, time, is_group) VALUES (?,?,?,?,?,?)", 
                              (contact, sender, content, is_file, time, is_group))
            self.conn.commit()

    def get_history(self, contact):
        with self.lock:
            cur = self.conn.execute("SELECT sender, content, is_file, time FROM msgs WHERE contact=?", (contact,))
            return cur.fetchall()

    def add_friend(self, name):
        with self.lock:
            self.conn.execute("INSERT INTO friends (name) VALUES (?)", (name,))
            self.conn.commit()

    def get_friends(self):
        with self.lock:
            return [r[0] for r in self.conn.execute("SELECT name FROM friends").fetchall()]

    def add_group(self, name):
        with self.lock:
            self.conn.execute("INSERT INTO groups (name) VALUES (?)", (name,))
            self.conn.commit()

    def get_groups(self):
        with self.lock:
            return [r[0] for r in self.conn.execute("SELECT name FROM groups").fetchall()]