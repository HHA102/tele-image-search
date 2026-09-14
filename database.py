import sqlite3
import threading

# Sử dụng lock để tránh lỗi khi ghi từ nhiều coroutines
db_lock = threading.Lock()

conn = sqlite3.connect('images.db', check_same_thread=False)
cursor = conn.cursor()

def init_db():
    with db_lock:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS images (
                message_id INTEGER,
                chat_id INTEGER,
                chat_title TEXT,
                date INTEGER,
                link TEXT,
                phash TEXT,
                PRIMARY KEY (message_id, chat_id)
            )
        ''')
        conn.commit()

def save_image_metadata(message_id, chat_id, chat_title, date, link, phash):
    with db_lock:
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO images (message_id, chat_id, chat_title, date, link, phash)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (message_id, chat_id, chat_title, date, link, phash))
            conn.commit()
        except Exception as e:
            print(f"Lỗi ghi database: {e}")

def get_all_images():
    with db_lock:
        cursor.execute('SELECT message_id, chat_id, chat_title, date, link, phash FROM images')
        return cursor.fetchall()

