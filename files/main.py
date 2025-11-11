# main.py — UI-polish edition + dialog stop button for admins
# — Эмодзи-меню и аккуратные карточки заявок (HTML)
# — Удобные кнопки "Подробнее" для пользователя
# — Подтверждения опасных операций через inline-кнопки
# — Хинты команд в меню Telegram (set_my_commands)
# — Мягкие подсказки в мастере создания заявки
# — Кнопка "🛑 Завершить диалог" в переписке админа с пользователем

import logging
import csv
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple

import aiosqlite
from telegram import (
    Update,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    BotCommand
)
from telegram.ext import (
    ApplicationBuilder, ContextTypes,
    CommandHandler, MessageHandler, CallbackQueryHandler,
    filters
)
from telegram.error import BadRequest

from config import (
    BOT_TOKEN, ADMIN_SECRET, FILES_DIR, DB_PATH,
    DEPARTMENTS, CATEGORY_TO_DEPT, EMERGENCY_ROUTE, URGENT_KEYWORDS
)
from utils import gen_ticket
from db import (
    init_db, create_user, set_admin, list_admins,
    save_request, list_user_requests, get_request_by_ticket, update_status,
    save_reply, list_replies, export_requests,
    cleanup_active_requests, cleanup_all_requests, cleanup_before, bulk_close_active_requests,
    list_all_user_ids, get_request_stats, assign_department
)

# ========= ЛОГИ =========
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s"
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.vendor.ptb_urllib3.urllib3").setLevel(logging.WARNING)
log = logging.getLogger("bot")

try:
    # Безопасная обёртка сокращения текста
    from textwrap import shorten as _shorten
    def s_short(s: str, width: int = 160, placeholder: str = "…") -> str:
        s = s or ""
        try:
            return _shorten(s, width=width, placeholder=placeholder)
        except Exception:
            return (s if len(s) <= width else s[:max(0, width - len(placeholder))] + placeholder)
except Exception:
    def s_short(s: str, width: int = 160, placeholder: str = "…") -> str:
        s = s or ""
        return (s if len(s) <= width else s[:max(0, width - len(placeholder))] + placeholder)


# ========= ГЛОБАЛЬНЫЕ ДИАЛОГИ =========
ACTIVE_DIALOGS_BY_TICKET = {}   # ticket -> {'admin_id': int, 'user_id': int}
ACTIVE_DIALOGS_BY_ADMIN = {}    # admin_id -> ticket
ACTIVE_DIALOGS_BY_USER = {}     # user_id -> ticket

# ========= КНОПКИ (обновлённые, с эмодзи) =========
BTN_CREATE = "📝 Создать обращение"
BTN_MY = "📂 Мои обращения"
BTN_HELP = "ℹ️ Справка"
BTN_ADMIN = "🛠️ Админ-меню"
BTN_CANCEL = "❌ Отмена"
BTN_CHOOSE_CATEGORY = "🏷️ Выбрать категорию"

# внутри админ-меню
BTN_ADMIN_NEW = "🆕 Последние заявки (5)"
BTN_ADMIN_ACTIVE = "🔥 Активные заявки"
BTN_ADMIN_FIND = "🔎 Открыть по тикету"
BTN_ADMIN_SERVICE = "📊 Сервис и отчёты"
BTN_BACK = "⬅️ В главное меню"

# подменю «Сервис/Отчёты»
BTN_EXPORT = "📤 Экспорт отчёта"
BTN_BROADCAST = "📣 Массовая рассылка"
BTN_STATS = "📈 Отчётность"
BTN_ADMIN_DANGER = "⚠️ Опасные операции"
BTN_SERVICE_BACK = "⬅️ Назад в админ-меню"

# подменю «ОПАСНО»
BTN_CLEAN_ACTIVE = "🗑️ Удалить активные…"
BTN_BULKCLOSE_ACTIVE = "✅ Закрыть активные…"
BTN_CLEAN_BEFORE = "🗓️ Удалить до даты…"
BTN_DANGER_BACK = "⬅️ Назад"

# ========= УТИЛИТЫ ФОРМАТИРОВАНИЯ =========
def normalize(text: Optional[str]) -> str:
    return (text or "").strip().lower()

def esc(s: object) -> str:
    """Простейший HTML-эскейп (достаточно для телеграма)."""
    t = str(s if s is not None else "")
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def status_badge(status: str) -> str:
    m = {
        "Новый": "🆕 Новый",
        "В обработке": "🛠️ В обработке",
        "Завершено": "✅ Завершено",
        "Отклонено": "⛔ Отклонено",
    }
    return m.get(status, esc(status))

def ticket_card_for_admin(row, dialog_info=None, last_reply=None) -> str:
    # row из SELECT ... requests: 14 полей
    _id, ticket, user_id, text, media, lat, lon, status, admin_comment, created, updated, category, urgency, department = row
    lines = []
    lines.append(f"<b>Заявка {esc(ticket)}</b>")
    lines.append(f"Автор: <code>{user_id}</code>")
    lines.append(f"Создана: <code>{esc(created)}</code>")
    lines.append(f"Статус: <b>{status_badge(status)}</b>")
    if category:
        lines.append(f"Категория: <code>{esc(category)}</code>")
    if department:
        lines.append(f"Направлена в отдел: <code>{esc(department)}</code>")
    if urgency:
        lines.append("⚠️ Отмечена как <b>экстренная</b>")
    if dialog_info:
        lines.append(f"Диалог: 🟢 активен (оператор <code>{dialog_info.get('admin_id')}</code>)")
    if lat is not None and lon is not None:
        lines.append(f"Координаты: <code>{lat:.6f}, {lon:.6f}</code>")
    if admin_comment:
        lines.append(f"Комментарий оператора: {esc(admin_comment)}")
    if last_reply:
        lines.append(f"\n<b>Последний ответ:</b> {esc(last_reply[1])}\n<code>{esc(last_reply[2])}</code>")
    lines.append("\n<b>Текст обращения:</b>")
    lines.append(esc(text))
    return "\n".join(lines)

def ticket_card_for_user(row, last_reply=None) -> str:
    _id, ticket, user_id, text, media, lat, lon, status, admin_comment, created, updated, category, urgency, department = row
    lines = []
    lines.append(f"<b>Заявка {esc(ticket)}</b>")
    lines.append(f"Создана: <code>{esc(created)}</code>")
    lines.append(f"Статус: <b>{status_badge(status)}</b>")
    if category:
        lines.append(f"Категория: <code>{esc(category)}</code>")
    if department:
        lines.append(f"Направлена в отдел: <code>{esc(department)}</code>")
    if urgency:
        lines.append("⚠️ Отмечена как <b>экстренная</b>")
    if lat is not None and lon is not None:
        lines.append(f"Координаты: <code>{lat:.6f}, {lon:.6f}</code>")
    if admin_comment:
        lines.append(f"Комментарий оператора: {esc(admin_comment)}")
    if last_reply:
        lines.append(f"\n<b>Последний ответ:</b> {esc(last_reply[1])}\n<code>{esc(last_reply[2])}</code>")
    lines.append("\n<b>Текст обращения:</b>")
    lines.append(esc(text))
    return "\n".join(lines)

