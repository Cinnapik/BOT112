# main.py

import asyncio
from pathlib import Path
from dotenv import load_dotenv

from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, CallbackQueryHandler

from config import BOT_TOKEN, FILES_DIR, ADMIN_SECRET
from db import init_db, create_user, save_request, list_user_requests, set_admin, list_admins, get_request_by_ticket, update_status
from utils import gen_ticket, save_file_bytes

load_dotenv()
Path(FILES_DIR).mkdir(parents=True, exist_ok=True)

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("Создать обращение"), KeyboardButton("Мои обращения")],
        [KeyboardButton("Справка")]
    ],
    resize_keyboard=True
)

# /start показывает клавиатуру
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await create_user(user.id, user.username, user.first_name)
    await update.message.reply_text("Здравствуйте! Нажмите кнопку для действия.", reply_markup=MAIN_KEYBOARD)

# /admin <код> даёт права админа 
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("Использование: /admin <код>")
        return
    if args[0].strip() == ADMIN_SECRET:
        await set_admin(update.effective_user.id)
        await update.message.reply_text("Вы получили права администратора.")
    else:
        await update.message.reply_text("Неверный код.")

# Простая функция для распознавания текста кнопок
def detect_button(text: str):
    if not text:
        return None
    t = text.strip().lower()
    if "создать" in t:
        return "create"
    if "мои" in t and "обращ" in t:
        return "my"
    if "справка" in t:
        return "help"
    return None

# Основной обработчик: кнопки и создание заявок
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return

    user = update.effective_user
    await create_user(user.id, user.username, user.first_name)

    text = update.message.text or ""

    # Если пользователь ранее нажал "Создать обращение" — следующее сообщение станет заявкой
    if context.user_data.get("awaiting_request"):
        ticket = gen_ticket()
        await save_request(ticket, user.id, text, None, None, None)
        await update.message.reply_text(f"Заявка принята, номер {ticket}", reply_markup=MAIN_KEYBOARD)
        admins = await list_admins()
        if admins:
            notif = f"Новая заявка {ticket}\nОт: {user.full_name} ({user.id})\n\n{text}"
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("Открыть заявку", callback_data=f"open:{ticket}")]])
            for aid in admins:
                try:
                    await context.bot.send_message(chat_id=aid, text=notif, reply_markup=kb)
                except Exception:
                    pass
        context.user_data.pop("awaiting_request", None)
        return

    action = detect_button(text)
    if action == "create":
        context.user_data["awaiting_request"] = True
        await update.message.reply_text("Введите текст обращения. Следующее ваше сообщение будет отправлено как заявка.", reply_markup=MAIN_KEYBOARD)
        return
    if action == "my":
        rows = await list_user_requests(user.id)
        if not rows:
            await update.message.reply_text("У вас нет обращений.", reply_markup=MAIN_KEYBOARD)
            return
        lines = []
        for ticket, msg, status, created in rows:
            snippet = (msg[:80] + "...") if msg and len(msg) > 80 else (msg or "<пусто>")
            lines.append(f"{ticket} — {status} — {created.split('T')[0]}\n{snippet}")
        await update.message.reply_text("\n\n".join(lines), reply_markup=MAIN_KEYBOARD)
        return
    if action == "help":
        await update.message.reply_text(
            "Справка:\n- Нажмите Создать обращение и введите текст.\n- Мои обращения — посмотреть ваши заявки.\n- Админ вводит /admin <код> чтобы получить права.",
            reply_markup=MAIN_KEYBOARD
        )
        return

    # Если пользователь пишет текст без нажатия кнопки — подсказываем
    await update.message.reply_text("Чтобы создать обращение — нажмите кнопку 'Создать обращение'.", reply_markup=MAIN_KEYBOARD)

# Обработчик callback'ов от админских inline-кнопок 
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data.startswith("open:"):
        ticket = data.split(":", 1)[1]
        row = await get_request_by_ticket(ticket)
        if not row:
            await query.edit_message_text("Заявка не найдена.")
            return
        _, ticket, uid, text, media_path, lat, lon, status, admin_comment, created_at, updated_at = row
        txt = f"Заявка {ticket}\nСтатус: {status}\nОт: {uid}\nДата: {created_at}\n\n{(text or '<пусто>')}"
        buttons = [
            [InlineKeyboardButton("В обработке", callback_data=f"status:{ticket}:В обработке"),
             InlineKeyboardButton("Завершено", callback_data=f"status:{ticket}:Завершено")],
            [InlineKeyboardButton("Отклонено", callback_data=f"status:{ticket}:Отклонено")]
        ]
        try:
            await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(buttons))
        except Exception:
            pass
        return

    if data.startswith("status:"):
        parts = data.split(":", 2)
        if len(parts) < 3:
            await query.edit_message_text("Неверные данные.")
            return
        ticket = parts[1]; new_status = parts[2]
        await update_status(ticket, new_status, admin_comment=None)
        row = await get_request_by_ticket(ticket)
        if row:
            _, ticket, uid, text, *_ = row
            try:
                await context.bot.send_message(chat_id=uid, text=f"Статус вашей заявки {ticket} изменён: {new_status}")
            except Exception:
                pass
        await query.edit_message_text(f"Статус изменён на: {new_status}")
        return

# Сборка приложения и запуск
def build_app():
    return ApplicationBuilder().token(BOT_TOKEN).build()

def main():
    asyncio.run(init_db())

    # Создаём event loop и ставим его текущим 
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = build_app()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_messages))

    print("Bot started. Нажмите Ctrl+C для остановки.")
    app.run_polling()

if __name__ == "__main__":
    main()
