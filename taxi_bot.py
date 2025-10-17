# taxi_bot.py

import asyncio
import sqlite3
import logging
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# --- НАЛАШТУВАННЯ ---
# Ці дані потрібно буде вказати на хостингу в "Environment Variables"
# Це робить код безпечним, оскільки секретні ключі не зберігаються у файлі.
BOT_TOKEN = os.environ.get("BOT_TOKEN")
REGISTRATION_PASSWORD = os.environ.get("REGISTRATION_PASSWORD", "taxi_driver_2025") # Пароль за замовчуванням
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0)) # Ваш Telegram ID

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
    entering_user_id = State()
    choosing_field = State()
    entering_new_value = State()


# --- КЛАВІАТУРИ ---
def get_main_menu_keyboard():
    """Повертає головне меню з кнопками."""
    buttons = [
        [KeyboardButton(text="✅ Додати Дохід/Чайові"), KeyboardButton(text="➖ Додати Витрату")],
        [KeyboardButton(text="📊 Моя Статистика"), KeyboardButton(text="🏆 Рейтинг Водіїв")],
        [KeyboardButton(text="👤 Мій Профіль")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# --- ОБРОБНИКИ КОМАНД ТА ПОВІДОМЛЕНЬ ---
dp = Dispatcher()

async def is_registered(user_id: int) -> bool:
    """Перевіряє, чи є користувач у базі даних."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM drivers WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None

# --- СТАРТ ТА РЕЄСТРАЦІЯ ---
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обробник команди /start."""
    if await is_registered(message.from_user.id):
        await message.answer(f"З поверненням, {message.from_user.first_name}! 👋", reply_markup=get_main_menu_keyboard())
    else:
        await message.answer("👋 Вітаю у боті для водіїв!\n\nДля початку роботи, будь ласка, введіть пароль для реєстрації:")
        await state.set_state(Registration.waiting_for_password)

@dp.message(Registration.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    """Обробляє введений пароль."""
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
    buttons = [
        [InlineKeyboardButton(text="💰 Дохід", callback_data="add_transaction_дохід")],
        [InlineKeyboardButton(text="🎁 Чайові", callback_data="add_transaction_чай")]
    ]
    await message.answer("Оберіть тип доходу:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.message(F.text == "➖ Додати Витрату")
async def add_expense_menu(message: Message):
    buttons = [
        [InlineKeyboardButton(text="⛽ Паливо", callback_data="add_transaction_паливо"), InlineKeyboardButton(text="🧼 Мийка", callback_data="add_transaction_мийка")],
        [InlineKeyboardButton(text="🍔 Їжа", callback_data="add_transaction_їжа"), InlineKeyboardButton(text="🛠️ Ремонт", callback_data="add_transaction_ремонт")],
        [InlineKeyboardButton(text="Інше", callback_data="add_transaction_інше")]
    ]
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
            cursor.execute(
                "INSERT INTO transactions (driver_id, type, amount) VALUES (?, ?, ?)",
                (message.from_user.id, transaction_type, amount)
            )
            conn.commit()
        
        await message.answer(f"✅ Успішно додано: **{transaction_type.capitalize()}** на суму **{amount:.2f} грн**.", parse_mode="Markdown")
        await state.clear()
    except ValueError:
        await message.answer("❌ Помилка. Будь ласка, введіть числове значення (напр., 150 або 95.50).")


# --- СТАТИСТИКА ТА РЕЙТИНГ ---
@dp.message(F.text == "📊 Моя Статистика")
async def show_my_stats(message: Message):
    user_id = message.from_user.id
    current_month = datetime.now().strftime('%Y-%m')
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # Статистика за поточний місяць
        cursor.execute("""
            SELECT type, SUM(amount) FROM transactions
            WHERE driver_id = ? AND strftime('%Y-%m', date) = ?
            GROUP BY type
        """, (user_id, current_month))
        monthly_stats = cursor.fetchall()
        
        # Статистика за весь час
        cursor.execute("SELECT type, SUM(amount) FROM transactions WHERE driver_id = ? GROUP BY type", (user_id,))
        total_stats = cursor.fetchall()

    def format_stats(title, stats):
        text = f"**{title}**\n"
        income = sum(amt for type, amt in stats if type in ['дохід', 'чай'])
        expenses = sum(amt for type, amt in stats if type not in ['дохід', 'чай'])
        if not stats: return f"**{title}**\nНемає даних.\n"
        
        text += f"🟢 **Зароблено:** {income:.2f} грн\n"
        text += f"🔴 **Витрачено:** {expenses:.2f} грн\n"
        text += f"💰 **Чистий прибуток:** {(income - expenses):.2f} грн\n\n"
        text += "Деталізація:\n"
        for type, amount in stats:
            text += f" - {type.capitalize()}: {amount:.2f} грн\n"
        return text

    await message.answer(
        f"{format_stats('🗓️ Статистика за поточний місяць', monthly_stats)}\n---\n{format_stats('🕰️ Статистика за весь час', total_stats)}",
        parse_mode="Markdown"
    )

@dp.message(F.text == "🏆 Рейтинг Водіїв")
async def show_rating(message: Message):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        current_month = datetime.now().strftime('%Y-%m')

        # Рейтинг за поточний місяць
        cursor.execute("""
            SELECT d.name, SUM(t.amount)
            FROM transactions t JOIN drivers d ON t.driver_id = d.user_id
            WHERE t.type IN ('дохід', 'чай') AND strftime('%Y-%m', t.date) = ?
            GROUP BY d.user_id ORDER BY SUM(t.amount) DESC LIMIT 10
        """, (current_month,))
        monthly_rating = cursor.fetchall()

        # Рейтинг за весь час
        cursor.execute("""
            SELECT d.name, SUM(t.amount)
            FROM transactions t JOIN drivers d ON t.driver_id = d.user_id
            WHERE t.type IN ('дохід', 'чай')
            GROUP BY d.user_id ORDER BY SUM(t.amount) DESC LIMIT 10
        """)
        all_time_rating = cursor.fetchall()

    def format_rating(title, rating_data):
        text = f"**{title}**\n"
        if not rating_data: return text + "Ще немає даних для рейтингу.\n"
        
        medals = ["🥇", "🥈", "🥉"]
        for i, (name, total) in enumerate(rating_data):
            place = medals[i] if i < 3 else f" {i+1}. "
            text += f"{place} {name} - {total:.2f} грн\n"
        return text

    await message.answer(
        f"🏆 **Рейтинг заробітку водіїв** 🏆\n\n"
        f"{format_rating('🗓️ За Поточний Місяць', monthly_rating)}\n---\n"
        f"{format_rating('🕰️ За Весь Час', all_time_rating)}",
        parse_mode="Markdown"
    )

# --- ПРОФІЛЬ ---
@dp.message(F.text == "👤 Мій Профіль")
async def show_my_profile(message: Message):
    user_id = message.from_user.id
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, car_brand, car_plate, platform FROM drivers WHERE user_id = ?", (user_id,))
        profile = cursor.fetchone()

    if profile:
        name, car_brand, car_plate, platform = profile
        text = (f"**👤 Ваш профіль:**\n\n"
                f"**Ім'я:** {name}\n"
                f"**Авто:** {car_brand}\n"
                f"**Номер:** {car_plate}\n"
                f"**Платформа:** {platform}\n\n"
                f"Бажаєте змінити дані?")
        buttons = [[InlineKeyboardButton(text="✏️ Редагувати профіль", callback_data="edit_profile_start")]]
        await message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await message.answer("Не вдалося знайти ваш профіль.")

@dp.callback_query(F.data == "edit_profile_start")
async def edit_profile_start(callback: CallbackQuery, state: FSMContext):
    buttons = [
        [InlineKeyboardButton(text="Ім'я", callback_data="edit_field_name")],
        [InlineKeyboardButton(text="Авто", callback_data="edit_field_car_brand")],
        [InlineKeyboardButton(text="Номер", callback_data="edit_field_car_plate")],
        [InlineKeyboardButton(text="Платформу", callback_data="edit_field_platform")],
    ]
    await callback.message.edit_text("Яке поле ви хочете змінити?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.set_state(EditProfile.choosing_field)
    await callback.answer()

@dp.callback_query(EditProfile.choosing_field, F.data.startswith("edit_field_"))
async def edit_profile_choose_field(callback: CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[-1]
    field_map = {
        'name': "ім'я", 'car_brand': "марку авто", 'car_plate': "номер авто", 'platform': "платформу"
    }
    await state.update_data(field_to_edit=field)
    await callback.message.edit_text(f"Введіть нове значення для поля '{field_map[field]}':")
    await state.set_state(EditProfile.entering_new_value)
    await callback.answer()

@dp.message(EditProfile.entering_new_value)
async def edit_profile_enter_value(message: Message, state: FSMContext):
    user_data = await state.get_data()
    field = user_data['field_to_edit']
    new_value = message.text
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # Важливо: використовуйте параметризовані запити для безпеки
        cursor.execute(f"UPDATE drivers SET {field} = ? WHERE user_id = ?", (new_value, message.from_user.id))
        conn.commit()
    
    await message.answer("✅ Дані успішно оновлено!")
    await state.clear()
    await show_my_profile(message) # Показати оновлений профіль


# --- АДМІН-ПАНЕЛЬ ---
@dp.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Вітаю, Адміністраторе! Введіть User ID водія, якого потрібно редагувати:")
    await state.set_state(AdminEdit.entering_user_id)


async def main():
    """Головна функція для запуску бота."""
    if not BOT_TOKEN:
        logging.critical("Помилка: не знайдено BOT_TOKEN. Перевірте змінні оточення.")
        return

    bot = Bot(token=BOT_TOKEN)
    init_db()  # Ініціалізуємо базу даних при старті
    
    logging.info("Бот запускається...")
    await dp.start_polling(bot)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот зупинено вручну.")