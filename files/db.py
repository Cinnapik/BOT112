
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
    "updated_at TEXT"
]
REQUESTS_EXTRA_COLUMNS = [
    "category TEXT",
    "urgency INTEGER DEFAULT 0",
    "department TEXT"
]

async def _column_exists(db, table: str, column: str) -> bool:
    cur = await db.execute(f"PRAGMA table_info({table})")
    cols = await cur.fetchall()
    names = [c[1] for c in cols]
    return column in names

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # users
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                is_admin INTEGER DEFAULT 0
            )
        ''')
        # requests
        await db.execute(f'''
            CREATE TABLE IF NOT EXISTS requests (
                {", ".join(REQUESTS_BASE_COLUMNS)}
            )
        ''')
        # migrate extra columns
        for coldef in REQUESTS_EXTRA_COLUMNS:
            colname = coldef.split()[0]
            if not await _column_exists(db, "requests", colname):
                await db.execute(f"ALTER TABLE requests ADD COLUMN {coldef}")
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

# ---- USERS ----
async def create_user(user_id: int, username: Optional[str], first_name: Optional[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users(id, username, first_name) VALUES (?, ?, ?)",
            (user_id, username, first_name)
        )
        await db.execute(
            "UPDATE users SET username=?, first_name=? WHERE id=?",
            (username, first_name, user_id)
        )
        await db.commit()

async def set_admin(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_admin=1 WHERE id=?", (user_id,))
        await db.commit()

async def list_admins() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id FROM users WHERE is_admin=1")
        rows = await cur.fetchall()
        return [r[0] for r in rows]

async def list_all_user_ids() -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id FROM users")
        rows = await cur.fetchall()
        return [r[0] for r in rows]

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
            INSERT INTO requests (ticket, user_id, text, media_id, latitude, longitude, status, admin_comment, created_at, updated_at, category, urgency, department)
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
        if admin_comment is None:
            await db.execute("UPDATE requests SET status=?, updated_at=? WHERE ticket=?", (status, now, ticket))
        else:
            await db.execute("UPDATE requests SET status=?, admin_comment=?, updated_at=? WHERE ticket=?", (status, admin_comment, now, ticket))
        await db.execute(
            "INSERT INTO audit_log(ticket, actor_id, action, details, created_at) VALUES (?, NULL, ?, ?, ?)",
            (ticket, "status_change", status, now)
        )
        await db.commit()

async def assign_department(ticket: str, dept_key: str):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE requests SET department=?, updated_at=? WHERE ticket=?", (dept_key, now, ticket))
        await db.execute(
            "INSERT INTO audit_log(ticket, actor_id, action, details, created_at) VALUES (?, NULL, 'assign_department', ?, ?)",
            (ticket, dept_key, now)
        )
        await db.commit()

async def save_reply(ticket: str, admin_id: int, text: str):
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO replies(ticket, admin_id, text, created_at) VALUES (?, ?, ?, ?)", (ticket, admin_id, text, now))
        await db.commit()

async def list_replies(ticket: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            '''
            SELECT admin_id, text, created_at
            FROM replies
            WHERE ticket=?
            ORDER BY datetime(created_at)
            ''',
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
        cur = await db.execute("UPDATE requests SET status='Завершено' WHERE status IN ('Новый','В обработке')")
        await db.commit()
        return cur.rowcount

async def get_request_stats() -> Tuple[int,int,int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM requests")
        total = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM requests WHERE status='Завершено'")
        done = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM requests WHERE status='Отклонено'")
        declined = (await cur.fetchone())[0]
        return total, done, declined

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
