import os
from PIL import Image

ASSETS_DIR = "assets"
COVERS_DIR = os.path.join(ASSETS_DIR, "covers")
DEFAULT_COVER = os.path.join(ASSETS_DIR, "default_cover.png")

def init_covers_dir():
    """Проверяет наличие необходимых папок и создает их"""
    if not os.path.exists(COVERS_DIR):
        os.makedirs(COVERS_DIR, exist_ok=True)
    
    # Автоматически генерируем красивую уютную заглушку, если её нет
    if not os.path.exists(DEFAULT_COVER):
        try:
            # Создаем нежно-розовый пастельный квадрат
            img = Image.new("RGB", (500, 500), color="#F3E5F5")
            img.save(DEFAULT_COVER)
        except Exception as e:
            print(f"Не удалось создать дефолтную обложку: {e}")

def save_and_resize_cover(source_path: str, song_id: int) -> str:
    """
    Обрезает пользовательскую картинку по центру до квадрата, 
    сжимает до 500x500 и сохраняет в ассеты. Возвращает готовый путь.
    """
    init_covers_dir()
    
    if not source_path or not os.path.exists(source_path):
        return DEFAULT_COVER

    # Сохраняем все обложки под ID песни, чтобы они не путались
    target_path = os.path.join(COVERS_DIR, f"cover_{song_id}.jpg")
    
    try:
        with Image.open(source_path) as img:
            width, height = img.size
            min_side = min(width, height)
            
            # Считаем координаты для кропа по центру
            left = (width - min_side) // 2
            top = (height - min_side) // 2
            right = (width + min_side) // 2
            bottom = (height + min_side) // 2
            
            img_cropped = img.crop((left, top, right, bottom))
            # Фильтр Resampling.LANCZOS отвечает за мягкое и качественное сжатие
            img_resized = img_cropped.resize((500, 500), Image.Resampling.LANCZOS)
            
            # Конвертируем в RGB (если у пользователя был прозрачный PNG, станет белым)
            if img_resized.mode in ("RGBA", "P"):
                img_resized = img_resized.convert("RGB")
                
            img_resized.save(target_path, "JPEG", quality=90)
            return target_path
            
    except Exception as e:
        print(f"Ошибка обработки изображения {source_path}: {e}")
        return DEFAULT_COVER