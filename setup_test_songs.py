import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "blossom.db")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    cursor.execute("DELETE FROM songs;")
    print("[+] Старые треки удалены из базы.")
except Exception as e:
    print(f"[-] Ошибка при очистке: {e}")

test_songs = [
    (
        "Cozy Local Vibes 🌸", 
        "Blossom Player", 
        "E:/blossom-player/testsong/Frozy_Kompa.mp3", 
        "default_cover.png",
        "Это первая песня. Здесь играет локальное видео bg.webm!", 
        "bg.webm", 
        None
    ),
    (
        "Lofi Cafe Rain ☕", 
        "YouTube Stream", 
        "E:/blossom-player/testsong/Sumeru_OST_Forest.mp3", 
        "default_cover.png",
        "Это вторая песня. Видео должно загрузиться с YouTube!", 
        "https://www.youtube.com/watch?v=5wRWniH7sh8", 
        None
    )
]

for song in test_songs:
    try:
        cursor.execute("""
            INSERT INTO songs (title, artist, filepath, cover_path, lyrics, video_link, drive_file_id)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """, song)
        print(f"[+] Добавлена песня: {song[0]}")
    except Exception as e:
        print(f"[-] Не удалось добавить {song[0]}: {e}")

conn.commit()
conn.close()
print("[+] Настройка тестовой библиотеки завершена!")