import sqlite3

def update_first_song_video():
    # Подключаемся к нашей базе данных
    conn = sqlite3.connect("blossom.db")
    cursor = conn.cursor()
    
    print("[*] Проверяю структуру базы данных...")
    
    # Хак: пробуем добавить колонку 'video', если её не существовало
    try:
        cursor.execute("ALTER TABLE songs ADD COLUMN video TEXT")
        print("[+] Колонка 'video' успешно добавлена в таблицу songs!")
    except sqlite3.OperationalError:
        # Если колонка уже была, sqlite выдаст ошибку, и мы её просто игнорируем
        print("[*] Колонка 'video' уже существует.")
    
    # Рабочая тестовая ссылка на YouTube
    test_video_url = "bg.mp4"
    
    # Обновляем все песни в базе данных этой ссылкой
    cursor.execute("UPDATE songs SET video = ?", (test_video_url,))
    
    conn.commit()
    print("[+] База данных успешно обновлена! Ссылка на видео записана.")
    conn.close()

if __name__ == "__main__":
    update_first_song_video()