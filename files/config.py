from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "replace_with_token")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "secret123")
DB_PATH = str(BASE_DIR / "bot.db")
FILES_DIR = str(BASE_DIR / "files")

