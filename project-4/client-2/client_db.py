import sqlite3
import threading
from datetime import datetime

class ClientDatabase:
    def __init__(self, db_name="client_data.db"):
        self.db_name = db_name
        # Thread lock is crucial for SQLite in a multi-threaded app
        self.lock = threading.Lock()
        self.create_tables()
        self.migrate_tables()

    def get_connection(self):
        return sqlite3.connect(self.db_name, check_same_thread=False)

    def create_tables(self):
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS client_friends (
                    my_username TEXT,
                    friend_name TEXT,
                    UNIQUE(my_username, friend_name)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS client_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    my_username TEXT,
                    other_username TEXT, 
                    sender TEXT,
                    content TEXT,
                    msg_type TEXT DEFAULT 'text',
                    timestamp TEXT,
                    UNIQUE(my_username, other_username, sender, content, timestamp)
                )
            ''')
            conn.commit()
            conn.close()

    def migrate_tables(self):
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT msg_type FROM client_messages LIMIT 1")
            except sqlite3.OperationalError:
                cursor.execute("ALTER TABLE client_messages ADD COLUMN msg_type TEXT DEFAULT 'text'")
                conn.commit()
            conn.close()

    def add_friend(self, my_user, friend_name):
        with self.lock:
            conn = self.get_connection()
            try:
                conn.execute("INSERT INTO client_friends (my_username, friend_name) VALUES (?, ?)", (my_user, friend_name))
                conn.commit()
            except sqlite3.IntegrityError:
                pass
            conn.close()

    def get_friends(self, my_user):
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT friend_name FROM client_friends WHERE my_username=?", (my_user,))
            friends = [row[0] for row in cursor.fetchall()]
            conn.close()
            return friends

    def save_message(self, my_user, other_user, sender, content, msg_type="text", timestamp=None):
        if not timestamp:
            timestamp = datetime.now().strftime("%H:%M:%S")
        
        with self.lock:
            conn = self.get_connection()
            try:
                conn.execute('''
                    INSERT INTO client_messages (my_username, other_username, sender, content, msg_type, timestamp) 
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (my_user, other_user, sender, content, msg_type, timestamp))
                conn.commit()
            except sqlite3.IntegrityError:
                pass
            conn.close()

    def bulk_save_messages(self, my_user, other_user, messages_list):
        if not messages_list: return
        
        data_to_insert = []
        for msg in messages_list:
            # Normalizing data structure
            # Server might send: [sender, content, timestamp] OR [sender, content, type, timestamp]
            if len(msg) == 3:
                data_to_insert.append((my_user, other_user, msg[0], msg[1], 'text', msg[2]))
            elif len(msg) == 4:
                data_to_insert.append((my_user, other_user, msg[0], msg[1], msg[2], msg[3]))

        with self.lock:
            conn = self.get_connection()
            try:
                conn.executemany('''
                    INSERT OR IGNORE INTO client_messages (my_username, other_username, sender, content, msg_type, timestamp) 
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', data_to_insert)
                conn.commit()
            except Exception as e:
                print(f"Bulk save error: {e}")
            conn.close()

    def get_history(self, my_user, other_user):
        with self.lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            query = '''
                SELECT sender, content, msg_type, timestamp FROM client_messages 
                WHERE my_username=? AND other_username=?
                ORDER BY timestamp ASC
            '''
            cursor.execute(query, (my_user, other_user))
            rows = cursor.fetchall()
            conn.close()
            return rows