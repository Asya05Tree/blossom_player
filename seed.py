import os
import core.database as db
from core.models import Song
from core.covers import save_and_resize_cover

def add_test_song():
    print("🌸 Инициализация тестового трека...")
    db.init_db()
    
    # Ищем любой mp3 файл в твоей системе или создаем пустышку для теста
    # Обязательно замени путь ниже на реальный MP3 файл на твоем компьютере!
    test_mp3_path = r"E:\blossom-player\testsong\Frozy_Kompa.mp3" 
    
    if not os.path.exists(test_mp3_path):
        print(f"❌ Файл не найден по пути: {test_mp3_path}")
        print("Пожалуйста, открой seed.py и укажи точный путь к любому твоему MP3 файлу.")
        return

    # Создаем запись в декоративном стиле
    song = Song(
        title="✧ Cozy Morning Melody ✧",
        artist="❀ Blossom Lofi ❀",
        filepath=test_mp3_path,
        lyrics="This is a cozy place...\n🍃\nFeel the lo-fi vibes\n✨\nEnjoy your custom player!",
        video_link="https://www.youtube.com/watch?v=s7ygN1EBdl4&list=RDGMEMCMFH2exzjBeE_zAHHJOdxgVMs7ygN1EBdl4&start_radio=1"
    )
    
    # Добавляем в базу
    song_id = db.add_song(song)
    
    # Генерируем пастельную обложку по умолчанию
    final_cover = save_and_resize_cover("", song_id)
    
    # Обновляем путь к обложке в БД
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE songs SET cover_path = ? WHERE id = ?", (final_cover, song_id))
    conn.commit()
    conn.close()
    
    print("✅ Тестовый трек успешно добавлен в базу данных!")

if __name__ == "__main__":
    add_test_song()