# ========= КЛАВИАТУРЫ =========
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton(BTN_CREATE)],
     [KeyboardButton(BTN_MY)],
     [KeyboardButton(BTN_HELP)]],
    resize_keyboard=True
)

def make_keyboard(is_admin: bool) -> ReplyKeyboardMarkup:
    if not is_admin:
        return MAIN_KEYBOARD
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_CREATE)],
            [KeyboardButton(BTN_MY)],
            [KeyboardButton(BTN_HELP)],
            [KeyboardButton(BTN_ADMIN)],
        ],
        resize_keyboard=True
    )

def admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_ADMIN_NEW)],
            [KeyboardButton(BTN_ADMIN_ACTIVE)],
            [KeyboardButton(BTN_ADMIN_FIND)],
            [KeyboardButton(BTN_ADMIN_SERVICE)],
            [KeyboardButton(BTN_BACK)],
        ],
        resize_keyboard=True
    )

def service_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_EXPORT)],
            [KeyboardButton(BTN_BROADCAST)],
            [KeyboardButton(BTN_STATS)],
            [KeyboardButton(BTN_ADMIN_DANGER)],
            [KeyboardButton(BTN_SERVICE_BACK)],
        ],
        resize_keyboard=True
    )

def danger_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_CLEAN_ACTIVE)],
            [KeyboardButton(BTN_BULKCLOSE_ACTIVE)],
            [KeyboardButton(BTN_CLEAN_BEFORE)],
            [KeyboardButton(BTN_DANGER_BACK)],
        ],
        resize_keyboard=True
    )

