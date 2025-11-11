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
    "police": {"name": "Полиция", "tg_chat_id": None},
    "fire": {"name": "Пожарная часть", "tg_chat_id": None},
    "housing": {"name": "Отдел ЖКХ", "tg_chat_id": None},
    "roads": {"name": "Дороги", "tg_chat_id": None},
    "lighting": {"name": "Освещение", "tg_chat_id": None},
    "water": {"name": "Водоканал", "tg_chat_id": None},
    "gas": {"name": "Газовая служба", "tg_chat_id": None},
    "heat": {"name": "Теплосети", "tg_chat_id": None},
    "emergency": {"name": "Гражданская защита/МЧС", "tg_chat_id": None},
}

CATEGORY_TO_DEPT = {
    "police": "police",
    "fire": "fire",
    "housing": "housing",
    "roads": "roads",
    "lighting": "lighting",
    "water": "water",
    "gas": "gas",
    "heat": "heat",
    "emerg_fire": "fire",
    "emerg_murder": "police",
    "emerg_bomb": "police",
    "emerg_flood": "emergency",
    "emerg_uav": "emergency",
}

EMERGENCY_ROUTE = {
    "emerg_fire": ["fire", "police", "emergency"],
    "emerg_murder": ["police", "emergency"],
    "emerg_bomb": ["police", "emergency", "fire"],
    "emerg_flood": ["emergency", "housing"],
    "emerg_uav": ["emergency", "police", "fire"],
}

URGENT_KEYWORDS = {
    "пожар": "emerg_fire", "горит": "emerg_fire",
    "убийство": "emerg_murder", "человек убит": "emerg_murder", "нападение": "emerg_murder",
    "бомба": "emerg_bomb", "взрывчатка": "emerg_bomb", "заминир": "emerg_bomb",
    "наводнен": "emerg_flood", "потоп": "emerg_flood",
    "бпла": "emerg_uav", "дрон": "emerg_uav", "атак": "emerg_uav", "удар": "emerg_uav"
}
