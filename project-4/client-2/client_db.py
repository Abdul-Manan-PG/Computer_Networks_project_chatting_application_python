import sqlite3
from datetime import datetime

class ClientDatabase:
    def __init__(self, db_name="client_data.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
        self.migrate_tables() # Ensure old DBs get new columns

    def create_tables(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS client_friends (
                my_username TEXT,
                friend_name TEXT,
                UNIQUE(my_username, friend_name)
            )
        ''')

        self.cursor.execute('''
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
        self.conn.commit()

    def migrate_tables(self):
        """Adds msg_type column to existing databases if missing."""
        try:
            self.cursor.execute("SELECT msg_type FROM client_messages LIMIT 1")
        except sqlite3.OperationalError:
            # Column missing, add it
            self.cursor.execute("ALTER TABLE client_messages ADD COLUMN msg_type TEXT DEFAULT 'text'")
            self.conn.commit()

    def add_friend(self, my_user, friend_name):
        try:
            self.cursor.execute("INSERT INTO client_friends (my_username, friend_name) VALUES (?, ?)", 
                                (my_user, friend_name))
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def get_friends(self, my_user):
        self.cursor.execute("SELECT friend_name FROM client_friends WHERE my_username=?", (my_user,))
        return [row[0] for row in self.cursor.fetchall()]

    def save_message(self, my_user, other_user, sender, content, msg_type="text", timestamp=None):
        if not timestamp:
            timestamp = datetime.now().strftime("%H:%M:%S")
        
        try:
            self.cursor.execute('''
                INSERT INTO client_messages (my_username, other_username, sender, content, msg_type, timestamp) 
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (my_user, other_user, sender, content, msg_type, timestamp))
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def bulk_save_messages(self, my_user, other_user, messages_list):
        if not messages_list: return
        data_to_insert = []
        for msg in messages_list:
            # Handle old server history format (sender, content, timestamp) vs new (sender, content, type, timestamp)
            if len(msg) == 3:
                data_to_insert.append((my_user, other_user, msg[0], msg[1], 'text', msg[2]))
            elif len(msg) == 4:
                data_to_insert.append((my_user, other_user, msg[0], msg[1], msg[2], msg[3]))

        try:
            self.cursor.executemany('''
                INSERT OR IGNORE INTO client_messages (my_username, other_username, sender, content, msg_type, timestamp) 
                VALUES (?, ?, ?, ?, ?, ?)
            ''', data_to_insert)
            self.conn.commit()
        except Exception as e:
            print(f"Bulk save error: {e}")

    def get_history(self, my_user, other_user):
        # Now returns msg_type as well
        query = '''
            SELECT sender, content, msg_type, timestamp FROM client_messages 
            WHERE my_username=? AND other_username=?
            ORDER BY timestamp ASC
        '''
        self.cursor.execute(query, (my_user, other_user))
        return self.cursor.fetchall()