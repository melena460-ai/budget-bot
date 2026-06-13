"""
Семейный бюджет — Telegram Bot
Команды:
  /start          — приветствие и помощь
  /help           — все команды
  /отчёт          — сводка за текущий месяц
  /история [N]    — последние N операций (по умолч. 10)
  /категории      — список категорий
  /удалить [id]   — удалить операцию по ID

Добавление расхода (просто текстом):
  850 продукты Пятёрочка
  3500 красота стрижка
  авто 2000 бензин АЗС

Добавление дохода:
  +50000 зарплата
  доход 15000 фриланс
"""

import os
import json
import re
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

TOKEN = os.environ.get("BOT_TOKEN", "8460531456:AAFchQTVAVqNTuFH9twKzywsc73X-H1Cu9I")
DB_PATH = "budget.db"

CATEGORIES = {
    "продукты":    "Продукты",
    "еда":         "Продукты",
    "магазин":     "Продукты",
    "супермаркет": "Продукты",
    "авто":        "Авто",
    "бензин":      "Авто",
    "азс":         "Авто",
    "машина":      "Авто",
    "здоровье":    "Здоровье",
    "аптека":      "Здоровье",
    "врач":        "Здоровье",
    "больница":    "Здоровье",
    "клиника":     "Здоровье",
    "детское":     "Детское",
    "дети":        "Детское",
    "ребёнок":     "Детское",
    "ребенок":     "Детское",
    "детскиймир":  "Детское",
    "жкх":         "Коммунальные платежи",
    "коммунальные":"Коммунальные платежи",
    "квартплата":  "Коммунальные платежи",
    "свет":        "Коммунальные платежи",
    "газ":         "Коммунальные платежи",
    "ресторан":    "Рестораны и кафе",
    "кафе":        "Рестораны и кафе",
    "обед":        "Рестораны и кафе",
    "ужин":        "Рестораны и кафе",
    "кофе":        "Рестораны и кафе",
    "красота":     "Красота",
    "салон":       "Красота",
    "стрижка":     "Красота",
    "маникюр":     "Красота",
    "косметика":   "Красота",
    "одежда":      "Одежда",
    "обувь":       "Одежда",
    "одежда":      "Одежда",
    "перевод":     "Переводы",
    "животные":    "Животные",
    "питомец":     "Животные",
    "ветеринар":   "Животные",
    "зоомагазин":  "Животные",
    "образование": "Образование/досуг детей",
    "кружок":      "Образование/досуг детей",
    "секция":      "Образование/досуг детей",
    "авито":       "Авито",
    "ремонт":      "Сервис/ремонт",
    "сервис":      "Сервис/ремонт",
    "зарплата":    None,  # доход
    "доход":       None,
    "фриланс":     None,
    "аренда":      None,
    "кэшбэк":      None,
    "возврат":     None,
}

CAT_EMOJI = {
    "Продукты":                "🛒",
    "Авто":                    "🚗",
    "Здоровье":                "💊",
    "Детское":                 "👶",
    "Коммунальные платежи":    "🏠",
    "Рестораны и кафе":        "🍽",
    "Красота":                 "💄",
    "Одежда":                  "👗",
    "Переводы":                "💸",
    "Животные":                "🐾",
    "Образование/досуг детей": "📚",
    "Авито":                   "📦",
    "Сервис/ремонт":           "🔧",
    "Прочее":                  "📌",
}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            amount REAL,
            category TEXT,
            description TEXT,
            type TEXT
        )
    """)
    conn.commit()
    conn.close()

def add_tx(user_id, amount, category, description, tx_type):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO transactions (user_id,date,amount,category,description,type) VALUES (?,?,?,?,?,?)",
        (user_id, datetime.now().strftime("%d.%m.%Y"), abs(amount), category, description, tx_type)
    )
    tx_id = c.lastrowid
    conn.commit()
    conn.close()
    return tx_id

def get_month_stats(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    month = datetime.now().strftime("%m.%Y")
    c.execute("""
        SELECT category, SUM(amount), type FROM transactions
        WHERE user_id=? AND date LIKE ?
        GROUP BY category, type
        ORDER BY SUM(amount) DESC
    """, (user_id, f"%.{month}"))
    rows = c.fetchall()
    conn.close()
    return rows

def get_history(user_id, limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, date, amount, category, description, type FROM transactions
        WHERE user_id=? ORDER BY id DESC LIMIT ?
    """, (user_id, limit))
    rows = c.fetchall()
    conn.close()
    return rows