def admin_dialog_inline_keyboard(ticket: str) -> InlineKeyboardMarkup:
    """Инлайн-кнопки для админа прямо в чате во время активного диалога."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 Завершить диалог", callback_data=f"dialog:stop:{ticket}")],
        [InlineKeyboardButton("📄 Открыть карточку", callback_data=f"open:{ticket}")]
    ])

def build_category_keyboard():
    rows = [
        [InlineKeyboardButton("🚨 Пожар", callback_data="cat:emerg_fire"),
         InlineKeyboardButton("🚨 Убийство/Нападение", callback_data="cat:emerg_murder")],
        [InlineKeyboardButton("🚨 Бомба/Заминировано", callback_data="cat:emerg_bomb"),
         InlineKeyboardButton("🚨 Наводнение/Потоп", callback_data="cat:emerg_flood")],
        [InlineKeyboardButton("🚨 Атака БПЛА", callback_data="cat:emerg_uav")],
        [InlineKeyboardButton("👮 Полиция", callback_data="cat:police"),
         InlineKeyboardButton("🔥 Пожарная часть", callback_data="cat:fire")],
        [InlineKeyboardButton("🏠 ЖКХ", callback_data="cat:housing"),
         InlineKeyboardButton("🛣️ Дороги", callback_data="cat:roads")],
        [InlineKeyboardButton("💡 Освещение", callback_data="cat:lighting"),
         InlineKeyboardButton("🚰 Водоканал", callback_data="cat:water")],
        [InlineKeyboardButton("🔥 Теплосети", callback_data="cat:heat"),
         InlineKeyboardButton("🧯 Газ", callback_data="cat:gas")],
    ]
    return InlineKeyboardMarkup(rows)

def build_create_flow_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📍 Прикрепить геолокацию", request_location=True)],
            [KeyboardButton(BTN_CANCEL)]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

# ========= МАЛЫЕ SQL-ХЭЛПЕРЫ ДЛЯ АДМИНА =========
async def admin_recent_requests(limit: int = 5) -> List[Tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT ticket, user_id, text, status, created_at
            FROM requests
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (limit,)
        )
        return await cur.fetchall()

async def admin_active_requests(limit: int = 20) -> List[Tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT ticket, user_id, text, status, created_at
            FROM requests
            WHERE status IN ('Новый', 'В обработке')
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (limit,)
        )
        return await cur.fetchall()

# ========= СЛУЖЕБНОЕ =========
def private_only(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.type == "private")

async def ensure_user_and_admin(update: Update) -> tuple[bool, ReplyKeyboardMarkup]:
    user = update.effective_user
    await create_user(user.id, user.username, user.first_name)
    admins = await list_admins()
    is_admin = user.id in admins
    return is_admin, make_keyboard(is_admin)

# ========= КОМАНДЫ =========
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private_only(update):
        await update.message.reply_text("Пожалуйста, напишите мне в личном чате.")
        return
    user = update.effective_user
    await create_user(user.id, user.username, user.first_name)
    admins = await list_admins()
    is_admin = user.id in admins
    await update.message.reply_text(
        "<b>Привет!</b> Я бот для обращений по ЖКХ/благоустройству.\n\n"
        "Нажмите «📝 Создать обращение», чтобы оставить заявку.\n"
        "«📂 Мои обращения» — ваши статусы и история.\n"
        "«ℹ️ Справка» — короткая инструкция.",
        reply_markup=make_keyboard(is_admin),
        parse_mode="HTML"
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private_only(update):
        await update.message.reply_text("Эта команда доступна только в личном чате.")
        return
    user = update.effective_user
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("Использование: <code>/admin &lt;секретный_код&gt;</code>", reply_markup=MAIN_KEYBOARD, parse_mode="HTML")
        return
    code = args[1].strip()
    if code == ADMIN_SECRET:
        await set_admin(user.id)
        await update.message.reply_text("Готово! У вас права администратора.", reply_markup=make_keyboard(True))
    else:
        await update.message.reply_text("Код неверный.", reply_markup=MAIN_KEYBOARD)

# ---- EXPORT ----
async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private_only(update):
        await update.message.reply_text("Эта команда доступна только в личном чате.")
        return
    user = update.effective_user
    admins = await list_admins()
    if user.id not in admins:
        await update.message.reply_text("Доступ запрещён.")
        return

    parts = (update.message.text or "").split()
    if len(parts) != 4 or parts[1] not in ("csv", "txt"):
        await update.message.reply_text(
            "Использование:\n<code>/export csv 2025-11-01 2025-11-10</code>\nили\n<code>/export txt 2025-11-01 2025-11-10</code>",
            reply_markup=service_keyboard(),
            parse_mode="HTML"
        )
        return

    fmt, d1, d2 = parts[1], parts[2], parts[3]
    try:
        start = datetime.strptime(d1, "%Y-%m-%d")
        end = datetime.strptime(d2, "%Y-%m-%d")
        end_iso = (end.replace(hour=23, minute=59, second=59)).isoformat()
        start_iso = start.isoformat()
    except ValueError:
        await update.message.reply_text("Неверный формат дат. Нужен YYYY-MM-DD YYYY-MM-DD.", reply_markup=service_keyboard())
        return

    rows = await export_requests(start_iso, end_iso)

    Path(FILES_DIR).mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    if fmt == "csv":
        filename = Path(FILES_DIR) / f"report_{d1}_{d2}_{ts}.csv"
        headers = ["id","ticket","user_id","text","media_id","latitude","longitude","status","admin_comment","created_at","updated_at","category","urgency","department"]
        with open(filename, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(headers)
            for r in rows:
                writer.writerow(list(r))
        await update.message.reply_document(document=str(filename), caption=f"CSV-отчёт за период {d1}—{d2}")
    else:
        filename = Path(FILES_DIR) / f"report_{d1}_{d2}_{ts}.txt"
        by_status = {}
        for r in rows:
            by_status[r[7]] = by_status.get(r[7], 0) + 1
        total = len(rows)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"Отчёт по обращениям за период {d1}—{d2}\n")
            f.write(f"Всего обращений: {total}\n")
            f.write("По статусам:\n")
            for st, cnt in by_status.items():
                f.write(f"  - {st}: {cnt}\n")
            f.write("\nСписок обращений:\n")
            for r in rows:
                _id,ticket,uid,text,media,lat,lon,status,comment,created,updated,category,urgency,department = r
                f.write(f"\n[{ticket}] {created} — {status}\n")
                f.write(f"Автор: {uid}\n")
                if category:
                    f.write(f"Категория: {category}\n")
                if department:
                    f.write(f"Отдел: {department}\n")
                if urgency:
                    f.write(f"Экстренность: да\n")
                if lat is not None and lon is not None:
                    f.write(f"Координаты: {lat:.6f}, {lon:.6f}\n")
                if media:
                    f.write(f"Медиа (file_id): {media}\n")
                if comment:
                    f.write(f"Комментарий админа: {comment}\n")
                f.write(f"Текст: {text}\n")
        await update.message.reply_document(document=str(filename), caption=f"TXT-отчёт за период {d1}—{d2}")

# ---- CLEANUP ----
async def cleanup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private_only(update):
        await update.message.reply_text("Эта команда доступна только в личном чате.")
        return
    user = update.effective_user
    admins = await list_admins()
    if user.id not in admins:
        await update.message.reply_text("Доступ запрещён.")
        return

    parts = (update.message.text or "").split()
    if len(parts) < 2:
        await update.message.reply_text(
            "Использование:\n"
            "/cleanup active\n"
            "/cleanup all\n"
            "/cleanup before 2025-10-01",
            reply_markup=danger_keyboard()
        )
        return

    sub = parts[1]
    if sub == "active":
        n = await cleanup_active_requests()
        await update.message.reply_text(f"Удалено активных заявок: {n}", reply_markup=service_keyboard())
    elif sub == "all":
        n = await cleanup_all_requests()
        await update.message.reply_text(f"Полностью очищено заявок: {n}", reply_markup=service_keyboard())
    elif sub == "before":
        if len(parts) != 3:
            await update.message.reply_text("Укажите дату: /cleanup before YYYY-MM-DD", reply_markup=danger_keyboard())
            return
        try:
            datetime.strptime(parts[2], "%Y-%m-%d")
        except ValueError:
            await update.message.reply_text("Неверный формат даты. Нужен YYYY-MM-DD", reply_markup=danger_keyboard())
            return
        n = await cleanup_before(parts[2])
        await update.message.reply_text(f"Удалено заявок до {parts[2]}: {n}", reply_markup=service_keyboard())
    else:
        await update.message.reply_text("Неизвестный параметр. active | all | before YYYY-MM-DD", reply_markup=danger_keyboard())

async def bulkclose_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not private_only(update):
        await update.message.reply_text("Эта команда доступна только в личном чате.")
        return
    user = update.effective_user
    admins = await list_admins()
    if user.id not in admins:
        await update.message.reply_text("Доступ запрещён.")
        return
    n = await bulk_close_active_requests()
    await update.message.reply_text(f"Закрыто активных заявок: {n}", reply_markup=service_keyboard())

# ---- BROADCAST ----
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда: /broadcast <текст>. Всегда показывает предпросмотр и просит подтверждение."""
    if not private_only(update):
        await update.message.reply_text("Эта команда доступна только в личном чате.")
        return
    user = update.effective_user
    admins = await list_admins()
    if user.id not in admins:
        await update.message.reply_text("Доступ запрещён.")
        return

    text = (update.message.text or "").split(maxsplit=1)
    if len(text) < 2 or not text[1].strip():
        await update.message.reply_text(
            "Использование: <code>/broadcast &lt;текст сообщения&gt;</code>\n"
            "Либо нажмите «📣 Массовая рассылка» в «📊 Сервис и отчёты».",
            reply_markup=service_keyboard(),
            parse_mode="HTML"
        )
        return

    payload = text[1].strip()
    context.user_data["broadcast_preview"] = payload

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Отправить всем", callback_data="broadcast:confirm")],
        [InlineKeyboardButton("✖ Отмена", callback_data="broadcast:cancel")]
    ])
    await update.message.reply_text(f"Предпросмотр рассылки:\n\n{esc(payload)}", reply_markup=kb, parse_mode="HTML")

