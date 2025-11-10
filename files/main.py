# main.py
# Главный файл бота. Здесь хендлеры команд/кнопок и запуск приложения.
# Бот делает три вещи:
#  1) Создать заявку (пользователь)
#  2) Посмотреть мои заявки (пользователь)
#  3) Открыть заявку, изменить статус и ОТВЕТИТЬ пользователю (админ)

import asyncio
import logging
from typing import Optional

from telegram import (
    Update,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, ContextTypes,
    CommandHandler, MessageHandler, CallbackQueryHandler,
    filters
)

from config import BOT_TOKEN, ADMIN_SECRET, FILES_DIR
from utils import gen_ticket
from db import (
    init_db, create_user, set_admin, list_admins,
    save_request, list_user_requests, get_request_by_ticket, update_status,
    save_reply, list_replies
)

# Включаем логирование (полезно для отладки)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

# Кнопки главного меню (простые и понятные)
BTN_CREATE = "Создать обращение"
BTN_MY = "Мои обращения"
BTN_HELP = "Справка"

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton(BTN_CREATE)], [KeyboardButton(BTN_MY)], [KeyboardButton(BTN_HELP)]],
    resize_keyboard=True
)


# ======= ВСПОМОГАТЕЛЬНОЕ =======

def normalize(text: Optional[str]) -> str:
    """Просто приводим текст к нижнему регистру и режем пробелы."""
    return (text or "").strip().lower()


# ======= КОМАНДЫ =======

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start — регистрируем юзера, показываем клавиатуру."""
    user = update.effective_user
    await create_user(user.id, user.username, user.first_name)

    await update.message.reply_text(
        "Привет! Это бот-тикетница.\n\n"
        "Нажми «Создать обращение», чтобы оставить заявку.\n"
        "«Мои обращения» — список твоих заявок.\n"
        "«Справка» — краткая помощь.",
        reply_markup=MAIN_KEYBOARD
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /admin <код> — выдаём права админа, если код верный."""
    user = update.effective_user
    args = update.message.text.split(maxsplit=1)
    if len(args) < 2:
        await update.message.reply_text("Использование: /admin <секретный_код>", reply_markup=MAIN_KEYBOARD)
        return

    code = args[1].strip()
    if code == ADMIN_SECRET:
        await set_admin(user.id)
        await update.message.reply_text("Готово! Вы администратор.", reply_markup=MAIN_KEYBOARD)
    else:
        await update.message.reply_text("Код неверный.", reply_markup=MAIN_KEYBOARD)


