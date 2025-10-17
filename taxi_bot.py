# taxi_bot.py (Версія 4.0 - Фінальна)

import asyncio
import sqlite3
import logging
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

# --- НАЛАШТУВАННЯ ---
# Ці дані потрібно буде вказати на хостингу в "Environment Variables"
BOT_TOKEN = os.environ.get("BOT_TOKEN")
REGISTRATION_PASSWORD = os.environ.get("REGISTRATION_PASSWORD", "taxi_driver_2025") # Пароль за замовчуванням
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0)) # Ваш Telegram ID
USERS_PER_PAGE = 5 # Кількість водіїв на одній сторінці в адмін-панелі

# Налаштування логування для відстеження роботи бота
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- БАЗА ДАНИХ (SQLite) ---
DB_FILE = "taxi_drivers.db"

def init_db():
    """Створює таблиці в базі даних, якщо їх ще не існує."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS drivers (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                car_brand TEXT,
                car_plate TEXT,
                platform TEXT,
                registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                driver_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                amount REAL NOT NULL,
                date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (driver_id) REFERENCES drivers (user_id)
            )''')
        conn.commit()

# --- СТАНИ (FSM) для покрокових дій ---
class Registration(StatesGroup):
    waiting_for_password = State()
    waiting_for_name = State()
    waiting_for_car_brand = State()
    waiting_for_car_plate = State()
    waiting_for_platform = State()

class AddTransaction(StatesGroup):
    waiting_for_amount = State()

class EditProfile(StatesGroup):
    choosing_field = State()
    entering_new_value = State()

class AdminEdit(StatesGroup):
    choosing_user = State()
    choosing_field = State()
    entering_new_value = State()

# --- КЛАВІАТУРИ ---
def get_main_menu_keyboard():
    """Повертає головне меню з кнопками."""
    buttons = [
        [KeyboardButton(text="✅ Додати Дохід/Чайові"), KeyboardButton(text="➖ Додати Витрату")],
        [KeyboardButton(text="📊 Моя Статистика"), KeyboardButton(text="📈 Розширена статистика")],
        [KeyboardButton(text="🏆 Рейтинг Водіїв"), KeyboardButton(text="👤 Мій Профіль")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, row_width=2)

async def get_admin_user_list_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    """Створює клавіатуру зі списком водіїв для редагування з пагінацією."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        offset = page * USERS_PER_PAGE
        cursor.execute("SELECT user_id, name FROM drivers ORDER BY registration_date DESC LIMIT ? OFFSET ?", (USERS_PER_PAGE, offset))
        users = cursor.fetchall()
        cursor.execute("SELECT COUNT(user_id) FROM drivers")
        total_users = cursor.fetchone()[0]

    keyboard = []
    for user_id, name in users:
        keyboard.append([InlineKeyboardButton(text=name, callback_data=f"admin_select_{user_id}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_page_{page - 1}"))
    if offset + USERS_PER_PAGE < total_users:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"admin_page_{page + 1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# --- ДОПОМІЖНІ ФУНКЦІЇ ---
def format_currency(amount: float) -> str:
    """Форматує суму в ціле число, якщо вона без копійок."""
    if amount == int(amount):
        return f"{int(amount)} грн"
    return f"{amount:.2f} грн"

async def is_registered(user_id: int) -> bool:
    """Перевіряє, чи є користувач у базі даних."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM drivers WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None

# --- ОСНОВНА ЛОГІКА БОТА ---
dp = Dispatcher()

# --- СТАРТ ТА РЕЄСТРАЦІЯ ---
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    if await is_registered(message.from_user.id):
        await message.answer(f"З поверненням, {message.from_user.first_name}! 👋", reply_markup=get_main_menu_keyboard())
    else:
        await message.answer("👋 Вітаю у боті для водіїв!\n\nДля початку роботи, будь ласка, введіть пароль для реєстрації:")
        await state.set_state(Registration.waiting_for_password)

@dp.message(Registration.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    if message.text == REGISTRATION_PASSWORD:
        await message.answer("✅ Пароль вірний! Тепер введіть ваше ім'я та прізвище:")
        await state.set_state(Registration.waiting_for_name)
    else:
        await message.answer("❌ Неправильний пароль. Спробуйте ще раз.")

@dp.message(Registration.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Чудово! Тепер вкажіть марку та модель вашого авто (напр., Kia Optima):")
    await state.set_state(Registration.waiting_for_car_brand)

@dp.message(Registration.waiting_for_car_brand)
async def process_car_brand(message: Message, state: FSMContext):
    await state.update_data(car_brand=message.text)
    await message.answer("Прийнято. Введіть номерний знак автомобіля (напр., BC 1234 HI):")
    await state.set_state(Registration.waiting_for_car_plate)

@dp.message(Registration.waiting_for_car_plate)
async def process_car_plate(message: Message, state: FSMContext):
    await state.update_data(car_plate=message.text.upper())
    await message.answer("Майже готово! На якій платформі працюєте? (напр., Uber, Bolt, Uklon)")
    await state.set_state(Registration.waiting_for_platform)

@dp.message(Registration.waiting_for_platform)
async def process_platform_and_finish_reg(message: Message, state: FSMContext):
    user_data = await state.get_data()
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO drivers (user_id, name, car_brand, car_plate, platform) VALUES (?, ?, ?, ?, ?)",
            (message.from_user.id, user_data['name'], user_data['car_brand'], user_data['car_plate'], message.text)
        )
        conn.commit()
    await state.clear()
    await message.answer("🎉 Реєстрацію успішно завершено! Ласкаво просимо!", reply_markup=get_main_menu_keyboard())

# --- ДОДАВАННЯ ТРАНЗАКЦІЙ ---
@dp.message(F.text == "✅ Додати Дохід/Чайові")
async def add_income_menu(message: Message):
    buttons = [[InlineKeyboardButton(text="💰 Дохід", callback_data="add_transaction_дохід")], [InlineKeyboardButton(text="🎁 Чайові", callback_data="add_transaction_чай")]]
    await message.answer("Оберіть тип доходу:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.message(F.text == "➖ Додати Витрату")
async def add_expense_menu(message: Message):
    buttons = [[InlineKeyboardButton(text="⛽ Паливо", callback_data="add_transaction_паливо"), InlineKeyboardButton(text="🧼 Мийка", callback_data="add_transaction_мийка")], [InlineKeyboardButton(text="🍔 Їжа", callback_data="add_transaction_їжа"), InlineKeyboardButton(text="🛠️ Ремонт", callback_data="add_transaction_ремонт")], [InlineKeyboardButton(text="Інше", callback_data="add_transaction_інше")]]
    await message.answer("Оберіть тип витрати:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("add_transaction_"))
async def process_add_transaction_type(callback: CallbackQuery, state: FSMContext):
    transaction_type = callback.data.split("_")[-1]
    await state.update_data(transaction_type=transaction_type)
    await callback.message.answer(f"Введіть суму для '{transaction_type.capitalize()}':")
    await state.set_state(AddTransaction.waiting_for_amount)
    await callback.answer()

@dp.message(AddTransaction.waiting_for_amount)
async def process_transaction_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        user_data = await state.get_data()
        transaction_type = user_data['transaction_type']
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO transactions (driver_id, type, amount) VALUES (?, ?, ?)", (message.from_user.id, transaction_type, amount))
            conn.commit()
        await message.answer(f"✅ Успішно додано: **{transaction_type.capitalize()}** на суму **{format_currency(amount)}**.", parse_mode=ParseMode.MARKDOWN)
        await state.clear()
    except ValueError:
        await message.answer("❌ Помилка. Будь ласка, введіть числове значення (напр., 150 або 95.50).")

# --- СТАТИСТИКА ---
@dp.message(F.text == "📊 Моя Статистика")
async def show_my_stats(message: Message):
    user_id = message.from_user.id
    current_month = datetime.now().strftime('%Y-%m')
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT type, SUM(amount) FROM transactions WHERE driver_id = ? AND strftime('%Y-%m', date) = ? GROUP BY type", (user_id, current_month))
        monthly_stats = cursor.fetchall()
        cursor.execute("SELECT type, SUM(amount) FROM transactions WHERE driver_id = ? GROUP BY type", (user_id,))
        total_stats = cursor.fetchall()

    def format_stats(title, stats):
        text = f"**{title}**\n"
        income = sum(amt for type, amt in stats if type in ['дохід', 'чай'])
        expenses = sum(amt for type, amt in stats if type not in ['дохід', 'чай'])
        if not stats: return f"**{title}**\nНемає даних.\n"
        text += f"🟢 **Зароблено:** {format_currency(income)}\n"
        text += f"🔴 **Витрачено:** {format_currency(expenses)}\n"
        text += f"💰 **Чистий прибуток:** {format_currency(income - expenses)}\n\nДеталізація:\n"
        for type, amount in stats:
            text += f" - {type.capitalize()}: {format_currency(amount)}\n"
        return text
    await message.answer(f"{format_stats('🗓️ Статистика за поточний місяць', monthly_stats)}\n---\n{format_stats('🕰️ Статистика за весь час', total_stats)}", parse_mode=ParseMode.MARKDOWN)

@dp.message(F.text == "📈 Розширена статистика")
async def advanced_stats_menu(message: Message):
    buttons = [[InlineKeyboardButton(text="Сьогодні", callback_data="stats_period_today")], [InlineKeyboardButton(text="Вчора", callback_data="stats_period_yesterday")], [InlineKeyboardButton(text="Цей тиждень", callback_data="stats_period_week")], [InlineKeyboardButton(text="Цей місяць", callback_data="stats_period_month")]]
    await message.answer("Оберіть період для перегляду статистики:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("stats_period_"))
async def show_advanced_stats(callback: CallbackQuery):
    period = callback.data.split("_")[-1]
    today = datetime.now()
    if period == "today":
        start_date, end_date, title = today.strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'), "📈 Статистика за сьогодні"
    elif period == "yesterday":
        start_date, end_date, title = (today - timedelta(days=1)).strftime('%Y-%m-%d'), (today - timedelta(days=1)).strftime('%Y-%m-%d'), "📈 Статистика за вчора"
    elif period == "week":
        start_date, end_date, title = (today - timedelta(days=today.weekday())).strftime('%Y-%m-%d'), today.strftime('%Y-%m-%d'), "📈 Статистика за цей тиждень"
    else: # month
        start_date, end_date, title = today.strftime('%Y-%m-01'), today.strftime('%Y-%m-%d'), "📈 Статистика за цей місяць"
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT type, SUM(amount) FROM transactions WHERE driver_id = ? AND date(date) BETWEEN ? AND ? GROUP BY type", (callback.from_user.id, start_date, end_date))
        stats = cursor.fetchall()
    
    income = sum(amt for type, amt in stats if type in ['дохід', 'чай'])
    expenses = sum(amt for type, amt in stats if type not in ['дохід', 'чай'])
    text = f"**{title}**\n\n"
    if not stats: text += "За цей період немає даних."
    else: text += f"🟢 **Зароблено:** {format_currency(income)}\n🔴 **Витрачено:** {format_currency(expenses)}\n💰 **Чистий прибуток:** {format_currency(income - expenses)}\n"
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()

# --- РЕЙТИНГ ---
@dp.message(F.text == "🏆 Рейтинг Водіїв")
async def show_rating(message: Message):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        current_month = datetime.now().strftime('%Y-%m')
        query = "SELECT d.name, d.car_brand, d.car_plate, SUM(t.amount) FROM transactions t JOIN drivers d ON t.driver_id = d.user_id WHERE t.type IN ('дохід', 'чай') AND strftime('%Y-%m', t.date) = ? GROUP BY d.user_id ORDER BY SUM(t.amount) DESC LIMIT 10"
        cursor.execute(query, (current_month,))
        monthly_rating = cursor.fetchall()
        query_all_time = "SELECT d.name, d.car_brand, d.car_plate, SUM(t.amount) FROM transactions t JOIN drivers d ON t.driver_id = d.user_id WHERE t.type IN ('дохід', 'чай') GROUP BY d.user_id ORDER BY SUM(t.amount) DESC LIMIT 10"
        cursor.execute(query_all_time)
        all_time_rating = cursor.fetchall()

    def format_rating(title, rating_data):
        text = f"**{title}**\n"
        if not rating_data: return text + "Ще немає даних для рейтингу.\n"
        medals = ["🥇", "🥈", "🥉"]
        for i, (name, car, plate, total) in enumerate(rating_data):
            place = medals[i] if i < 3 else f"**{i+1}.**"
            text += f"{place} {name} ({car}, {plate}) - **{format_currency(total)}**\n"
        return text
    await message.answer(f"🏆 **Рейтинг заробітку водіїв** 🏆\n\n{format_rating('🗓️ За Поточний Місяць', monthly_rating)}\n---\n{format_rating('🕰️ За Весь Час', all_time_rating)}", parse_mode=ParseMode.MARKDOWN)

# --- ПРОФІЛЬ ---
@dp.message(F.text == "👤 Мій Профіль")
async def show_my_profile(message: Message):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, car_brand, car_plate, platform FROM drivers WHERE user_id = ?", (message.from_user.id,))
        profile = cursor.fetchone()
    if profile:
        name, car, plate, platform = profile
        text = f"**👤 Ваш профіль:**\n\n**Ім'я:** {name}\n**Авто:** {car}\n**Номер:** {plate}\n**Платформа:** {platform}\n\nБажаєте змінити дані?"
        buttons = [[InlineKeyboardButton(text="✏️ Редагувати профіль", callback_data="edit_profile_start")]]
        await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data == "edit_profile_start")
async def edit_profile_start(callback: CallbackQuery, state: FSMContext):
    buttons = [[InlineKeyboardButton(text="Ім'я", callback_data="edit_field_name")], [InlineKeyboardButton(text="Авто", callback_data="edit_field_car_brand")], [InlineKeyboardButton(text="Номер", callback_data="edit_field_car_plate")], [InlineKeyboardButton(text="Платформу", callback_data="edit_field_platform")]]
    await callback.message.edit_text("Яке поле ви хочете змінити?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(EditProfile.choosing_field)

@dp.callback_query(EditProfile.choosing_field, F.data.startswith("edit_field_"))
async def edit_profile_choose_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[-1]
    field_map = {'name': "ім'я", 'car_brand': "марку авто", 'car_plate': "номер авто", 'platform': "платформу"}
    await state.update_data(field_to_edit=field)
    await callback.message.edit_text(f"Введіть нове значення для поля '{field_map[field]}':")
    await state.set_state(EditProfile.entering_new_value)

@dp.message(EditProfile.entering_new_value)
async def edit_profile_enter_value(message: Message, state: FSMContext):
    user_data = await state.get_data()
    field = user_data['field_to_edit']
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE drivers SET {field} = ? WHERE user_id = ?", (message.text, message.from_user.id))
        conn.commit()
    await message.answer("✅ Дані успішно оновлено!")
    await state.clear()
    await show_my_profile(message)

# --- АДМІН-ПАНЕЛЬ ---
@dp.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    keyboard = await get_admin_user_list_keyboard()
    await message.answer("Доброго дня, Адміністраторе! 🧑‍🔧\nОберіть водія для редагування:", reply_markup=keyboard)
    await state.set_state(AdminEdit.choosing_user)

@dp.callback_query(AdminEdit.choosing_user, F.data.startswith("admin_page_"))
async def admin_paginate_users(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[-1])
    keyboard = await get_admin_user_list_keyboard(page)
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(AdminEdit.choosing_user, F.data.startswith("admin_select_"))
async def admin_select_user(callback: CallbackQuery, state: FSMContext):
    user_id_to_edit = int(callback.data.split("_")[-1])
    await state.update_data(user_to_edit=user_id_to_edit)
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM drivers WHERE user_id = ?", (user_id_to_edit,))
        user_name = cursor.fetchone()[0]
    buttons = [[InlineKeyboardButton(text="Ім'я", callback_data="admin_edit_name")], [InlineKeyboardButton(text="Авто", callback_data="admin_edit_car_brand")], [InlineKeyboardButton(text="Номер", callback_data="admin_edit_car_plate")], [InlineKeyboardButton(text="Платформу", callback_data="admin_edit_platform")], [InlineKeyboardButton(text="⬅️ Повернутись до списку", callback_data="admin_back_to_list")]]
    await callback.message.edit_text(f"Ви обрали водія: **{user_name}**.\nЯке поле бажаєте змінити?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.MARKDOWN)
    await state.set_state(AdminEdit.choosing_field)

@dp.callback_query(AdminEdit.choosing_field, F.data.startswith("admin_edit_"))
async def admin_choose_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[-1]
    field_map = {'name': "ім'я", 'car_brand': "марку авто", 'car_plate': "номер авто", 'platform': "платформу"}
    await state.update_data(field_to_edit=field)
    await callback.message.edit_text(f"Введіть нове значення для поля **'{field_map[field]}'**:", parse_mode=ParseMode.MARKDOWN)
    await state.set_state(AdminEdit.entering_new_value)

@dp.callback_query(AdminEdit.choosing_field, F.data == "admin_back_to_list")
async def admin_back_to_list(callback: CallbackQuery, state: FSMContext):
    keyboard = await get_admin_user_list_keyboard()
    await callback.message.edit_text("Оберіть водія для редагування:", reply_markup=keyboard)
    await state.set_state(AdminEdit.choosing_user)

@dp.message(AdminEdit.entering_new_value)
async def admin_enter_new_value(message: Message, state: FSMContext):
    user_data = await state.get_data()
    field, user_id, new_value = user_data['field_to_edit'], user_data['user_to_edit'], message.text
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE drivers SET {field} = ? WHERE user_id = ?", (new_value, user_id))
        conn.commit()
    await message.answer("✅ Дані водія успішно оновлено!")
    await state.clear()
    keyboard = await get_admin_user_list_keyboard()
    await message.answer("Оберіть наступного водія для редагування:", reply_markup=keyboard)
    await state.set_state(AdminEdit.choosing_user)

# --- ОСНОВНА ФУНКЦІЯ ЗАПУСКУ ---
async def main():
    """Головна функція для запуску бота."""
    if not BOT_TOKEN:
        logging.critical("ПОМИЛКА: не знайдено BOT_TOKEN. Перевірте змінні оточення на хостингу.")
        return

    bot = Bot(token=BOT_TOKEN)
    init_db()  # Ініціалізуємо базу даних при старті
    logging.info("Бот запускається...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот зупинено.")