# ========= СОЗДАНИЕ ЗАЯВКИ =========
async def create_ticket_and_notify(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    media_id: Optional[str] = None,
    media_kind: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    category: Optional[str] = None,
    urgency: int = 0
):
    user = update.effective_user
    ticket = gen_ticket()

    # Автодетекция экстренности по ключевым словам, если категория не выбрана
    if not category:
        low_text = (text or '').lower()
        for kw, cat in URGENT_KEYWORDS.items():
            if kw in low_text:
                category = cat
                urgency = 1
                break

    await save_request(
        ticket=ticket,
        user_id=user.id,
        text=text,
        media_path=media_id,
        lat=lat,
        lon=lon,
        category=category,
        urgency=urgency
    )

    prefix = "🚨 " if urgency else ""
    await update.message.reply_text(
        f"{prefix}🎟️ <b>Заявка принята!</b>\nВаш номер: <code>{esc(ticket)}</code>",
        reply_markup=(await ensure_user_and_admin(update))[1],
        parse_mode="HTML"
    )

    # Админы (для прямых уведомлений)
    admins = await list_admins()

    # Автоматическая маршрутизация по категории
    targets = []
    if category in EMERGENCY_ROUTE:
        targets = EMERGENCY_ROUTE[category]
    elif category in CATEGORY_TO_DEPT:
        targets = [CATEGORY_TO_DEPT[category]]

    for key in targets:
        try:
            await assign_department(ticket, key)
        except Exception:
            pass
        dept = DEPARTMENTS.get(key) or {}
        chat_id = dept.get("tg_chat_id")
        name = dept.get("name", key)
        try:
            if chat_id:
                if media_id and media_kind == "photo":
                    await context.bot.send_photo(chat_id=chat_id, photo=media_id, caption=f"Заявка {ticket} ({name})\n\n{text}")
                elif media_id and media_kind == "video":
                    await context.bot.send_video(chat_id=chat_id, video=media_id, caption=f"Заявка {ticket} ({name})\n\n{text}")
                elif media_id and media_kind == "document":
                    await context.bot.send_document(chat_id=chat_id, document=media_id, caption=f"Заявка {ticket} ({name})\n\n{text}")
                else:
                    await context.bot.send_message(chat_id=chat_id, text=f"Заявка {ticket} ({name})\n\n{text}")
                if lat is not None and lon is not None:
                    await context.bot.send_location(chat_id=chat_id, latitude=lat, longitude=lon)
        except Exception as e:
            log.warning("Не удалось отправить в отдел %s: %s", key, e)

    # Уведомим администраторов (лично), если назначенных нет/мало — они увидят и откроют
    caption = f"Новая заявка {ticket} от @{user.username or user.id}\n\n{text}"
    buttons = InlineKeyboardMarkup([[InlineKeyboardButton("Открыть заявку", callback_data=f"open:{ticket}")]])
    for admin_id in admins:
        try:
            if media_id and media_kind == "photo":
                await context.bot.send_photo(chat_id=admin_id, photo=media_id, caption=caption, reply_markup=buttons)
            elif media_id and media_kind == "video":
                await context.bot.send_video(chat_id=admin_id, video=media_id, caption=caption, reply_markup=buttons)
            elif media_id and media_kind == "document":
                await context.bot.send_document(chat_id=admin_id, document=media_id, caption=caption, reply_markup=buttons)
            else:
                await context.bot.send_message(chat_id=admin_id, text=caption, reply_markup=buttons)
            if lat is not None and lon is not None:
                await context.bot.send_location(chat_id=admin_id, latitude=lat, longitude=lon)
        except Exception as e:
            log.warning("Не удалось уведомить админа %s: %s", admin_id, e)

