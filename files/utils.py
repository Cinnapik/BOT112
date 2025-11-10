# utils.py
# Небольшие утилиты: генерация номера заявки и сохранение файлов

import datetime
from pathlib import Path

BASE = Path(__file__).parent
FILES = BASE / "files"
FILES.mkdir(parents=True, exist_ok=True)

def gen_ticket():
    """
    Простая генерация тикета: T + YYYYMMDDHHMMSSmmm
    Возвращает строку.
    """
    now = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S%f")[:-3]
    return "T" + now

def save_file_bytes(data: bytes, filename: str) -> str:
    """
    Сохранить байты в папку files и вернуть путь к файлу (строка).
    Пример filename: "123_photo.jpg"
    """
    safe = filename.replace("/", "_").replace("\\", "_")
    path = FILES / safe
    with open(path, "wb") as f:
        f.write(data)
    return str(path)