# ======= ОСНОВНАЯ ЛОГИКА СООБЩЕНИЙ =======

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Все текстовые сообщения попадают сюда (в личке с ботом)."""
    if not update.message:
        return

    user = update.effective_user
    text = update.message.text or ""

    # Всегда гарантируем, что юзер есть в БД
    await create_user(user.id, user.username, user.first_name)

    # --- 1) Режим "админ отвечает пользователю" ---
    # Админ нажал "Ответить пользователю 💬" → мы поставили флаг reply_to_ticket
    if context.user_data.get("reply_to_ticket"):
        admins = await list_admins()
        if user.id in admins:
            ticket = context.user_data.pop("reply_to_ticket")
            req = await get_request_by_ticket(ticket)
            if not req:
                await update.message.reply_text("Заявка не найдена.", reply_markup=MAIN_KEYBOARD)
                return

            # Извлекаем user_id автора заявки (в выборке он под индексом 2)
            _, ticket, author_id, *_ = req

            # Сохраняем ответ и отправляем его автору заявки
            await save_reply(ticket, user.id, text)
            try:
                await context.bot.send_message(
                    chat_id=author_id,
                    text=f"Ответ по вашей заявке {ticket}:\n\n{text}"
                )
            except Exception as e:
                log.warning("Не удалось отправить ответ пользователю: %s", e)

            await update.message.reply_text(
                f"Ответ отправлен пользователю (заявка {ticket}).",
                reply_markup=MAIN_KEYBOARD
            )
            return
        else:
            # Если вдруг флаг остался у не-админа — уберём его
            context.user_data.pop("reply_to_ticket", None)

    # --- 2) Создание заявки (пользователь сначала нажимает кнопку) ---
    # Если флаг awaiting_request = True → следующее сообщение считаем текстом заявки
    if context.user_data.get("awaiting_request"):
        context.user_data.pop("awaiting_request", None)  # сбрасываем флаг
        ticket = gen_ticket()
        await save_request(ticket=ticket, user_id=user.id, text=text)

        # Сообщаем автору номер его заявки
        await update.message.reply_text(
            f"Заявка принята! Номер: {ticket}\nМы сообщили администраторам.",
            reply_markup=MAIN_KEYBOARD
        )

        # Шлём уведомление всем админам (если они есть)
        admins = await list_admins()
        if admins:
            buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton("Открыть заявку", callback_data=f"open:{ticket}")]
            ])
            for admin_id in admins:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=f"Новая заявка {ticket} от @{user.username or user.id}\n\n{text}",
                        reply_markup=buttons
                    )
                except Exception as e:
                    log.warning("Не удалось уведомить админа %s: %s", admin_id, e)
        return

    # --- 3) Обычная обработка кнопок главного меню ---
    low = normalize(text)

    if low == normalize(BTN_CREATE):
        # Ставим флаг: следующее сообщение пользователя = текст заявки
        context.user_data["awaiting_request"] = True
        await update.message.reply_text(
            "Напишите текст вашей заявки одним сообщением.\n(Фото/доки можно добавить позже — логика уже заложена)",
            reply_markup=MAIN_KEYBOARD
        )
        return

    if low == normalize(BTN_MY):
        # Покажем короткий список заявок пользователя
        rows = await list_user_requests(user.id)
        if not rows:
            await update.message.reply_text("У вас пока нет заявок.", reply_markup=MAIN_KEYBOARD)
            return

        lines = []
        for r in rows[:10]:  # покажем максимум 10 последних, чтобы не засорять чат
            _id, ticket, _uid, rtext, _mp, _lat, _lon, status, _cmt, created, _upd = r
            # Сниппет делаем покороче, чтоб не растягивать
            snippet = (rtext[:60] + "…") if len(rtext) > 60 else rtext
            lines.append(f"{ticket} — {status} — {created}\n{snippet}")

        await update.message.reply_text(
            "Ваши последние заявки:\n\n" + "\n\n".join(lines),
            reply_markup=MAIN_KEYBOARD
        )
        return

    if low == normalize(BTN_HELP):
        await update.message.reply_text(
            "Как пользоваться ботом:\n"
            "1) Нажмите «Создать обращение» и отправьте текст одним сообщением.\n"
            "2) Администратор откроет вашу заявку и ответит, либо поменяет статус.\n"
            "3) «Мои обращения» — список ваших заявок со статусами.",
            reply_markup=MAIN_KEYBOARD
        )
        return

    # Если это что-то непонятное — подскажем, куда нажать
    await update.message.reply_text(
        "Нажмите «Создать обращение», чтобы оставить заявку.\n"
        "Или «Мои обращения», чтобы посмотреть статусы.",
        reply_markup=MAIN_KEYBOARD
    )


# ======= CALLBACK-КНОПКИ ДЛЯ АДМИНОВ =======

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатываем нажатия на инлайн-кнопки (admin)."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data or ""

    # --- Открыть карточку заявки ---
    if data.startswith("open:"):
        ticket = data.split(":", 1)[1]
        row = await get_request_by_ticket(ticket)
        if not row:
            await query.edit_message_text("Заявка не найдена.")
            return

        _id, ticket, user_id, text, media_path, lat, lon, status, admin_comment, created, updated = row

        # Можно вывести краткую историю ответов (по желанию)
        replies = await list_replies(ticket)
        replies_block = ""
        if replies:
            last = replies[-1]
            rid, rtext, rtime = last[0], last[1], last[2]
            replies_block = f"\n\nПоследний ответ: {rtext}\n({rtime})"

        msg = (
            f"Заявка {ticket}\n"
            f"Автор: {user_id}\n"
            f"Создана: {created}\n"
            f"Статус: {status}\n"
            f"Текст:\n{text}{replies_block}"
        )

        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("Ответить пользователю 💬", callback_data=f"reply:{ticket}")],
            [InlineKeyboardButton("В обработке", callback_data=f"status:{ticket}:В обработке"),
             InlineKeyboardButton("Завершено", callback_data=f"status:{ticket}:Завершено")],
            [InlineKeyboardButton("Отклонено", callback_data=f"status:{ticket}:Отклонено")]
        ])

        await query.edit_message_text(msg, reply_markup=buttons)
        return

    # --- Поменять статус заявки ---
    if data.startswith("status:"):
        try:
            _, ticket, new_status = data.split(":", 2)
        except ValueError:
            await query.edit_message_text("Некорректные данные статуса.")
            return

        await update_status(ticket, status=new_status)

        # Уведомим автора, если сможем
        row = await get_request_by_ticket(ticket)
        if row:
            _id, ticket, user_id, *_ = row
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"Статус вашей заявки {ticket} изменён: {new_status}"
                )
            except Exception as e:
                log.warning("Не удалось уведомить автора о статусе: %s", e)

        await query.edit_message_text(f"Статус заявки {ticket} изменён на: {new_status}")
        return

    # --- Включить режим ответа ---
    if data.startswith("reply:"):
        ticket = data.split(":", 1)[1]
        context.user_data["reply_to_ticket"] = ticket
        await query.edit_message_text(
            f"Введите текст ответа для заявки {ticket}.\n"
            f"Когда отправите сообщение — я перешлю его автору.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Отмена", callback_data=f"cancel_reply:{ticket}")]
            ])
        )
        return

    # --- Отмена режима ответа ---
    if data.startswith("cancel_reply:"):
        ticket = data.split(":", 1)[1]
        context.user_data.pop("reply_to_ticket", None)
        await query.edit_message_text(f"Ответ отменён для заявки {ticket}.")
        return


# ======= ЗАПУСК =======

async def on_startup(app):
    """Хук перед запуском polling — инициализируем БД."""
    await init_db()
    log.info("DB ready. Files dir: %s", FILES_DIR)

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("admin", admin_command))

    # Инлайн-кнопки (админские)
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Любой текст в личке — в общий обработчик
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))

    # Запуск
    app.post_init = on_startup  # вызовем init_db перед стартом
    app.run_polling(close_loop=False)
    # close_loop=False — чтобы asyncio-цикл закрывался корректно на Windows

if __name__ == "__main__":
    main()
