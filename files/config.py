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
