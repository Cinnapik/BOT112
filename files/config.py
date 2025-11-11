# config.py
# Простая конфигурация проекта.
# Секреты и токены берём из .env 
from pathlib import Path
import os
from dotenv import load_dotenv

# BASE_DIR = папка, где лежит этот файл (корень проекта)
BASE_DIR = Path(__file__).parent

# Загружаем переменные окружения из файла .env в корне
# (пример: BOT_TOKEN=xxx, ADMIN_SECRET=yyy)
load_dotenv(BASE_DIR / ".env")

# Токен телеграм-бота. Достаём из .env.
# Если .env не настроен — берём заглушку (чтоб не падало локально).
BOT_TOKEN = os.getenv("BOT_TOKEN", "replace_with_token")

# Секрет для выдачи прав администратора (команда /admin <код>)
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "secret123")

# Путь к файлу базы (SQLite) и папке для файлов
DB_PATH = str(BASE_DIR / "bot.db")
FILES_DIR = str(BASE_DIR / "files")


# ==== Маршрутизация по отделам ====
DEPARTMENTS = {
    "police": {"name": "Полиция", "tg_chat_id": -1003434460179},
    "fire": {"name": "Пожарная часть", "tg_chat_id": -1003434460179},
    "housing": {"name": "Отдел ЖКХ", "tg_chat_id": -1003434460179},
    "roads": {"name": "Дороги", "tg_chat_id": -1003434460179},
    "lighting": {"name": "Освещение", "tg_chat_id": -1003434460179},
    "water": {"name": "Водоканал", "tg_chat_id": -1003434460179},
    "gas": {"name": "Газовая служба", "tg_chat_id": -1003434460179},
    "heat": {"name": "Теплосети", "tg_chat_id": -1003434460179},
    "emergency": {"name": "Гражданская защита/МЧС", "tg_chat_id": -1003434460179},
}

CATEGORY_TO_DEPT = {
    "housing": "housing",
    "roads": "roads",
    "lighting": "lighting",
    "water": "water",
    "heat": "heat",
    "gas": "gas",
    "police": "police",
    "fire": "fire",
}

EMERGENCY_ROUTE = {
    "emerg_fire":  ["fire"],             
    "emerg_murder":["police"],            
    "emerg_bomb":  ["police"],            
    "emerg_flood": ["emergency"],         
    "emerg_uav":   ["police", "emergency"]
}

URGENT_KEYWORDS = {
    "пожар": "emerg_fire", "горит": "emerg_fire",
    "убийство": "emerg_murder", "человек убит": "emerg_murder", "нападение": "emerg_murder",
    "бомба": "emerg_bomb", "взрывчатка": "emerg_bomb", "заминир": "emerg_bomb",
    "наводнен": "emerg_flood", "потоп": "emerg_flood",
    "бпла": "emerg_uav", "дрон": "emerg_uav", "атак": "emerg_uav", "удар": "emerg_uav"
}