def delete_tx(tx_id, user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM transactions WHERE id=? AND user_id=?", (tx_id, user_id))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def parse_message(text):
    """
    Парсит сообщение вида:
      850 продукты Пятёрочка
      +50000 зарплата январь
      авто 2500 бензин
    Возвращает (amount, category_raw, description) или None
    """
    text = text.strip()
    is_income = text.startswith("+") or any(
        w in text.lower() for w in ["доход","зарплата","фриланс","аренда","кэшбэк","возврат"]
    )

    # Найти число
    nums = re.findall(r"[\+\-]?\d+(?:[.,]\d+)?", text)
    if not nums:
        return None
    amount = float(nums[0].replace(",", ".").replace("+", ""))

    # Убрать число из текста
    rest = re.sub(r"[\+\-]?\d+(?:[.,]\d+)?", "", text, count=1).strip()
    words = rest.split()

    # Первое слово — попытка определить категорию
    cat_raw = words[0].lower() if words else "прочее"
    desc = " ".join(words[1:]) if len(words) > 1 else ""

    return amount, cat_raw, desc, is_income

def resolve_category(cat_raw, is_income):
    key = cat_raw.lower().replace(" ", "")
    for k, v in CATEGORIES.items():
        if k in key or key in k:
            if v is None:
                return None, True   # доход
            return v, False
    if is_income:
        return None, True
    return "Прочее", False

def fmt(n):
    return f"{int(n):,}".replace(",", " ") + " ₽"

# ============================================================
# HANDLERS
# ============================================================
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Семейный бюджет*\n\n"
        "Просто напиши расход, например:\n"
        "`850 продукты Пятёрочка`\n"
        "`3500 красота стрижка`\n"
        "`авто 2000 бензин`\n\n"
        "Для дохода:\n"
        "`+50000 зарплата`\n\n"
        "Команды:\n"
        "/отчёт — сводка за месяц\n"
        "/история — последние операции\n"
        "/категории — список категорий\n"
        "/удалить [id] — удалить запись",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await start(update, ctx)

async def report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    rows = get_month_stats(uid)
    if not rows:
        await update.message.reply_text("За этот месяц пока нет операций.")
        return

    income = sum(r[1] for r in rows if r[2] == "income")
    expense = sum(r[1] for r in rows if r[2] == "expense")
    balance = income - expense

    month_name = datetime.now().strftime("%B %Y")
    lines = [f"📊 *{month_name}*\n"]
    lines.append(f"💚 Доходы: {fmt(income)}")
    lines.append(f"❤️ Расходы: {fmt(expense)}")
    lines.append(f"{'🟢' if balance >= 0 else '🔴'} Остаток: {fmt(balance)}\n")
    lines.append("*По категориям:*")

    exp_rows = [(r[0], r[1]) for r in rows if r[2] == "expense"]
    exp_rows.sort(key=lambda x: x[1], reverse=True)
    total_exp = expense or 1
    for cat, amt in exp_rows:
        emoji = CAT_EMOJI.get(cat, "📌")
        pct = int(amt / total_exp * 100)
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        lines.append(f"{emoji} {cat}: {fmt(amt)} ({pct}%)\n`{bar}`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def history(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    limit = 10
    if ctx.args:
        try: limit = int(ctx.args[0])
        except: pass
    rows = get_history(uid, limit)
    if not rows:
        await update.message.reply_text("Операций пока нет.")
        return

    lines = [f"📋 *Последние {len(rows)} операций:*\n"]
    for tx_id, date, amount, cat, desc, tx_type in rows:
        sign = "+" if tx_type == "income" else "-"
        emoji = CAT_EMOJI.get(cat, "📌") if tx_type == "expense" else "💚"
        lines.append(f"`#{tx_id}` {date} {emoji} {sign}{fmt(amount)} — {cat}" + (f"\n_{desc}_" if desc else ""))

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def categories(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lines = ["📂 *Категории расходов:*\n"]
    for cat, emoji in CAT_EMOJI.items():
        lines.append(f"{emoji} {cat}")
    lines.append("\n_Пишите название категории в сообщении, бот определит автоматически._")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not ctx.args:
        await update.message.reply_text("Укажите ID: /удалить 42")
        return
    try:
        tx_id = int(ctx.args[0].lstrip("#"))
    except:
        await update.message.reply_text("Неверный ID.")
        return
    if delete_tx(tx_id, uid):
        await update.message.reply_text(f"✅ Операция #{tx_id} удалена.")
    else:
        await update.message.reply_text(f"Операция #{tx_id} не найдена.")

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    uid = update.effective_user.id

    parsed = parse_message(text)
    if not parsed:
        await update.message.reply_text(
            "Не понял 🤔 Попробуйте:\n`850 продукты Пятёрочка`\n`+50000 зарплата`",
            parse_mode="Markdown"
        )
        return

    amount, cat_raw, desc, is_income = parsed
    cat, confirmed_income = resolve_category(cat_raw, is_income)

    if confirmed_income:
        # Доход
        tx_id = add_tx(uid, amount, "Доход", desc or cat_raw, "income")
        await update.message.reply_text(
            f"💚 Записан доход #{tx_id}\n"
            f"Сумма: *{fmt(amount)}*\n"
            f"Описание: {desc or cat_raw}",
            parse_mode="Markdown"
        )
    else:
        # Расход — предложить уточнить категорию если не распознана чётко
        tx_id = add_tx(uid, amount, cat, desc or cat_raw, "expense")
        emoji = CAT_EMOJI.get(cat, "📌")
        keyboard = [[
            InlineKeyboardButton("✅ Верно", callback_data=f"ok_{tx_id}"),
            InlineKeyboardButton("✏️ Изменить категорию", callback_data=f"edit_{tx_id}_{amount}"),
        ]]
        await update.message.reply_text(
            f"❤️ Записан расход #{tx_id}\n"
            f"Сумма: *{fmt(amount)}*\n"
            f"Категория: {emoji} *{cat}*\n"
            f"Описание: {desc or cat_raw}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("ok_"):
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("👍 Сохранено!")

    elif data.startswith("edit_"):
        parts = data.split("_")
        tx_id = parts[1]
        # Show category picker
        cats = list(CAT_EMOJI.items())
        keyboard = []
        row = []
        for i, (cat, emoji) in enumerate(cats):
            row.append(InlineKeyboardButton(f"{emoji} {cat}", callback_data=f"setcat_{tx_id}_{cat}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("setcat_"):
        parts = data.split("_", 2)
        tx_id = parts[1]
        new_cat = parts[2]
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE transactions SET category=? WHERE id=?", (new_cat, tx_id))
        conn.commit()
        conn.close()
        emoji = CAT_EMOJI.get(new_cat, "📌")
        await query.edit_message_text(
            f"✅ Категория обновлена: {emoji} *{new_cat}*",
            parse_mode="Markdown"
        )

def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("report", report))
app.add_handler(CommandHandler("history", history))
app.add_handler(CommandHandler("categories", categories))
app.add_handler(CommandHandler("delete", delete))
       app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
