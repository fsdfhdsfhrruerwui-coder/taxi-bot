# taxi_bot.py (Версія 12.2 - З веб-сервером для безкоштовного хостингу Render)

import asyncio
import sqlite3
import logging
import os
from datetime import datetime, timedelta
from threading import Thread
from flask import Flask

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

# --- НАЛАШТУВАННЯ ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DEFAULT_REGISTRATION_PASSWORD = "taxi_driver_2025"
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
USERS_PER_PAGE = 5

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- НАЛАШТУВАННЯ "ШИРМИ" (Flask) для Render ---
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# --- БАЗА ДАНИХ (SQLite) ---
DB_FILE = "taxi_drivers.db"

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS drivers (user_id INTEGER PRIMARY KEY, name TEXT NOT NULL, car_brand TEXT, car_plate TEXT, platform TEXT, registration_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, driver_id INTEGER NOT NULL, type TEXT NOT NULL, amount REAL NOT NULL, date TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (driver_id) REFERENCES drivers (user_id))''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)''')
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", ('password', DEFAULT_REGISTRATION_PASSWORD))
        conn.commit()

# --- СТАНИ FSM ---
class Registration(StatesGroup):
    waiting_for_password, waiting_for_name, waiting_for_car_brand, waiting_for_car_plate, waiting_for_platform = [State() for _ in range(5)]

class AddTransaction(StatesGroup):
    waiting_for_amount = State()

class EditProfile(StatesGroup):
    choosing_field, entering_new_value = [State() for _ in range(2)]

class AdminEdit(StatesGroup):
    choosing_user, choosing_field, entering_new_value = [State() for _ in range(3)]
    managing_finances = State()
    adding_transaction_type, adding_transaction_amount = [State() for _ in range(2)]
    editing_transaction_amount = State()

class AdminSettings(StatesGroup):
    choosing_setting, entering_new_password = [State() for _ in range(2)]

# --- КЛАВІАТУРИ ---
def get_main_menu_keyboard():
    buttons = [
        [KeyboardButton(text="✅ Додати Дохід/Чайові"), KeyboardButton(text="➖ Додати Витрату")],
        [KeyboardButton(text="📊 Моя Статистика"), KeyboardButton(text="📈 Розширена статистика")],
        [KeyboardButton(text="🏆 Рейтинг Водіїв"), KeyboardButton(text="👤 Мій Профіль")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, row_width=2)

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Відмінити", callback_data="action_cancel")]])

async def get_admin_user_list_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        offset = page * USERS_PER_PAGE
        cursor.execute("SELECT user_id, name FROM drivers ORDER BY registration_date DESC LIMIT ? OFFSET ?", (USERS_PER_PAGE, offset))
        users = cursor.fetchall()
        cursor.execute("SELECT COUNT(user_id) FROM drivers")
        total_users = cursor.fetchone()[0]
    keyboard = []
    for user_id, name in users:
        keyboard.append([InlineKeyboardButton(text=name, callback_data=f"admin_select_user_{user_id}")])
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_page_{page - 1}"))
    if offset + USERS_PER_PAGE < total_users:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"admin_page_{page + 1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton(text="❌ Завершити", callback_data="admin_finish")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

async def get_admin_user_management_keyboard(user_id: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="✏️ Редагувати профіль", callback_data=f"admin_edit_profile_{user_id}")],
        [InlineKeyboardButton(text="💰 Керувати фінансами", callback_data=f"admin_manage_finances_{user_id}")],
        [InlineKeyboardButton(text="⬅️ Повернутись до списку", callback_data="admin_back_to_list")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# --- ДОПОМІЖНІ ФУНКЦІЇ ---
def format_currency(amount: float) -> str:
    if amount == int(amount): return f"{int(amount)} грн"
    return f"{amount:.2f} грн"

async def is_registered(user_id: int) -> bool:
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM drivers WHERE user_id = ?", (user_id,))
            return cursor.fetchone() is not None
    except sqlite3.OperationalError: return False

# --- ОСНОВНА ЛОГІКА БОТА ---
dp = Dispatcher()

@dp.callback_query(F.data == "action_cancel")
async def handle_cancel_action(callback: CallbackQuery, state: FSMContext):
    current_state = await state.get_state()
    if current_state is not None and "AdminEdit" in current_state:
        user_data = await state.get_data()
        user_id = user_data.get('user_to_edit')
        await callback.message.edit_text("Дію скасовано.")
        await state.set_state(AdminEdit.choosing_user)
        if user_id:
            await admin_select_user(callback, state, user_id_from_context=user_id)
        else:
             await admin_finish(callback, state)
    else:
        await state.clear()
        await callback.message.edit_text("Дію скасовано.")
        await callback.message.answer("Ви повернулись у головне меню.", reply_markup=get_main_menu_keyboard())
    await callback.answer()

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    if await is_registered(message.from_user.id):
        await message.answer(f"З поверненням, {message.from_user.first_name}! 👋", reply_markup=get_main_menu_keyboard())
    else:
        await message.answer("👋 Вітаю у боті для водіїв!\n\nЦе ваш особистий помічник для ведення фінансів. Будь ласка, введіть пароль для реєстрації.", reply_markup=ReplyKeyboardRemove())
        await state.set_state(Registration.waiting_for_password)

@dp.message(Command("menu"))
async def show_main_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Головне меню:", reply_markup=get_main_menu_keyboard())

@dp.message(Registration.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'password'")
        current_password = cursor.fetchone()[0]
    if message.text == current_password:
        await message.answer("✅ Пароль вірний! Як до вас звертатись?\n(Введіть ім'я та, за бажанням, прізвище):")
        await state.set_state(Registration.waiting_for_name)
    else:
        await message.answer("❌ Неправильний пароль. Спробуйте ще раз.")

@dp.message(Registration.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Чудово! Вкажіть марку та модель авто (напр., Kia Optima):")
    await state.set_state(Registration.waiting_for_car_brand)

@dp.message(Registration.waiting_for_car_brand)
async def process_car_brand(message: Message, state: FSMContext):
    await state.update_data(car_brand=message.text)
    await message.answer("Прийнято. Введіть номерний знак (напр., BC 1234 HI):")
    await state.set_state(Registration.waiting_for_car_plate)

@dp.message(Registration.waiting_for_car_plate)
async def process_car_plate(message: Message, state: FSMContext):
    await state.update_data(car_plate=message.text.upper())
    await message.answer("Майже готово! На якій платформі працюєте? (напр., Uber, Bolt)")
    await state.set_state(Registration.waiting_for_platform)

@dp.message(Registration.waiting_for_platform)
async def process_platform_and_finish_reg(message: Message, state: FSMContext):
    user_data = await state.get_data()
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO drivers (user_id, name, car_brand, car_plate, platform) VALUES (?, ?, ?, ?, ?)", (message.from_user.id, user_data['name'], user_data['car_brand'], user_data['car_plate'], message.text))
        conn.commit()
    await state.clear()
    await message.answer("🎉 Реєстрацію успішно завершено! Ласкаво просимо!", reply_markup=get_main_menu_keyboard())

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
    await callback.message.edit_text(f"Введіть суму для '{transaction_type.capitalize()}' (напр., 1500.50)", reply_markup=get_cancel_keyboard())
    await state.set_state(AddTransaction.waiting_for_amount)
    await callback.answer()

@dp.message(AddTransaction.waiting_for_amount)
async def process_transaction_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            await message.answer("❌ Сума має бути більшою за нуль. Спробуйте ще раз.", reply_markup=get_cancel_keyboard())
            return
        user_data = await state.get_data()
        transaction_type = user_data['transaction_type']
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO transactions (driver_id, type, amount) VALUES (?, ?, ?)", (message.from_user.id, transaction_type, amount))
            conn.commit()
        await message.answer(f"✅ Успішно додано: **{transaction_type.capitalize()}** на суму **{format_currency(amount)}**.", parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_menu_keyboard())
        await state.clear()
    except ValueError:
        await message.answer("❌ Помилка. Введіть числове значення (напр., 150.50).", reply_markup=get_cancel_keyboard())

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
    else:
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

@dp.message(F.text == "🏆 Рейтинг Водіїв")
async def show_rating(message: Message):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        current_month = datetime.now().strftime('%Y-%m')
        cursor.execute("SELECT DISTINCT driver_id FROM transactions WHERE strftime('%Y-%m', date) = ?", (current_month,))
        driver_ids = [row[0] for row in cursor.fetchall()]
        rating_data = []
        for user_id in driver_ids:
            cursor.execute("SELECT name, car_brand, car_plate FROM drivers WHERE user_id = ?", (user_id,))
            driver_info = cursor.fetchone()
            if not driver_info: continue
            cursor.execute("SELECT SUM(amount) FROM transactions WHERE driver_id = ? AND type IN ('дохід', 'чай') AND strftime('%Y-%m', date) = ?", (user_id, current_month))
            income = cursor.fetchone()[0] or 0
            cursor.execute("SELECT type, SUM(amount) FROM transactions WHERE driver_id = ? AND type NOT IN ('дохід', 'чай') AND strftime('%Y-%m', date) = ? GROUP BY type", (user_id, current_month))
            expenses_list = cursor.fetchall()
            expenses_total = sum(amount for _, amount in expenses_list)
            net_income = income - expenses_total
            rating_data.append({"info": driver_info, "net_income": net_income, "expenses": dict(expenses_list)})
    sorted_rating = sorted(rating_data, key=lambda x: x['net_income'], reverse=True)[:10]
    text = f"🏆 **Рейтинг водіїв за чистим прибутком** 🏆\n_(за поточний місяць)_\n\n"
    if not sorted_rating:
        text += "Ще немає даних для формування рейтингу в цьому місяці."
    medals = ["🥇", "🥈", "🥉"]
    for i, data in enumerate(sorted_rating):
        place = medals[i] if i < 3 else f"**{i+1}.**"
        name, car, plate = data['info']
        text += f"{place} **{name}** ({car}, {plate})\n"
        text += f"   💰 **Чистий прибуток: {format_currency(data['net_income'])}**\n"
        if data['expenses']:
            text += f"   *Витрати:*\n"
            for exp_type, amount in data['expenses'].items():
                text += f"     - {exp_type.capitalize()}: {format_currency(amount)}\n"
        text += "---\n"
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

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
    field = '_'.join(callback.data.split("_")[2:])
    field_map = {'name': "ім'я", 'car_brand': "марку авто", 'car_plate': "номер авто", 'platform': "платформу"}
    await state.update_data(field_to_edit=field)
    await callback.message.edit_text(f"Введіть нове значення для поля '{field_map[field]}':", reply_markup=get_cancel_keyboard())
    await state.set_state(EditProfile.entering_new_value)
    await callback.answer()

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

@dp.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.clear()
    keyboard = await get_admin_user_list_keyboard()
    await message.answer("Доброго дня, Адміністраторе! 🧑‍🔧\nОберіть водія для керування:", reply_markup=keyboard)
    await state.set_state(AdminEdit.choosing_user)

@dp.callback_query(AdminEdit.choosing_user, F.data.startswith("admin_page_"))
async def admin_paginate_users(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[-1])
    keyboard = await get_admin_user_list_keyboard(page)
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_select_user_"))
async def admin_select_user(callback: CallbackQuery, state: FSMContext, user_id_from_context: int = None):
    user_id_to_edit = user_id_from_context if user_id_from_context else int(callback.data.split("_")[-1])
    await state.update_data(user_to_edit=user_id_to_edit)
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM drivers WHERE user_id = ?", (user_id_to_edit,))
        user_name_result = cursor.fetchone()
        if user_name_result is None:
            await callback.message.edit_text("Помилка: водія не знайдено.")
            await state.clear()
            return
        user_name = user_name_result[0]
    keyboard = await get_admin_user_management_keyboard(user_id_to_edit)
    await callback.message.edit_text(f"Керування водієм: **{user_name}**\nОберіть дію:", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    await state.set_state(AdminEdit.choosing_user)
    await callback.answer()

@dp.callback_query(AdminEdit.choosing_user, F.data == "admin_back_to_list")
async def admin_back_to_list(callback: CallbackQuery, state: FSMContext):
    keyboard = await get_admin_user_list_keyboard()
    await callback.message.edit_text("Оберіть водія для керування:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(AdminEdit.choosing_user, F.data.startswith("admin_edit_profile_"))
async def admin_edit_profile_start(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[-1])
    buttons = [
        [InlineKeyboardButton(text="Ім'я", callback_data="admin_edit_name")],
        [InlineKeyboardButton(text="Авто", callback_data="admin_edit_car_brand")],
        [InlineKeyboardButton(text="Номер", callback_data="admin_edit_car_plate")],
        [InlineKeyboardButton(text="Платформу", callback_data="admin_edit_platform")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_select_user_{user_id}")]
    ]
    await callback.message.edit_text("Яке поле профілю змінити?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(AdminEdit.choosing_field)
    await callback.answer()

@dp.callback_query(AdminEdit.choosing_field, F.data.startswith("admin_edit_"))
async def admin_choose_field(callback: CallbackQuery, state: FSMContext):
    field = '_'.join(callback.data.split("_")[2:])
    field_map = {'name': "ім'я", 'car_brand': "марку авто", 'car_plate': "номер авто", 'platform': "платформу"}
    await state.update_data(field_to_edit=field)
    await callback.message.edit_text(f"Введіть нове значення для поля **'{field_map[field]}'**:", parse_mode=ParseMode.MARKDOWN, reply_markup=get_cancel_keyboard())
    await state.set_state(AdminEdit.entering_new_value)
    await callback.answer()

@dp.message(AdminEdit.entering_new_value)
async def admin_enter_new_value(message: Message, state: FSMContext):
    user_data = await state.get_data()
    field, user_id, new_value = user_data['field_to_edit'], user_data['user_to_edit'], message.text
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE drivers SET {field} = ? WHERE user_id = ?", (new_value, user_id))
        conn.commit()
    await message.answer("✅ Дані водія успішно оновлено!")
    await state.set_state(AdminEdit.choosing_user)
    fake_callback_message = types.Message(message_id=0, date=datetime.now(), chat=message.chat)
    fake_callback = types.CallbackQuery(id="0", from_user=message.from_user, message=fake_callback_message, data="")
    await admin_select_user(fake_callback, state, user_id_from_context=user_id)

@dp.callback_query(AdminEdit.choosing_user, F.data.startswith("admin_manage_finances_"))
async def admin_manage_finances(callback: CallbackQuery, state: FSMContext):
    user_id = (await state.get_data())['user_to_edit']
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, date, type, amount FROM transactions WHERE driver_id = ? ORDER BY date DESC LIMIT 10", (user_id,))
        transactions = cursor.fetchall()
        cursor.execute("SELECT name FROM drivers WHERE user_id=?", (user_id,))
        user_name_result = cursor.fetchone()
        if user_name_result is None: return
        user_name = user_name_result[0]
    text = f"**Останні 10 операцій водія {user_name}:**\n\n"
    if not transactions: text += "Операцій ще не було."
    keyboard = []
    for id, date, type, amount in transactions:
        sign = "🟢" if type in ['дохід', 'чай'] else "🔴"
        date_str = datetime.fromisoformat(date).strftime('%d.%m %H:%M')
        text += f"{sign} {date_str} - {type.capitalize()}: {format_currency(amount)}\n"
        keyboard.append([
            InlineKeyboardButton(text=f"✏️ Ред. №{id}", callback_data=f"admin_edit_trans_{id}"),
            InlineKeyboardButton(text=f"❌ Вид. №{id}", callback_data=f"admin_delete_trans_{id}")
        ])
    keyboard.append([InlineKeyboardButton(text="✅ Додати транзакцію", callback_data=f"admin_add_trans_{user_id}")])
    keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_select_user_{user_id}")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard), parse_mode=ParseMode.MARKDOWN)
    await state.set_state(AdminEdit.managing_finances)
    await callback.answer()

@dp.callback_query(AdminEdit.managing_finances, F.data.startswith("admin_edit_trans_"))
async def admin_edit_transaction_start(callback: CallbackQuery, state: FSMContext):
    transaction_id = int(callback.data.split("_")[-1])
    await state.update_data(transaction_to_edit=transaction_id)
    await callback.message.edit_text("Введіть нову суму для цієї транзакції:", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminEdit.editing_transaction_amount)
    await callback.answer()

@dp.message(AdminEdit.editing_transaction_amount)
async def admin_edit_transaction_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            await message.answer("❌ Сума має бути більшою за нуль.", reply_markup=get_cancel_keyboard())
            return
        user_data = await state.get_data()
        transaction_id = user_data['transaction_to_edit']
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE transactions SET amount = ? WHERE id = ?", (amount, transaction_id))
            conn.commit()
        await message.answer("✅ Суму транзакції успішно оновлено!")
        fake_callback_message = types.Message(message_id=message.message_id + 1, date=datetime.now(), chat=message.chat)
        fake_callback = types.CallbackQuery(id="0", from_user=message.from_user, message=fake_callback_message, data="")
        await state.set_state(AdminEdit.managing_finances)
        await admin_manage_finances(fake_callback, state)
    except ValueError:
        await message.answer("❌ Помилка. Введіть числове значення.", reply_markup=get_cancel_keyboard())

@dp.callback_query(AdminEdit.managing_finances, F.data.startswith("admin_delete_trans_"))
async def admin_delete_transaction(callback: CallbackQuery, state: FSMContext):
    transaction_id = int(callback.data.split("_")[-1])
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
        conn.commit()
    await callback.answer("✅ Транзакцію видалено.", show_alert=True)
    await admin_manage_finances(callback, state)

@dp.callback_query(AdminEdit.managing_finances, F.data.startswith("admin_add_trans_"))
async def admin_add_transaction_start(callback: CallbackQuery, state: FSMContext):
    user_id = (await state.get_data())['user_to_edit']
    buttons = [
        [InlineKeyboardButton(text="💰 Дохід", callback_data="admin_add_type_дохід"), InlineKeyboardButton(text="🎁 Чайові", callback_data="admin_add_type_чай")],
        [InlineKeyboardButton(text="⛽ Паливо", callback_data="admin_add_type_паливо"), InlineKeyboardButton(text="🧼 Мийка", callback_data="admin_add_type_мийка")],
        [InlineKeyboardButton(text="🍔 Їжа", callback_data="admin_add_type_їжа"), InlineKeyboardButton(text="🛠️ Ремонт", callback_data="admin_add_type_ремонт")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_manage_finances_{user_id}")]
    ]
    await callback.message.edit_text("Оберіть тип транзакції для додавання:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(AdminEdit.adding_transaction_type)
    await callback.answer()

@dp.callback_query(AdminEdit.adding_transaction_type, F.data.startswith("admin_add_type_"))
async def admin_add_transaction_type(callback: CallbackQuery, state: FSMContext):
    trans_type = callback.data.split("_")[-1]
    await state.update_data(admin_trans_type=trans_type)
    await callback.message.edit_text(f"Введіть суму для '{trans_type.capitalize()}':", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminEdit.adding_transaction_amount)
    await callback.answer()

@dp.message(AdminEdit.adding_transaction_amount)
async def admin_add_transaction_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(',', '.'))
        if amount <= 0:
            await message.answer("❌ Сума має бути більшою за нуль.", reply_markup=get_cancel_keyboard())
            return
        user_data = await state.get_data()
        user_id = user_data['user_to_edit']
        trans_type = user_data['admin_trans_type']
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO transactions (driver_id, type, amount) VALUES (?, ?, ?)", (user_id, trans_type, amount))
            conn.commit()
        await message.answer("✅ Транзакцію успішно додано!")
        fake_callback_message = types.Message(message_id=message.message_id + 1, date=datetime.now(), chat=message.chat)
        fake_callback = types.CallbackQuery(id="0", from_user=message.from_user, message=fake_callback_message, data=f"admin_manage_finances_{user_id}")
        await state.set_state(AdminEdit.managing_finances)
        await admin_manage_finances(fake_callback, state)
    except ValueError:
        await message.answer("❌ Помилка. Введіть числове значення.", reply_markup=get_cancel_keyboard())

@dp.callback_query(AdminEdit.choosing_user, F.data == "admin_finish")
async def admin_finish(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Ви вийшли з режиму адміністрування.")
    await callback.message.answer("Повернення до головного меню.", reply_markup=get_main_menu_keyboard())
    await callback.answer()

@dp.message(Command("settings"))
async def admin_settings(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'password'")
        current_password = cursor.fetchone()[0]
    text = (f"⚙️ **Панель налаштувань** ⚙️\n\n"
            f"Тут ви можете змінювати основні параметри бота.\n\n"
            f"Поточний пароль для реєстрації: `{current_password}`")
    buttons = [[InlineKeyboardButton(text="🔑 Змінити пароль", callback_data="settings_change_password")]]
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode=ParseMode.MARKDOWN)
    await state.set_state(AdminSettings.choosing_setting)

@dp.callback_query(AdminSettings.choosing_setting, F.data == "settings_change_password")
async def settings_change_password_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Введіть новий пароль для реєстрації водіїв:", reply_markup=get_cancel_keyboard())
    await state.set_state(AdminSettings.entering_new_password)
    await callback.answer()

@dp.message(AdminSettings.entering_new_password)
async def settings_set_new_password(message: Message, state: FSMContext):
    new_password = message.text
    if len(new_password) < 4:
        await message.answer("❌ Пароль занадто короткий. Введіть пароль довжиною мінімум 4 символи.", reply_markup=get_cancel_keyboard())
        return
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE settings SET value = ? WHERE key = 'password'", (new_password,))
        conn.commit()
    await state.clear()
    await message.answer(f"✅ Пароль успішно змінено на `{new_password}`", parse_mode=ParseMode.MARKDOWN)
    await cmd_start(message, state)

async def set_main_menu(bot: Bot):
    main_menu_commands = [
        BotCommand(command="/start", description="Перезапустити бота"),
        BotCommand(command="/menu", description="Показати головне меню"),
        BotCommand(command="/admin", description="Керування водіями (для адміна)"),
        BotCommand(command="/settings", description="Налаштування бота (для адміна)"),
    ]
    await bot.set_my_commands(main_menu_commands)

async def main():
    if not BOT_TOKEN:
        logging.critical("ПОМИЛКА: не знайдено BOT_TOKEN. Перевірте змінні оточення на хостингу.")
        return

    bot = Bot(token=BOT_TOKEN)
    
    dp.callback_query.register(handle_cancel_action, F.data == "action_cancel")
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(show_main_menu, Command("menu"))
    dp.message.register(process_password, Registration.waiting_for_password)
    dp.message.register(process_name, Registration.waiting_for_name)
    dp.message.register(process_car_brand, Registration.waiting_for_car_brand)
    dp.message.register(process_car_plate, Registration.waiting_for_car_plate)
    dp.message.register(process_platform_and_finish_reg, Registration.waiting_for_platform)
    dp.message.register(add_income_menu, F.text == "✅ Додати Дохід/Чайові")
    dp.message.register(add_expense_menu, F.text == "➖ Додати Витрату")
    dp.callback_query.register(process_add_transaction_type, F.data.startswith("add_transaction_"))
    dp.message.register(process_transaction_amount, AddTransaction.waiting_for_amount)
    dp.message.register(show_my_stats, F.text == "📊 Моя Статистика")
    dp.message.register(advanced_stats_menu, F.text == "📈 Розширена статистика")
    dp.callback_query.register(show_advanced_stats, F.data.startswith("stats_period_"))
    dp.message.register(show_rating, F.text == "🏆 Рейтинг Водіїв")
    dp.message.register(show_my_profile, F.text == "👤 Мій Профіль")
    dp.callback_query.register(edit_profile_start, F.data == "edit_profile_start")
    dp.callback_query.register(edit_profile_choose_field, EditProfile.choosing_field, F.data.startswith("edit_field_"))
    dp.message.register(edit_profile_enter_value, EditProfile.entering_new_value)
    dp.message.register(admin_panel, Command("admin"))
    dp.callback_query.register(admin_paginate_users, AdminEdit.choosing_user, F.data.startswith("admin_page_"))
    dp.callback_query.register(admin_select_user, F.data.startswith("admin_select_user_"))
    dp.callback_query.register(admin_back_to_list, AdminEdit.choosing_user, F.data == "admin_back_to_list")
    dp.callback_query.register(admin_edit_profile_start, AdminEdit.choosing_user, F.data.startswith("admin_edit_profile_"))
    dp.callback_query.register(admin_choose_field, AdminEdit.choosing_field, F.data.startswith("admin_edit_"))
    dp.message.register(admin_enter_new_value, AdminEdit.entering_new_value)
    dp.callback_query.register(admin_manage_finances, AdminEdit.choosing_user, F.data.startswith("admin_manage_finances_"))
    dp.callback_query.register(admin_edit_transaction_start, AdminEdit.managing_finances, F.data.startswith("admin_edit_trans_"))
    dp.message.register(admin_edit_transaction_amount, AdminEdit.editing_transaction_amount)
    dp.callback_query.register(admin_delete_transaction, AdminEdit.managing_finances, F.data.startswith("admin_delete_trans_"))
    dp.callback_query.register(admin_add_transaction_start, AdminEdit.managing_finances, F.data.startswith("admin_add_trans_"))
    dp.callback_query.register(admin_add_transaction_type, AdminEdit.adding_transaction_type, F.data.startswith("admin_add_type_"))
    dp.message.register(admin_add_transaction_amount, AdminEdit.adding_transaction_amount)
    dp.callback_query.register(admin_finish, AdminEdit.choosing_user, F.data == "admin_finish")
    dp.message.register(admin_settings, Command("settings"))
    dp.callback_query.register(settings_change_password_prompt, AdminSettings.choosing_setting, F.data == "settings_change_password")
    dp.message.register(settings_set_new_password, AdminSettings.entering_new_password)
    
    init_db()
    await set_main_menu(bot)
    logging.info("Бот запускається...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        # Запускаємо "ширму" в окремому потоці для Render
        flask_thread = Thread(target=run_flask)
        flask_thread.start()
        # Запускаємо основну логіку бота
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот зупинено.")