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