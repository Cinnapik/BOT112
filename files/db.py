# db.py
# Простые функции для работы с SQLite через aiosqlite.
# Таблицы: users (id, username, first_name, is_admin)
#          requests (id, ticket, user_id, text, media_path, latitude, longitude, status, admin_comment, created_at, updated_at)

import aiosqlite
import datetime
from config import DB_PATH

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            is_admin INTEGER DEFAULT 0
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket TEXT UNIQUE,
            user_id INTEGER,
            text TEXT,
            media_path TEXT,
            latitude REAL,
            longitude REAL,
            status TEXT DEFAULT 'Новый',
            admin_comment TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """)
        await db.commit()

async def create_user(user_id, username, first_name):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users(id, username, first_name) VALUES(?,?,?)",
                         (user_id, username, first_name))
        await db.commit()

async def set_admin(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users(id) VALUES(?)", (user_id,))
        await db.execute("UPDATE users SET is_admin=1 WHERE id=?", (user_id,))
        await db.commit()

async def list_admins():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id FROM users WHERE is_admin=1")
        rows = await cur.fetchall()
        return [r[0] for r in rows]

async def list_user_requests(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT ticket, text, status, created_at FROM requests WHERE user_id=? ORDER BY created_at DESC",
            (user_id,))
        return await cur.fetchall()

async def save_request(ticket, user_id, text, media_path, lat, lon):
    now = datetime.datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO requests(ticket,user_id,text,media_path,latitude,longitude,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?)
        """, (ticket, user_id, text, media_path, lat, lon, now, now))
        await db.commit()

async def get_request_by_ticket(ticket):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, ticket, user_id, text, media_path, latitude, longitude, status, admin_comment, created_at, updated_at FROM requests WHERE ticket=?",
            (ticket,))
        return await cur.fetchone()

async def update_status(ticket, status, admin_comment=None):
    now = datetime.datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        # Если status is None — оставляем прежний статус (чтобы не перезаписывать)
        if status is None:
            await db.execute("UPDATE requests SET admin_comment=?, updated_at=? WHERE ticket=?",
                             (admin_comment, now, ticket))
        else:
            await db.execute("UPDATE requests SET status=?, admin_comment=?, updated_at=? WHERE ticket=?",
                             (status, admin_comment, now, ticket))
        await db.commit()

async def list_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id FROM users")
        rows = await cur.fetchall()
        return [r[0] for r in rows]

async def export_requests(start_date, end_date):
    # start_date и end_date в формате YYYY-MM-DD
    s = start_date + "T00:00:00"
    e = end_date + "T23:59:59"
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, ticket, user_id, text, media_path, latitude, longitude, status, admin_comment, created_at, updated_at FROM requests WHERE created_at BETWEEN ? AND ? ORDER BY created_at",
            (s, e))
        return await cur.fetchall()
