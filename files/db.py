# db.py
# Здесь вся работа с базой данных (SQLite) через aiosqlite (async).
# Таблицы:
#  - users: кто писал боту и кто админ
#  - requests: заявки пользователей
#  - replies: ответы админов по заявкам

import datetime
from typing import List, Optional, Tuple
import aiosqlite

from config import DB_PATH

# Типы для удобства (не обязательно, но понятнее)
UserRow = Tuple[int, Optional[str], Optional[str], int]
RequestRow = Tuple[
    int,      # id
    str,      # ticket
    int,      # user_id
    str,      # text
    Optional[str],  # media_path
    Optional[float],# latitude
    Optional[float],# longitude
    str,      # status
    Optional[str],  # admin_comment
    str,      # created_at
    str       # updated_at
]


async def init_db():
    """Создаём таблицы, если их ещё нет. Вызывается при старте."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,         -- telegram user id
            username TEXT,
            first_name TEXT,
            is_admin INTEGER DEFAULT 0      -- 0 - обычный, 1 - админ
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket TEXT UNIQUE,             -- читаемый номер заявки (например T202501011234...)
            user_id INTEGER,                -- кто создал
            text TEXT,                      -- текст заявки
            media_path TEXT,                -- путь к файлу (если добавим медиа)
            latitude REAL,                  -- широта (если добавим гео)
            longitude REAL,                 -- долгота
            status TEXT DEFAULT 'Новый',    -- статус заявки
            admin_comment TEXT,             -- комментарий админа (если надо)
            created_at TEXT,                -- когда создана
            updated_at TEXT                 -- когда последний раз меняли
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket TEXT,                    -- к какой заявке относится ответ
            admin_id INTEGER,               -- кто ответил (tg id админа)
            text TEXT,                      -- текст ответа
            created_at TEXT                 -- когда ответили
        )
        """)

        await db.commit()


# ======= Пользователи =======

async def create_user(user_id: int, username: Optional[str], first_name: Optional[str]):
    """Добавляем пользователя (или игнорируем, если уже есть)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO users(id, username, first_name, is_admin)
            VALUES(?, ?, ?, 0)
        """, (user_id, username, first_name))
        await db.commit()


async def set_admin(user_id: int):
    """Выдать права админа пользователю."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_admin=1 WHERE id=?", (user_id,))
        await db.commit()


async def list_admins() -> List[int]:
    """Список chat_id админов (для рассылок)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id FROM users WHERE is_admin=1")
        rows = await cur.fetchall()
    return [r[0] for r in rows]


# ======= Заявки =======

async def save_request(
    ticket: str,
    user_id: int,
    text: str,
    media_path: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None
):
    """Сохраняем новую заявку в БД."""
    now = datetime.datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO requests(ticket, user_id, text, media_path, latitude, longitude, status, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, 'Новый', ?, ?)
        """, (ticket, user_id, text, media_path, lat, lon, now, now))
        await db.commit()


async def list_user_requests(user_id: int) -> List[RequestRow]:
    """Вернём заявки конкретного пользователя (сначала новые)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT id, ticket, user_id, text, media_path, latitude, longitude, status, admin_comment, created_at, updated_at
            FROM requests
            WHERE user_id=?
            ORDER BY datetime(created_at) DESC
        """, (user_id,))
        return await cur.fetchall()


async def get_request_by_ticket(ticket: str) -> Optional[RequestRow]:
    """Достаём одну заявку по её тикету (если есть)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT id, ticket, user_id, text, media_path, latitude, longitude, status, admin_comment, created_at, updated_at
            FROM requests
            WHERE ticket=?
            LIMIT 1
        """, (ticket,))
        row = await cur.fetchone()
        return row


async def update_status(ticket: str, status: Optional[str] = None, admin_comment: Optional[str] = None):
    """Меняем статус и/или комментарий админа. Если что-то None — оставляем старое."""
    now = datetime.datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        # COALESCE берёт первый NON-NULL аргумент → удобно для частичных обновлений
        await db.execute("""
            UPDATE requests
            SET status        = COALESCE(?, status),
                admin_comment = COALESCE(?, admin_comment),
                updated_at    = ?
            WHERE ticket=?
        """, (status, admin_comment, now, ticket))
        await db.commit()


async def export_requests(start_date_iso: str, end_date_iso: str) -> List[RequestRow]:
    """Выгрузка заявок за период (ISO-строки дат). Опционально для отчётов."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT id, ticket, user_id, text, media_path, latitude, longitude, status, admin_comment, created_at, updated_at
            FROM requests
            WHERE datetime(created_at) BETWEEN datetime(?) AND datetime(?)
            ORDER BY created_at
        """, (start_date_iso, end_date_iso))
        return await cur.fetchall()


# ======= Ответы админов =======

async def save_reply(ticket: str, admin_id: int, text: str):
    """Сохраняем ответ админа по заявке."""
    now = datetime.datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO replies(ticket, admin_id, text, created_at)
            VALUES(?, ?, ?, ?)
        """, (ticket, admin_id, text, now))
        await db.commit()


async def list_replies(ticket: str):
    """История ответов по тикету (можно показывать в карточке заявки)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT admin_id, text, created_at
            FROM replies
            WHERE ticket=?
            ORDER BY datetime(created_at)
        """, (ticket,))
        return await cur.fetchall()
