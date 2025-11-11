# db.py — async слой БД (SQLite, aiosqlite)
import aiosqlite
from typing import List, Optional, Tuple
from datetime import datetime
from config import DB_PATH

# ---- SCHEMA ----
REQUESTS_BASE_COLUMNS = [
    "id INTEGER PRIMARY KEY AUTOINCREMENT",
    "ticket TEXT UNIQUE",
    "user_id INTEGER",
    "text TEXT",
    "media_id TEXT",
    "latitude REAL",
    "longitude REAL",
    "status TEXT",
    "admin_comment TEXT",
    "created_at TEXT",
    "updated_at TEXT",
    "category TEXT",
    "urgency INTEGER",
    "department TEXT"
]

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # requests
        await db.execute(f'''
            CREATE TABLE IF NOT EXISTS requests (
                {", ".join(REQUESTS_BASE_COLUMNS)}
            )
        ''')
        # replies
        await db.execute('''
            CREATE TABLE IF NOT EXISTS replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket TEXT,
                admin_id INTEGER,
                text TEXT,
                created_at TEXT
            )
        ''')
        # audit
        await db.execute('''
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket TEXT,
                actor_id INTEGER,
                action TEXT,
                details TEXT,
                created_at TEXT
            )
        ''')
        # departments
        await db.execute('''
            CREATE TABLE IF NOT EXISTS departments (
                key TEXT PRIMARY KEY,
                name TEXT,
                tg_chat_id INTEGER
            )
        ''')
        await db.commit()

# ---- USERS/ADMINS ----
async def create_user(user_id: int, username: Optional[str], first_name: Optional[str]):
    # на будущее можно сделать таблицу users, пока просто создаём записи через requests
    return True

async def list_admins() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        ''')
        await db.commit()
        cur = await db.execute("SELECT user_id FROM admins")
        rows = await cur.fetchall()
        return [r[0] for r in rows]

async def set_admin(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        ''')
        await db.execute("INSERT OR IGNORE INTO admins(user_id) VALUES(?)", (user_id,))
        await db.commit()

async def list_all_user_ids() -> List[int]:
    # простая выборка авторов из заявок
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT DISTINCT user_id FROM requests ORDER BY user_id")
        return [r[0] for r in await cur.fetchall()]

# ---- REQUESTS ----
async def save_request(
    ticket: str,
    user_id: int,
    text: str,
    media_path: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    category: Optional[str] = None,
    urgency: int = 0,
    department: Optional[str] = None
):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            '''
            INSERT INTO requests (ticket, user_id, text, media_id, latitude, 
            longitude, status, admin_comment, created_at, updated_at, category, urgency, department)
            VALUES (?, ?, ?, ?, ?, ?, 'Новый', NULL, ?, ?, ?, ?, ?)
            ''',
            (ticket, user_id, text, media_path, lat, lon, now, now, category, urgency, department)
        )
        await db.commit()

async def list_user_requests(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            '''
            SELECT id, ticket, user_id, text, media_id, latitude, longitude, status, admin_comment, created_at, updated_at, category, urgency, department
            FROM requests
            WHERE user_id=?
            ORDER BY datetime(created_at) DESC
            ''',
            (user_id,)
        )
        return await cur.fetchall()

async def get_request_by_ticket(ticket: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            '''
            SELECT id, ticket, user_id, text, media_id, latitude, longitude, status, admin_comment, created_at, updated_at, category, urgency, department
            FROM requests
            WHERE ticket=?
            ''',
            (ticket,)
        )
        return await cur.fetchone()

async def update_status(ticket: str, status: str, admin_comment: Optional[str] = None):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            '''
            UPDATE requests
            SET status=?, admin_comment=COALESCE(?, admin_comment), updated_at=?
            WHERE ticket=?
            ''',
            (status, admin_comment, now, ticket)
        )
        await db.commit()

async def save_reply(ticket: str, admin_id: int, text: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO replies(ticket, admin_id, text, created_at) VALUES(?,?,?,?)",
            (ticket, admin_id, text, datetime.utcnow().isoformat())
        )
        await db.commit()

async def list_replies(ticket: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, text, created_at FROM replies WHERE ticket=? ORDER BY datetime(created_at) ASC",
            (ticket,)
        )
        return await cur.fetchall()

async def export_requests(start_iso: str, end_iso: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            '''
            SELECT id, ticket, user_id, text, media_id, latitude, longitude, status, admin_comment, created_at, updated_at, category, urgency, department
            FROM requests
            WHERE datetime(created_at) BETWEEN datetime(?) AND datetime(?)
            ORDER BY datetime(created_at)
            ''',
            (start_iso, end_iso)
        )
        return await cur.fetchall()

async def cleanup_active_requests() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM replies WHERE ticket IN (SELECT ticket FROM requests WHERE status IN ('Новый','В обработке'))")
        cur = await db.execute("DELETE FROM requests WHERE status IN ('Новый','В обработке')")
        await db.commit()
        return cur.rowcount

async def cleanup_all_requests() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM replies")
        cur = await db.execute("DELETE FROM requests")
        await db.commit()
        return cur.rowcount

async def cleanup_before(date_yyyy_mm_dd: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM replies WHERE ticket IN (SELECT ticket FROM requests WHERE date(created_at) < date(?))", (date_yyyy_mm_dd,))
        cur = await db.execute("DELETE FROM requests WHERE date(created_at) < date(?)", (date_yyyy_mm_dd,))
        await db.commit()
        return cur.rowcount

async def bulk_close_active_requests() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("UPDATE requests SET status='Завершено', updated_at=? WHERE status IN ('Новый','В обработке')", (datetime.utcnow().isoformat(),))
        await db.commit()
        return cur.rowcount

async def get_request_stats() -> Tuple[int, int, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM requests")
        total = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM requests WHERE status='Завершено'")
        done = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM requests WHERE status='Отклонено'")
        declined = (await cur.fetchone())[0]
        return total, done, declined

# ---- DEPARTMENTS ----
async def assign_department(ticket: str, dept_key: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE requests SET department=?, updated_at=? WHERE ticket=?", (dept_key, datetime.utcnow().isoformat(), ticket))
        await db.commit()

async def upsert_department(key: str, name: str, tg_chat_id: Optional[int]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO departments(key,name,tg_chat_id) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET name=excluded.name, tg_chat_id=excluded.tg_chat_id",
            (key, name, tg_chat_id)
        )
        await db.commit()

async def list_departments():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT key, name, tg_chat_id FROM departments ORDER BY name")
        return await cur.fetchall()
