import json
import os
import time

# Base directory for all user data
BASE_DIR = "data"

def ensure_user_structure(username):
    """Creates: data/{username}/"""
    user_path = os.path.join(BASE_DIR, username)
    if not os.path.exists(user_path):
        os.makedirs(user_path)
    return user_path

def get_existing_users():
    """
    Scans the data directory and returns a list of all usernames 
    that have a folder (historical users).
    """
    if not os.path.exists(BASE_DIR):
        return []
    
    # List all directories in data/
    users = [name for name in os.listdir(BASE_DIR) 
             if os.path.isdir(os.path.join(BASE_DIR, name))]
    return users

def save_message_history(username, message_data):
    """Appends a message to data/{username}/history.json"""
    user_path = ensure_user_structure(username)
    history_file = os.path.join(user_path, "history.json")
    
    history = []
    
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r') as f:
                history = json.load(f)
        except (json.JSONDecodeError, ValueError):
            history = [] 

    if 'timestamp' not in message_data:
        message_data['timestamp'] = time.time()

    history.append(message_data)

    with open(history_file, 'w') as f:
        json.dump(history, f, indent=2)

def load_user_history(username):
    """Returns list of messages."""
    user_path = ensure_user_structure(username)
    history_file = os.path.join(user_path, "history.json")
    
    if not os.path.exists(history_file):
        return []
    
    try:
        with open(history_file, 'r') as f:
            return json.load(f)
    except:
        return []