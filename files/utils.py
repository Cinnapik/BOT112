# utils.py
# Всякая полезная мелочь, чтобы не плодить код в main.py.

from datetime import datetime
from pathlib import Path
from config import FILES_DIR

def gen_ticket() -> str:
    """
    Генерируем удобный номер заявки по времени (UTC).
    Формат: TYYYYMMDDHHMMSSmmm (T + дата-время + миллисекунды)
    Пример: T20251110152312001
    """
    now = datetime.utcnow()
    return "T" + now.strftime("%Y%m%d%H%M%S") + f"{int(now.microsecond/1000):03d}"

def save_file_bytes(data: bytes, filename: str) -> str:
    """
    Сохраняем байты в папку ./files и возвращаем путь.
    Сейчас не используется, но место готово, если добавим медиа/документы.
    """
    folder = Path(FILES_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    with open(path, "wb") as f:
        f.write(data)
    return str(path)