# ========= ОСНОВНОЙ ХЭНДЛЕР СООБЩЕНИЙ =========
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    # Зарегистрируем пользователя и узнаем его роль
    is_admin, kb = await ensure_user_and_admin(update)

    # ===== Сообщения АДМИНА при активном диалоге =====
    if is_admin and private_only(update):
        admin_id = update.effective_user.id
        ticket = ACTIVE_DIALOGS_BY_ADMIN.get(admin_id)
        if ticket:
            req = await get_request_by_ticket(ticket)
            if not req:
                ACTIVE_DIALOGS_BY_ADMIN.pop(admin_id, None)
                ACTIVE_DIALOGS_BY_TICKET.pop(ticket, None)
            else:
                _, t, author_id, *_ = req
                try:
                    if update.message.text:
                        await context.bot.send_message(
                            chat_id=author_id,
                            text=f"Сообщение от оператора по заявке {t}:\n\n{update.message.text}"
                        )
                        await save_reply(t, admin_id, update.message.text)
                    elif update.message.photo:
                        fid = update.message.photo[-1].file_id
                        cap = update.message.caption or ""
                        await context.bot.send_photo(chat_id=author_id, photo=fid,
                                                     caption=f"От оператора (заявка {t}):\n{cap}")
                        if cap:
                            await save_reply(t, admin_id, cap)
                    elif update.message.video:
                        fid = update.message.video.file_id
                        cap = update.message.caption or ""
                        await context.bot.send_video(chat_id=author_id, video=fid,
                                                     caption=f"От оператора (заявка {t}):\n{cap}")
                        if cap:
                            await save_reply(t, admin_id, cap)
                    elif update.message.document:
                        fid = update.message.document.file_id
                        cap = update.message.caption or ""
                        await context.bot.send_document(chat_id=author_id, document=fid,
                                                        caption=f"От оператора (заявка {t}):\n{cap}")
                        if cap:
                            await save_reply(t, admin_id, cap)
                    else:
                        await update.message.reply_text(
                            "Тип сообщения не поддержан в диалоге.",
                            reply_markup=admin_dialog_inline_keyboard(ticket)
                        )
                        return
                    await update.message.reply_text(
                        "Сообщение отправлено пользователю.",
                        reply_markup=admin_dialog_inline_keyboard(ticket)
                    )
                except Exception as e:
                    log.warning("Не удалось отправить автору: %s", e)
                    await update.message.reply_text(
                        "Не удалось отправить сообщение пользователю.",
                        reply_markup=admin_dialog_inline_keyboard(ticket)
                    )
                return

    # ===== Сообщения ПОЛЬЗОВАТЕЛЯ при активном диалоге =====
    if (not is_admin) and private_only(update):
        user_id = update.effective_user.id
        ticket = ACTIVE_DIALOGS_BY_USER.get(user_id)
        if ticket:
            info = ACTIVE_DIALOGS_BY_TICKET.get(ticket)
            admin_id = info["admin_id"] if info else None
            if admin_id:
                try:
                    if update.message.text:
                        await context.bot.send_message(
                            chat_id=admin_id,
                            text=f"Сообщение от пользователя по заявке {ticket}:\n\n{update.message.text}"
                        )
                    elif update.message.photo:
                        fid = update.message.photo[-1].file_id
                        cap = update.message.caption or ""
                        await context.bot.send_photo(chat_id=admin_id, photo=fid,
                                                     caption=f"От пользователя (заявка {ticket}):\n{cap}")
                    elif update.message.video:
                        fid = update.message.video.file_id
                        cap = update.message.caption or ""
                        await context.bot.send_video(chat_id=admin_id, video=fid,
                                                     caption=f"От пользователя (заявка {ticket}):\n{cap}")
                    elif update.message.document:
                        fid = update.message.document.file_id
                        cap = update.message.caption or ""
                        await context.bot.send_document(chat_id=admin_id, document=fid,
                                                        caption=f"От пользователя (заявка {ticket}):\n{cap}")
                    else:
                        await update.message.reply_text("Сообщение получено. Напишите текст или приложите файл.")
                        return
                    await update.message.reply_text("Сообщение отправлено оператору.")
                except Exception as e:
                    log.warning("Не удалось отправить админу: %s", e)
                    await update.message.reply_text("Не удалось доставить сообщение оператору.")
                return

    if not private_only(update):
        await update.message.reply_text("Обращения принимаются только в личном чате. Напишите мне напрямую.")
        return

    text = update.message.text or ""
    low = normalize(text)

    # ожидание ввода тикета (админ)
    if context.user_data.get("expect_ticket_to_open"):
        context.user_data.pop("expect_ticket_to_open", None)
        ticket = text.strip()
        row = await get_request_by_ticket(ticket)
        if not row:
            await update.message.reply_text(f"Заявка {ticket} не найдена.", reply_markup=admin_keyboard() if is_admin else kb)
            return

        replies = await list_replies(ticket)
        last = replies[-1] if replies else None
        dialog_info = ACTIVE_DIALOGS_BY_TICKET.get(ticket)
        msg = ticket_card_for_admin(row, dialog_info=dialog_info, last_reply=last)
        # Кнопки управления
        if row[7] in ("Завершено", "Отклонено"):
            buttons = InlineKeyboardMarkup([[InlineKeyboardButton("Ответить пользователю", callback_data=f"reply:{ticket}")]])
        else:
            if dialog_info and dialog_info.get("admin_id") == update.effective_user.id:
                dialog_row = [InlineKeyboardButton("Завершить диалог", callback_data=f"dialog:stop:{ticket}")]
            elif dialog_info:
                dialog_row = [InlineKeyboardButton("Диалог ведёт другой оператор", callback_data=f"noop:{ticket}")]
            else:
                dialog_row = [InlineKeyboardButton("Начать диалог", callback_data=f"dialog:start:{ticket}")]
            buttons = InlineKeyboardMarkup([
                dialog_row,
                [InlineKeyboardButton("Ответить (разово)", callback_data=f"reply:{ticket}")],
                [InlineKeyboardButton("Направить в отдел", callback_data=f"route_menu:{ticket}")],
                [InlineKeyboardButton("Завершено", callback_data=f"status:{ticket}:Завершено"),
                 InlineKeyboardButton("Отклонено", callback_data=f"status:{ticket}:Отклонено")]
            ])
        await update.message.reply_text(msg, reply_markup=buttons, parse_mode="HTML")
        return

    # режим разового ответа оператором (без диалога)
    if context.user_data.get("reply_to_ticket"):
        if is_admin:
            ticket = context.user_data.pop("reply_to_ticket")
            req = await get_request_by_ticket(ticket)
            if not req:
                await update.message.reply_text("Заявка не найдена.", reply_markup=kb)
                return
            _, ticket, author_id, *_ = req
            await save_reply(ticket, update.effective_user.id, text)
            try:
                await context.bot.send_message(chat_id=author_id, text=f"Ответ по вашей заявке {ticket}:\n\n{text}")
            except Exception as e:
                log.warning("Не удалось отправить ответ пользователю: %s", e)
            await update.message.reply_text(f"Ответ отправлен пользователю (заявка {ticket}).", reply_markup=kb)
            return
        else:
            context.user_data.pop("reply_to_ticket", None)

    # ожидание даты для опасного удаления
    if is_admin and context.user_data.get("expect_cleanup_date"):
        context.user_data.pop("expect_cleanup_date", None)
        date_str = text.strip()
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            await update.message.reply_text("Неверный формат. Введите дату как YYYY-MM-DD.", reply_markup=danger_keyboard())
            return
        n = await cleanup_before(date_str)
        await update.message.reply_text(f"Удалено заявок до {date_str}: {n}", reply_markup=service_keyboard())
        return

    # ожидание параметров экспорта
    if is_admin and context.user_data.get("expect_export_params"):
        context.user_data.pop("expect_export_params", None)
        parts = text.split()
        if len(parts) != 3 or parts[0] not in ("csv", "txt"):
            await update.message.reply_text("Формат: csv|txt YYYY-MM-DD YYYY-MM-DD", reply_markup=service_keyboard())
            return
        fake_cmd = f"/export {parts[0]} {parts[1]} {parts[2]}"
        update.message.text = fake_cmd
        await export_command(update, context)
        return

    # ожидание текста для рассылки
    if is_admin and context.user_data.get("expect_broadcast_text"):
        context.user_data.pop("expect_broadcast_text", None)
        payload = text.strip()
        if not payload:
            await update.message.reply_text("Пустое сообщение. Отправьте текст для рассылки.", reply_markup=service_keyboard())
            return
        context.user_data["broadcast_preview"] = payload
        kb_inline = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Отправить всем", callback_data="broadcast:confirm")],
            [InlineKeyboardButton("✖ Отмена", callback_data="broadcast:cancel")]
        ])
        await update.message.reply_text(f"Предпросмотр рассылки:\n\n{esc(payload)}", reply_markup=kb_inline, parse_mode="HTML")
        return

    # ====== ПРОЦЕСС СОЗДАНИЯ ЗАЯВКИ ======
    if context.user_data.get("awaiting_request"):
        if update.message.location:
            context.user_data["pending_lat"] = update.message.location.latitude
            context.user_data["pending_lon"] = update.message.location.longitude
            await update.message.reply_text(
                "📍 Геолокация добавлена.\n"
                "Теперь отправьте <b>текст проблемы</b> одним сообщением. "
                "Можно приложить фото/видео с подписью.",
                reply_markup=build_create_flow_keyboard(),
                parse_mode="HTML"
            )
            return

        media_id = None
        media_kind = None
        if update.message.photo:
            media_id = update.message.photo[-1].file_id
            media_kind = "photo"
            if update.message.caption:
                text = update.message.caption
        elif update.message.video:
            media_id = update.message.video.file_id
            media_kind = "video"
            if update.message.caption:
                text = update.message.caption
        elif update.message.document:
            media_id = update.message.document.file_id
            media_kind = "document"
            if update.message.caption:
                text = update.message.caption

        if media_id and not text:
            context.user_data["pending_media_id"] = media_id
            context.user_data["pending_media_kind"] = media_kind
            await update.message.reply_text("📎 Медиа получено. Теперь, пожалуйста, опишите проблему <b>текстом</b>.", parse_mode="HTML")
            return

        if low in ("отмена", normalize(BTN_CANCEL)):
            context.user_data.pop("awaiting_request", None)
            context.user_data.pop("pending_media_id", None)
            context.user_data.pop("pending_media_kind", None)
            context.user_data.pop("pending_lat", None)
            context.user_data.pop("pending_lon", None)
            await update.message.reply_text("Создание заявки отменено.", reply_markup=(await ensure_user_and_admin(update))[1])
            return

        if text:
            lat = context.user_data.pop("pending_lat", None)
            lon = context.user_data.pop("pending_lon", None)
            media_id = media_id or context.user_data.pop("pending_media_id", None)
            media_kind = media_kind or context.user_data.pop("pending_media_kind", None)
            context.user_data.pop("awaiting_request", None)

            cat = context.user_data.pop("pending_category", None)
            urgent = 1 if context.user_data.pop("pending_urgent", 0) else 0
            await create_ticket_and_notify(
                update, context, text=text,
                media_id=media_id, media_kind=media_kind,
                lat=lat, lon=lon,
                category=cat, urgency=urgent
            )
            return

        await update.message.reply_text(
            "Опишите проблему <b>текстом одним сообщением</b>. "
            "Можно приложить фото/видео с подписью и/или отправить геолокацию.",
            reply_markup=build_create_flow_keyboard(),
            parse_mode="HTML"
        )
        return

    # ====== ОБРАБОТКА КНОПОК ГЛАВНОГО МЕНЮ ======
    if low == normalize(BTN_CREATE):
        context.user_data["awaiting_request"] = True
        context.user_data.pop("pending_category", None)
        context.user_data.pop("pending_urgent", None)
        kb_inline = build_category_keyboard()
        await update.message.reply_text(
            "<b>Шаг 1 из 3.</b>\nВыберите <b>категорию</b> проблемы (можно экстренную):",
            reply_markup=kb_inline,
            parse_mode="HTML"
        )
        return

    if low == normalize(BTN_MY):
        rows = await list_user_requests(update.effective_user.id)
        if not rows:
            await update.message.reply_text("У вас пока нет заявок.", reply_markup=kb)
            return
        # Покажем аккуратный список + кнопки «Подробнее»
        for r in rows[:10]:
            _id, ticket, _uid, rtext, _mp, _lat, _lon, status, _cmt, created, _upd, _cat, _urg, _dept = r
            snippet = s_short(rtext, width=160, placeholder="…")
            msg = (
                f"<b>{esc(ticket)}</b> — {status_badge(status)}\n"
                f"<i>{esc(created)}</i>\n"
                f"{esc(snippet)}"
            )
            buttons = InlineKeyboardMarkup([[InlineKeyboardButton("📄 Подробнее", callback_data=f"openuser:{ticket}")]])
            await update.message.reply_text(msg, reply_markup=buttons, parse_mode="HTML")
        await update.message.reply_text("Показаны последние заявки.", reply_markup=kb)
        return

    if low == normalize(BTN_HELP):
        await update.message.reply_text(
            "<b>Как пользоваться ботом</b>\n"
            "1) «📝 Создать обращение» — текст одним сообщением (можно фото/видео с подписью и геолокацию).\n"
            "2) После отправки бот пришлёт номер заявки. Оператор включит диалог при необходимости.\n"
            "3) «📂 Мои обращения» — список ваших заявок со статусами и кнопкой «Подробнее».",
            reply_markup=kb,
            parse_mode="HTML"
        )
        return

    # === АДМИН-МЕНЮ ===
    if is_admin and low == normalize(BTN_ADMIN):
        await update.message.reply_text("Админ-меню:", reply_markup=admin_keyboard())
        return

    if is_admin and low == normalize(BTN_ADMIN_NEW):
        rows = await admin_recent_requests(limit=5)
        if not rows:
            await update.message.reply_text("Заявок пока нет.", reply_markup=admin_keyboard())
            return
        for ticket, uid, rtext, status, created in rows:
            snippet = s_short(rtext, width=220, placeholder="…")
            dial = " 🟢 Диалог" if ticket in ACTIVE_DIALOGS_BY_TICKET else ""
            msg = f"<b>Заявка {esc(ticket)}</b>\nСТАТУС: {status_badge(status)}{dial}\nАвтор: <code>{uid}</code>\nСоздана: <code>{esc(created)}</code>\n\n{esc(snippet)}"
            buttons = InlineKeyboardMarkup([[InlineKeyboardButton("Открыть", callback_data=f"open:{ticket}")]])
            await update.message.reply_text(msg, reply_markup=buttons, parse_mode="HTML")
        await update.message.reply_text("Готово.", reply_markup=admin_keyboard())
        return

    if is_admin and low == normalize(BTN_ADMIN_ACTIVE):
        rows = await admin_active_requests(limit=20)
        if not rows:
            await update.message.reply_text("Активных заявок нет.", reply_markup=admin_keyboard())
            return
        for ticket, uid, rtext, status, created in rows:
            snippet = s_short(rtext, width=220, placeholder="…")
            dial = " 🟢 Диалог" if ticket in ACTIVE_DIALOGS_BY_TICKET else ""
            msg = f"<b>Заявка {esc(ticket)}</b>\nСТАТУС: {status_badge(status)}{dial}\nАвтор: <code>{uid}</code>\nСоздана: <code>{esc(created)}</code>\n\n{esc(snippet)}"
            buttons = InlineKeyboardMarkup([[InlineKeyboardButton("Открыть", callback_data=f"open:{ticket}")]])
            await update.message.reply_text(msg, reply_markup=buttons, parse_mode="HTML")
        await update.message.reply_text("Готово.", reply_markup=admin_keyboard())
        return

    if is_admin and low == normalize(BTN_ADMIN_FIND):
        context.user_data["expect_ticket_to_open"] = True
        await update.message.reply_text("Введите номер тикета (например: <code>T20251110152312001</code>):", reply_markup=admin_keyboard(), parse_mode="HTML")
        return

    # --- Подменю «Сервис/Отчёты» ---
    if is_admin and low == normalize(BTN_ADMIN_SERVICE):
        await update.message.reply_text("Сервис и отчётность:", reply_markup=service_keyboard())
        return

    if is_admin and low == normalize(BTN_SERVICE_BACK):
        await update.message.reply_text("Возврат в админ-меню.", reply_markup=admin_keyboard())
        return

    if is_admin and low == normalize(BTN_EXPORT):
        context.user_data["expect_export_params"] = True
        await update.message.reply_text(
            "Экспорт отчёта.\nОтправьте: <code>csv|txt YYYY-MM-DD YYYY-MM-DD</code>\nНапример: <code>csv 2025-11-01 2025-11-10</code>",
            reply_markup=service_keyboard(),
            parse_mode="HTML"
        )
        return

    if is_admin and low == normalize(BTN_BROADCAST):
        context.user_data["expect_broadcast_text"] = True
        await update.message.reply_text(
            "Массовая рассылка.\nОтправьте ТЕКСТ сообщения — будет предпросмотр и подтверждение.",
            reply_markup=service_keyboard()
        )
        return

    if is_admin and low == normalize(BTN_STATS):
        total, done, declined = await get_request_stats()
        await update.message.reply_text(
            f"Отчётность:\n"
            f"— Всего заявок: {total}\n"
            f"— Завершено: {done}\n"
            f"— Отклонено: {declined}",
            reply_markup=service_keyboard()
        )
        return

    if is_admin and low == normalize(BTN_ADMIN_DANGER):
        await update.message.reply_text("⚠️ Опасные операции. Будьте осторожны.", reply_markup=danger_keyboard())
        return

    # --- Подменю «ОПАСНО» ---
    if is_admin and low == normalize(BTN_CLEAN_ACTIVE):
        kb_inline = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, удалить активные", callback_data="danger:clean_active:confirm")],
            [InlineKeyboardButton("✖ Отмена", callback_data="danger:cancel")]
        ])
        await update.message.reply_text("Удалить <b>все активные</b> заявки (Новый/В обработке)?", reply_markup=kb_inline, parse_mode="HTML")
        return

    if is_admin and low == normalize(BTN_BULKCLOSE_ACTIVE):
        kb_inline = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Да, закрыть активные", callback_data="danger:bulkclose_active:confirm")],
            [InlineKeyboardButton("✖ Отмена", callback_data="danger:cancel")]
        ])
        await update.message.reply_text("Перевести <b>все активные</b> заявки в статус «Завершено»?", reply_markup=kb_inline, parse_mode="HTML")
        return

    if is_admin and low == normalize(BTN_CLEAN_BEFORE):
        context.user_data["expect_cleanup_date"] = True
        await update.message.reply_text(
            "Введите дату в формате YYYY-MM-DD (всё, что <b>строго раньше</b> этой даты, будет удалено):",
            reply_markup=danger_keyboard(),
            parse_mode="HTML"
        )
        return

    if is_admin and low == normalize(BTN_DANGER_BACK):
        await update.message.reply_text("Возврат в «Сервис и отчёты».", reply_markup=service_keyboard())
        return

    if is_admin and low == normalize(BTN_BACK):
        await update.message.reply_text("Возврат в главное меню.", reply_markup=kb)
        return

    await update.message.reply_text(
        "Нажмите «📝 Создать обращение» чтобы оставить заявку, "
        "или «📂 Мои обращения» чтобы посмотреть статусы.",
        reply_markup=kb
    )

