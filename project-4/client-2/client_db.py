import sqlite3
from datetime import datetime

class ClientDatabase:
    def __init__(self, db_name="client_data.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        # Stores friends for a specific logged-in user
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS client_friends (
                my_username TEXT,
                friend_name TEXT,
                UNIQUE(my_username, friend_name)
            )
        ''')

        # Stores messages
        # ADDED UNIQUE constraint to prevent duplicates during sync
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS client_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                my_username TEXT,
                other_username TEXT, 
                sender TEXT,
                content TEXT,
                timestamp TEXT,
                UNIQUE(my_username, other_username, sender, content, timestamp)
            )
        ''')
        self.conn.commit()

    def add_friend(self, my_user, friend_name):
        try:
            self.cursor.execute("INSERT INTO client_friends (my_username, friend_name) VALUES (?, ?)", 
                                (my_user, friend_name))
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass # Already added

    def get_friends(self, my_user):
        self.cursor.execute("SELECT friend_name FROM client_friends WHERE my_username=?", (my_user,))
        return [row[0] for row in self.cursor.fetchall()]

    def save_message(self, my_user, other_user, sender, content, timestamp=None):
        if not timestamp:
            timestamp = datetime.now().strftime("%H:%M:%S")
        
        try:
            self.cursor.execute('''
                INSERT INTO client_messages (my_username, other_username, sender, content, timestamp) 
                VALUES (?, ?, ?, ?, ?)
            ''', (my_user, other_user, sender, content, timestamp))
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass # Ignore duplicate

    # --- NEW: Efficient Bulk Save for Syncing ---
    def bulk_save_messages(self, my_user, other_user, messages_list):
        """
        Efficiently saves a list of messages from the server.
        messages_list format: [(sender, content, timestamp), ...]
        """
        if not messages_list:
            return

        # Prepare data for bulk insert
        data_to_insert = []
        for msg in messages_list:
            # msg is (sender, content, timestamp)
            # We append (my_user, other_user, sender, content, timestamp)
            data_to_insert.append((my_user, other_user, msg[0], msg[1], msg[2]))

        try:
            # OR IGNORE skips rows that already exist (based on UNIQUE constraint)
            self.cursor.executemany('''
                INSERT OR IGNORE INTO client_messages (my_username, other_username, sender, content, timestamp) 
                VALUES (?, ?, ?, ?, ?)
            ''', data_to_insert)
            self.conn.commit()
        except Exception as e:
            print(f"Bulk save error: {e}")

    def get_history(self, my_user, other_user):
        query = '''
            SELECT sender, content, timestamp FROM client_messages 
            WHERE my_username=? AND other_username=?
            ORDER BY timestamp ASC
        '''
        self.cursor.execute(query, (my_user, other_user))
        return self.cursor.fetchall()