# ========= CALLBACK-КНОПКИ =========
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    try:
        await query.answer()
    except BadRequest:
        pass

    data = (query.data or "").strip()
    user = update.effective_user

    # --- Пользователь: открыть свою карточку заявки ---
    if data.startswith("openuser:"):
        ticket = data.split(":", 1)[1]
        row = await get_request_by_ticket(ticket)
        if not row:
            await context.bot.send_message(chat_id=query.message.chat_id, text="Заявка не найдена.")
            return
        # Проверим, что это его заявка
        if row[2] != user.id:
            await context.bot.send_message(chat_id=query.message.chat_id, text="Это не ваша заявка.")
            return
        replies = await list_replies(ticket)
        last = replies[-1] if replies else None
        msg = ticket_card_for_user(row, last_reply=last)
        try:
            await query.edit_message_text(msg, parse_mode="HTML")
        except BadRequest:
            await context.bot.send_message(chat_id=query.message.chat_id, text=msg, parse_mode="HTML")
        return

    # --- Выбор категории пользователем ---
    if data.startswith("cat:"):
        key = data.split(":", 1)[1]
        context.user_data["pending_category"] = key
        context.user_data["pending_urgent"] = 1 if key.startswith("emerg_") else 0
        try:
            await query.edit_message_text(
                f"Категория установлена: <b>{key}</b>\nТеперь отправьте текст проблемы одним сообщением. Можно прикрепить фото/видео и геолокацию.",
                parse_mode="HTML"
            )
        except BadRequest:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"Категория установлена: {key}. Теперь отправьте текст проблемы одним сообщением."
            )
        return

    # --- Меню направить в отдел (админ) ---
    if data.startswith("route_menu:"):
        ticket = data.split(":", 1)[1]
        rows = []
        pair = []
        for key, d in DEPARTMENTS.items():
            name = d.get("name", key)
            pair.append(InlineKeyboardButton(name, callback_data=f"route:{ticket}:{key}"))
            if len(pair) == 2:
                rows.append(pair)
                pair = []
        if pair:
            rows.append(pair)
        rows.append([InlineKeyboardButton("Отмена", callback_data=f"noop:{ticket}")])
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(rows))
        return

    # --- Направление в отдел (админ) ---
    if data.startswith("route:"):
        _, ticket, key = data.split(":", 2)
        await assign_department(ticket, key)
        dept = DEPARTMENTS.get(key) or {}
        name = dept.get("name", key)
        chat_id = dept.get("tg_chat_id")
        row = await get_request_by_ticket(ticket)
        if row:
            _id, t, author_id, text, media_id, lat, lon, *_ = row
            try:
                if chat_id:
                    if media_id:
                        try:
                            await context.bot.send_photo(chat_id=chat_id, photo=media_id, caption=f"Заявка {t} ({name})\n\n{text}")
                        except Exception:
                            await context.bot.send_message(chat_id=chat_id, text=f"Заявка {t} ({name})\n\n{text}")
                    else:
                        await context.bot.send_message(chat_id=chat_id, text=f"Заявка {t} ({name})\n\n{text}")
                    if lat is not None and lon is not None:
                        await context.bot.send_location(chat_id=chat_id, latitude=lat, longitude=lon)
            except Exception as e:
                log.warning("Не удалось отправить в отдел %s: %s", key, e)
        try:
            await query.edit_message_text(f"Заявка {ticket} направлена в отдел: {name}")
        except BadRequest:
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"Заявка {ticket} направлена в отдел: {name}")
        return

    # --- Дальше: только админам ---
    admins = await list_admins()
    if user.id not in admins:
        await context.bot.send_message(chat_id=query.message.chat_id, text="Доступ запрещён.")
        return

    # --- Рассылка: подтверждение/отмена ---
    if data == "broadcast:confirm":
        payload = context.user_data.get("broadcast_preview")
        if not payload:
            await context.bot.send_message(chat_id=query.message.chat_id, text="Нет текста для рассылки.")
            return
        user_ids = await list_all_user_ids()
        ok = 0
        fail = 0
        for uid in user_ids:
            try:
                await context.bot.send_message(chat_id=uid, text=payload)
                ok += 1
            except Exception:
                fail += 1
        context.user_data.pop("broadcast_preview", None)
        try:
            await query.edit_message_text(f"Рассылка завершена.\nДоставлено: {ok}\nОшибок: {fail}")
        except BadRequest:
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"Рассылка завершена. Доставлено: {ok}, ошибок: {fail}")
        return

    if data == "broadcast:cancel":
        context.user_data.pop("broadcast_preview", None)
        try:
            await query.edit_message_text("Рассылка отменена.")
        except BadRequest:
            await context.bot.send_message(chat_id=query.message.chat_id, text="Рассылка отменена.")
        return

    # --- Опасные операции: подтверждения ---
    if data == "danger:clean_active:confirm":
        n = await cleanup_active_requests()
        try:
            await query.edit_message_text(f"Удалено активных заявок: {n}")
        except BadRequest:
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"Удалено активных заявок: {n}")
        return

    if data == "danger:bulkclose_active:confirm":
        n = await bulk_close_active_requests()
        try:
            await query.edit_message_text(f"Закрыто активных заявок: {n}")
        except BadRequest:
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"Закрыто активных заявок: {n}")
        return

    if data == "danger:cancel":
        try:
            await query.edit_message_text("Операция отменена.")
        except BadRequest:
            await context.bot.send_message(chat_id=query.message.chat_id, text="Операция отменена.")
        return

    # --- Открыть карточку заявки (админ) ---
    if data.startswith("open:"):
        ticket = data.split(":", 1)[1]
        row = await get_request_by_ticket(ticket)
        if not row:
            await context.bot.send_message(chat_id=query.message.chat_id, text="Заявка не найдена.")
            return

        replies = await list_replies(ticket)
        last = replies[-1] if replies else None
        dialog_info = ACTIVE_DIALOGS_BY_TICKET.get(ticket)
        msg = ticket_card_for_admin(row, dialog_info=dialog_info, last_reply=last)

        if row[7] in ("Завершено", "Отклонено"):
            buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton("Ответить пользователю", callback_data=f"reply:{ticket}")]
            ])
        else:
            if dialog_info and dialog_info.get("admin_id") == update.effective_user.id:
                dialog_row = [InlineKeyboardButton("Завершить диалог", callback_data=f"dialog:stop:{ticket}")]
            elif dialog_info:
                dialog_row = [InlineKeyboardButton("Диалог ведёт другой оператор", callback_data=f"noop:{ticket}")]
            else:
                dialog_row = [InlineKeyboardButton("Начать диалог", callback_data=f"dialog:start:{ticket}")]
            buttons = InlineKeyboardMarkup([
                dialog_row,
                [InlineKeyboardButton("Ответить (разово)", callback_data=f"reply:{ticket}")],
                [InlineKeyboardButton("Направить в отдел", callback_data=f"route_menu:{ticket}")],
                [InlineKeyboardButton("Завершено", callback_data=f"status:{ticket}:Завершено"),
                 InlineKeyboardButton("Отклонено", callback_data=f"status:{ticket}:Отклонено")]
            ])

        msg_obj = query.message
        try:
            if msg_obj and (msg_obj.photo or msg_obj.video or msg_obj.document):
                await msg_obj.reply_text(msg, reply_markup=buttons, parse_mode="HTML")
            else:
                await query.edit_message_text(msg, reply_markup=buttons, parse_mode="HTML")
        except BadRequest:
            await context.bot.send_message(chat_id=query.message.chat_id, text=msg, reply_markup=buttons, parse_mode="HTML")
        return

    # --- ДИАЛОГ: старт/стоп ---
    if data.startswith("dialog:start:"):
        ticket = data.split(":", 2)[2]
        row = await get_request_by_ticket(ticket)
        if not row:
            await context.bot.send_message(chat_id=query.message.chat_id, text="Заявка не найдена.")
            return
        _id, t, author_id, *_ = row
        status = row[7]
        if status in ("Завершено", "Отклонено"):
            await context.bot.send_message(chat_id=query.message.chat_id, text="Заявка уже в финальном статусе. Диалог недоступен.")
            return

        await update_status(ticket, status="В обработке")

        admin_id = update.effective_user.id
        ACTIVE_DIALOGS_BY_TICKET[ticket] = {"admin_id": admin_id, "user_id": author_id}
        ACTIVE_DIALOGS_BY_ADMIN[admin_id] = ticket
        ACTIVE_DIALOGS_BY_USER[author_id] = ticket

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"Диалог по заявке {ticket} включён. Пишите сообщения — они уйдут автору.\nНажмите «Завершить диалог», когда уточнения будут собраны.",
            reply_markup=admin_dialog_inline_keyboard(ticket)
        )
        try:
            await context.bot.send_message(
                chat_id=author_id,
                text=f"Оператор подключился к вашей заявке {ticket}. Можете отвечать прямо здесь — сообщения уйдут оператору."
            )
        except Exception as e:
            log.warning("Не удалось уведомить пользователя о старте диалога: %s", e)
        return

    if data.startswith("dialog:stop:"):
        ticket = data.split(":", 2)[2]
        info = ACTIVE_DIALOGS_BY_TICKET.get(ticket)
        if info and info.get("admin_id") == update.effective_user.id:
            admin_id = info["admin_id"]
            user_id = info["user_id"]
            ACTIVE_DIALOGS_BY_TICKET.pop(ticket, None)
            if ACTIVE_DIALOGS_BY_ADMIN.get(admin_id) == ticket:
                ACTIVE_DIALOGS_BY_ADMIN.pop(admin_id, None)
            if ACTIVE_DIALOGS_BY_USER.get(user_id) == ticket:
                ACTIVE_DIALOGS_BY_USER.pop(user_id, None)
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"Диалог по заявке {ticket} завершён. Можете закрыть заявку кнопками «Завершено» / «Отклонено»."
            )
        else:
            await context.bot.send_message(chat_id=query.message.chat_id, text="Диалог не активен или управляется другим оператором.")
        return

    # --- Поменять статус заявки ---
    if data.startswith("status:"):
        try:
            _, ticket, new_status = data.split(":", 2)
        except ValueError:
            await context.bot.send_message(chat_id=query.message.chat_id, text="Некорректные данные статуса.")
            return

        row = await get_request_by_ticket(ticket)
        if not row:
            await context.bot.send_message(chat_id=query.message.chat_id, text="Заявка не найдена.")
            return
        current_status = row[7]
        if current_status in ("Завершено", "Отклонено"):
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"Заявка {ticket} уже в финальном статусе ({current_status}). Менять нельзя.")
            return

        await update_status(ticket, status=new_status)

        # Уведомим автора
        row = await get_request_by_ticket(ticket)
        if row:
            _id, ticket, user_id_author, *_ = row
            try:
                await context.bot.send_message(chat_id=user_id_author, text=f"Статус вашей заявки {ticket} изменён: {new_status}")
            except Exception as e:
                log.warning("Не удалось уведомить автора о статусе: %s", e)

        try:
            await query.edit_message_text(f"Статус заявки {ticket} изменён на: {new_status}")
        except BadRequest:
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"Статус заявки {ticket} изменён на: {new_status}")
        return

    # --- Разовый ответ ---
    if data.startswith("reply:"):
        ticket = data.split(":", 1)[1]
        context.user_data["reply_to_ticket"] = ticket
        try:
            await query.edit_message_text(f"Введите текст ответа для заявки {ticket} (разовый).")
        except BadRequest:
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"Введите текст ответа для заявки {ticket} (разовый).")
        return

# ========= ERROR HANDLER =========
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logging.exception("Exception while handling update:", exc_info=context.error)

# ========= STARTUP =========
async def on_startup(app):
    await init_db()
    Path(FILES_DIR).mkdir(parents=True, exist_ok=True)
    # Подсказки команд в меню Telegram
    try:
        await app.bot.set_my_commands([
            BotCommand("start", "Запуск и главное меню"),
            BotCommand("admin", "Получить права администратора"),
            BotCommand("export", "Экспорт отчёта (admin)"),
            BotCommand("cleanup", "Очистка заявок (admin)"),
            BotCommand("bulkclose", "Закрыть активные (admin)"),
            BotCommand("broadcast", "Массовая рассылка (admin)"),
        ])
    except Exception as e:
        log.warning("set_my_commands failed: %s", e)
    log.info("DB ready. Files dir: %s", FILES_DIR)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CommandHandler("cleanup", cleanup_command))
    app.add_handler(CommandHandler("bulkclose", bulkclose_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))

    # Инлайн-кнопки
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Любые сообщения в личке — общий обработчик
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_messages))

    # error handler
    app.add_error_handler(error_handler)

    app.post_init = on_startup
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
