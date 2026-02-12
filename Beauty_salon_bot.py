"""
Телеграм-бот салона красоты с админ-панелью
Версия 4.1 - Обновлённая версия

ОБНОВЛЕНИЯ в версии 4.1:
- ✅ Добавлен сбор номера телефона с кнопкой "Отправить номер"
- ✅ Админ видит номера телефонов клиентов
- ✅ Username показывается только если есть, иначе скрывается
- ✅ Админ добавляет клиентов без Telegram ID (автогенерация)
- ✅ Кнопки "Назад" везде где нужно
- ✅ Гарантированная отправка уведомлений админу
- ✅ У клиента одно сообщение обновляется (чистый чат)

Установка:
pip install aiogram aiosqlite

Запуск:
python beauty_salon_bot.py

ВАЖНО: Настройте ADMIN_ID в файле config.py!

При обновлении бота:
1. Замените beauty_salon_bot.py и config.py
2. НЕ ТРОГАЙТЕ database.py и beauty_salon.db
3. Все данные сохранятся!
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta
from typing import List, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, 
    CallbackQuery,
    ReplyKeyboardMarkup, 
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Импортируем наши модули
from databas23e import db
from confi23g import (
    BOT_TOKEN, ADMIN_ID, SERVICES, ALL_TIME_SLOTS,
    BOOKING_DAYS_AHEAD, WELCOME_MESSAGE, ADMIN_WELCOME_MESSAGE,
    INFO_MESSAGE, SALON_NAME, SALON_ADDRESS, SALON_PHONE, SALON_HOURS
)

# ============================================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Глобальная переменная для бота
bot_instance: Optional[Bot] = None

# ============================================================================
# FSM СОСТОЯНИЯ
# ============================================================================

class BookingStates(StatesGroup):
    """Состояния процесса записи клиента"""
    choosing_service = State()
    choosing_date = State()
    choosing_time = State()
    entering_phone = State()

class RescheduleStates(StatesGroup):
    """Состояния процесса переноса записи"""
    choosing_date = State()
    choosing_time = State()

class AdminAddClientStates(StatesGroup):
    """Состояния добавления клиента админом"""
    entering_name = State()
    entering_phone = State()
    choosing_service = State()
    choosing_date = State()
    choosing_time = State()

class AdminDeleteClientStates(StatesGroup):
    """Состояния удаления клиента админом"""
    entering_booking_id = State()

# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def is_admin(user_id: int) -> bool:
    """Проверка администратора"""
    return user_id == ADMIN_ID


async def send_admin_notification(text: str):
    """
    Отправка уведомления администратору с гарантией доставки
    Делает 3 попытки с задержкой между ними
    """
    if not bot_instance:
        logger.error("❌ bot_instance не инициализирован!")
        return
        
    if not ADMIN_ID:
        logger.error("❌ ADMIN_ID не настроен в config.py!")
        return
    
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            await bot_instance.send_message(
                chat_id=ADMIN_ID,
                text=f"🔔 <b>Уведомление</b>\n\n{text}",
                parse_mode="HTML"
            )
            logger.info(f"✅ Уведомление отправлено админу (попытка {attempt + 1})")
            return  # Успешно отправлено
        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления (попытка {attempt + 1}): {e}")
            if attempt < max_attempts - 1:
                await asyncio.sleep(1)  # Пауза перед повтором
    
    logger.error(f"❌ Не удалось отправить уведомление после {max_attempts} попыток")


def format_booking_text(booking: dict) -> str:
    """Форматирование информации о записи"""
    date_obj = datetime.strptime(booking['booking_date'], '%Y-%m-%d')
    date_str = date_obj.strftime('%d.%m.%Y')
    
    return (
        f"Услуга: {booking['service']}\n"
        f"📅 Дата: {date_str}\n"
        f"🕐 Время: {booking['booking_time']}"
    )


def format_user_info(booking: dict) -> str:
    """Форматирование информации о пользователе для админа"""
    info = f"👤 Клиент: {booking.get('first_name', 'Н/Д')} {booking.get('last_name', '')}\n"
    info += f"🆔 ID: {booking['user_id']}\n"
    
    # Показываем username только если он есть и не пустой
    username = booking.get('username', '')
    if username and username not in ['None', '', 'admin_added']:
        info += f"📱 Username: @{username}\n"
    
    # Показываем телефон если есть
    phone = booking.get('phone', '')
    if phone and phone not in ['None', '']:
        info += f"📞 Телефон: {phone}"
    else:
        info += f"📞 Телефон: не указан"
    
    return info


def generate_random_user_id() -> int:
    """Генерация случайного user_id для клиентов, добавленных админом"""
    return random.randint(900000000, 999999999)

# ============================================================================
# КЛАВИАТУРЫ
# ============================================================================

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню для клиентов"""
    keyboard = [
        [KeyboardButton(text="📝 Записаться")],
        [KeyboardButton(text="📋 Мои записи"), KeyboardButton(text="⭐ Отзывы")],
        [KeyboardButton(text="ℹ️ Информация")]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )


def get_admin_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню для администратора"""
    keyboard = [
        [KeyboardButton(text="➕ Добавить клиента")],
        [KeyboardButton(text="🗑️ Удалить клиента"), KeyboardButton(text="👥 Просмотр клиентов")],
        [KeyboardButton(text="📊 Аналитика")],
        [KeyboardButton(text="👤 Режим клиента")]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Админ-панель..."
    )


def get_phone_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для отправки номера телефона с кнопкой"""
    keyboard = [
        [KeyboardButton(text="📱 Отправить мой номер", request_contact=True)],
        [KeyboardButton(text="⬅️ Назад")]
    ]
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Нажмите кнопку или введите номер"
    )


def get_services_keyboard(with_back: bool = True) -> InlineKeyboardMarkup:
    """Клавиатура с услугами"""
    buttons = []
    for idx, service in enumerate(SERVICES):
        buttons.append([
            InlineKeyboardButton(text=service, callback_data=f"service_{idx}")
        ])
    
    if with_back:
        buttons.append([
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_start")
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_dates_keyboard(days_ahead: int = 7, with_back: bool = True) -> InlineKeyboardMarkup:
    """Клавиатура с датами"""
    buttons = []
    today = datetime.now()
    
    weekdays = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Вс"}
    
    for i in range(days_ahead):
        date = today + timedelta(days=i)
        date_str = date.strftime("%d.%m.%Y")
        weekday = weekdays[date.weekday()]
        
        buttons.append([
            InlineKeyboardButton(
                text=f"{weekday} {date_str}",
                callback_data=f"date_{date.strftime('%Y%m%d')}"
            )
        ])
    
    if with_back:
        buttons.append([
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_service")
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def get_time_keyboard(booking_date: str, with_back: bool = True) -> InlineKeyboardMarkup:
    """Клавиатура с доступными временными слотами"""
    occupied_slots = await db.get_occupied_slots(booking_date)
    available_slots = [slot for slot in ALL_TIME_SLOTS if slot not in occupied_slots]
    
    buttons = []
    for i in range(0, len(available_slots), 2):
        row = []
        for j in range(2):
            if i + j < len(available_slots):
                slot = available_slots[i + j]
                row.append(InlineKeyboardButton(text=f"✅ {slot}", callback_data=f"time_{slot}"))
        if row:
            buttons.append(row)
    
    if not buttons:
        buttons.append([
            InlineKeyboardButton(text="❌ Нет свободных слотов", callback_data="no_slots")
        ])
    
    if with_back:
        buttons.append([
            InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_date")
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def get_bookings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для управления записями"""
    bookings_list = await db.get_user_bookings(user_id)
    
    buttons = []
    for idx, booking in enumerate(bookings_list):
        buttons.append([
            InlineKeyboardButton(text=f"❌ Отменить #{idx + 1}", callback_data=f"cancel_{booking['id']}"),
            InlineKeyboardButton(text=f"🔄 Перенести #{idx + 1}", callback_data=f"reschedule_{booking['id']}")
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ============================================================================
# ОБРАБОТЧИКИ ДЛЯ КЛИЕНТОВ
# ============================================================================

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    await state.clear()
    
    user_id = message.from_user.id
    
    if is_admin(user_id):
        welcome_text = ADMIN_WELCOME_MESSAGE
        keyboard = get_admin_keyboard()
    else:
        welcome_text = WELCOME_MESSAGE.format(salon_name=SALON_NAME)
        keyboard = get_main_keyboard()
    
    await message.answer(text=welcome_text, reply_markup=keyboard)


@router.message(F.text == "👤 Режим клиента")
async def switch_to_client_mode(message: Message, state: FSMContext):
    """Переключение админа в режим клиента"""
    if not is_admin(message.from_user.id):
        return
    
    await state.clear()
    await message.answer(
        text="👤 Режим клиента активирован\n\nИспользуйте /admin для возврата",
        reply_markup=get_main_keyboard()
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    """Команда для входа в админ-панель"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав администратора")
        return
    
    await state.clear()
    await message.answer(text=ADMIN_WELCOME_MESSAGE, reply_markup=get_admin_keyboard())


@router.message(F.text == "📝 Записаться")
async def start_booking(message: Message, state: FSMContext):
    """Начало процесса записи"""
    await state.set_state(BookingStates.choosing_service)
    
    sent_message = await message.answer(
        text="🎯 Выберите услугу:",
        reply_markup=get_services_keyboard()
    )
    await state.update_data(last_message_id=sent_message.message_id)


@router.message(F.text == "📋 Мои записи")
async def show_my_bookings(message: Message):
    """Показ записей пользователя"""
    user_id = message.from_user.id
    bookings_list = await db.get_user_bookings(user_id)
    
    if not bookings_list:
        await message.answer(
            text="📭 У вас пока нет записей.\n\nНажмите '📝 Записаться' чтобы создать запись!",
            reply_markup=get_main_keyboard()
        )
        return
    
    text = "📋 Ваши записи:\n\n"
    for idx, booking in enumerate(bookings_list):
        date_obj = datetime.strptime(booking['booking_date'], '%Y-%m-%d')
        date_str = date_obj.strftime('%d.%m.%Y')
        
        text += f"{idx + 1}. {booking['service']}\n"
        text += f"   📅 {date_str} в {booking['booking_time']}\n\n"
    
    await message.answer(text=text, reply_markup=await get_bookings_keyboard(user_id))


@router.message(F.text == "⭐ Отзывы")
async def show_reviews(message: Message):
    """Раздел отзывов"""
    await message.answer(
        text=(
            "⭐ Раздел отзывов скоро будет добавлен! 😊\n\n"
            "Здесь вы сможете:\n"
            "• Просматривать отзывы других клиентов\n"
            "• Оставлять свои отзывы после посещения\n"
            "• Оценивать качество услуг\n"
            "• Делиться фото результата"
        ),
        reply_markup=get_main_keyboard()
    )


@router.message(F.text == "ℹ️ Информация")
async def show_info(message: Message):
    """Информация о салоне"""
    services_list = "\n".join([f"  {service}" for service in SERVICES])
    
    info_text = INFO_MESSAGE.format(
        salon_name=SALON_NAME,
        address=SALON_ADDRESS,
        phone=SALON_PHONE,
        hours=SALON_HOURS,
        services=services_list
    )
    
    await message.answer(text=info_text, reply_markup=get_main_keyboard())

# ============================================================================
# ОБРАБОТЧИКИ ЗАПИСИ (КЛИЕНТЫ)
# ============================================================================

@router.callback_query(F.data == "back_to_start")
async def back_to_start(callback: CallbackQuery, state: FSMContext):
    """Возврат в начало"""
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(text="Выберите действие:", reply_markup=get_main_keyboard())
    await callback.answer()


@router.callback_query(F.data == "back_to_service")
async def back_to_service(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору услуги"""
    await state.set_state(BookingStates.choosing_service)
    await callback.message.edit_text(text="🎯 Выберите услугу:", reply_markup=get_services_keyboard())
    await callback.answer()


@router.callback_query(F.data == "back_to_date")
async def back_to_date(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору даты"""
    data = await state.get_data()
    service = data.get('selected_service', 'Услуга')
    
    await state.set_state(BookingStates.choosing_date)
    await callback.message.edit_text(
        text=f"Услуга: {service}\n\n📅 Выберите дату:",
        reply_markup=get_dates_keyboard(BOOKING_DAYS_AHEAD)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("service_"))
async def process_service_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора услуги"""
    service_idx = int(callback.data.split("_")[1])
    selected_service = SERVICES[service_idx]
    
    await state.update_data(selected_service=selected_service)
    await state.set_state(BookingStates.choosing_date)
    
    await callback.message.edit_text(
        text=f"Услуга: {selected_service}\n\n📅 Выберите дату:",
        reply_markup=get_dates_keyboard(BOOKING_DAYS_AHEAD)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("date_"), BookingStates.choosing_date)
async def process_date_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора даты"""
    date_str = callback.data.split("_")[1]
    selected_date = datetime.strptime(date_str, "%Y%m%d")
    
    booking_date = selected_date.strftime("%Y-%m-%d")
    await state.update_data(selected_date=selected_date, booking_date=booking_date)
    await state.set_state(BookingStates.choosing_time)
    
    data = await state.get_data()
    service = data.get('selected_service')
    
    time_keyboard = await get_time_keyboard(booking_date)
    
    await callback.message.edit_text(
        text=f"Услуга: {service}\nДата: {selected_date.strftime('%d.%m.%Y')}\n\n🕐 Выберите время:",
        reply_markup=time_keyboard
    )
    await callback.answer()


@router.callback_query(F.data == "no_slots")
async def process_no_slots(callback: CallbackQuery):
    """Обработка нажатия на 'Нет свободных слотов'"""
    await callback.answer(text="Все слоты заняты. Выберите другую дату.", show_alert=True)


@router.callback_query(F.data.startswith("time_"), BookingStates.choosing_time)
async def process_time_selection(callback: CallbackQuery, state: FSMContext):
    """Выбор времени - переход к вводу номера"""
    selected_time = callback.data.split("_")[1]
    
    await state.update_data(selected_time=selected_time)
    await state.set_state(BookingStates.entering_phone)
    
    data = await state.get_data()
    service = data.get('selected_service')
    selected_date = data.get('selected_date')
    
    await callback.message.edit_text(
        text=(
            f"Услуга: {service}\n"
            f"Дата: {selected_date.strftime('%d.%m.%Y')}\n"
            f"Время: {selected_time}\n\n"
            f"📱 Отправьте ваш номер телефона:"
        )
    )
    
    await callback.message.answer(
        text="👇 Нажмите кнопку или введите номер:",
        reply_markup=get_phone_keyboard()
    )
    await callback.answer()


@router.message(F.text == "⬅️ Назад", BookingStates.entering_phone)
async def back_from_phone(message: Message, state: FSMContext):
    """Возврат от ввода номера"""
    data = await state.get_data()
    service = data.get('selected_service')
    selected_date = data.get('selected_date')
    booking_date = data.get('booking_date')
    
    await state.set_state(BookingStates.choosing_time)
    
    time_keyboard = await get_time_keyboard(booking_date)
    
    await message.answer(
        text=f"Услуга: {service}\nДата: {selected_date.strftime('%d.%m.%Y')}\n\n🕐 Выберите время:",
        reply_markup=time_keyboard
    )


@router.message(F.contact, BookingStates.entering_phone)
async def process_phone_contact(message: Message, state: FSMContext):
    """Обработка отправки номера через кнопку"""
    phone = message.contact.phone_number
    if not phone.startswith('+'):
        phone = f"+{phone}"
    await finalize_booking(message, state, phone)


@router.message(F.text, BookingStates.entering_phone)
async def process_phone_text(message: Message, state: FSMContext):
    """Обработка ввода номера вручную"""
    phone = message.text.strip()
    
    if len(phone) < 10:
        await message.answer(
            text="❌ Номер слишком короткий. Попробуйте ещё раз:",
            reply_markup=get_phone_keyboard()
        )
        return
    
    if not phone.startswith('+'):
        phone = f"+{phone}"
    
    await finalize_booking(message, state, phone)


async def finalize_booking(message: Message, state: FSMContext, phone: str):
    """Финальное создание записи"""
    data = await state.get_data()
    service = data.get('selected_service')
    booking_date = data.get('booking_date')
    selected_date = data.get('selected_date')
    selected_time = data.get('selected_time')
    
    user = message.from_user
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or ""
    last_name = user.last_name or ""
    
    success = await db.add_booking(
        user_id=user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        service=service,
        booking_date=booking_date,
        booking_time=selected_time,
        phone=phone
    )
    
    await state.clear()
    
    if success:
        confirmation_text = (
            "✅ Запись успешно создана!\n\n"
            f"Услуга: {service}\n"
            f"Дата: {selected_date.strftime('%d.%m.%Y')}\n"
            f"Время: {selected_time}\n"
            f"Телефон: {phone}\n\n"
            f"Мы ждём вас! 😊"
        )
        
        # Уведомление админу
        username_display = f"@{username}" if username else "нет"
        admin_notification = (
            f"📝 <b>Новая запись</b>\n\n"
            f"👤 {first_name} {last_name}\n"
            f"🆔 ID: {user_id}\n"
            f"📱 Username: {username_display}\n"
            f"📞 Телефон: {phone}\n\n"
            f"💼 {service}\n"
            f"📅 {selected_date.strftime('%d.%m.%Y')}\n"
            f"🕐 {selected_time}"
        )
        await send_admin_notification(admin_notification)
    else:
        confirmation_text = "❌ Это время только что заняли!\n\nПопробуйте другое."
    
    await message.answer(text=confirmation_text, reply_markup=get_main_keyboard())


@router.callback_query(F.data.startswith("cancel_"))
async def process_cancel_booking(callback: CallbackQuery):
    """Отмена записи"""
    booking_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    booking = await db.get_booking_by_id(booking_id)
    
    if not booking:
        await callback.answer(text="❌ Запись не найдена", show_alert=True)
        return
    
    deleted = await db.delete_booking(booking_id, user_id)
    
    if deleted:
        cancel_text = f"❌ Запись отменена:\n\n{format_booking_text(booking)}\n\n🆓 Слот свободен!"
        
        # Уведомление админу
        date_obj = datetime.strptime(booking['booking_date'], '%Y-%m-%d')
        admin_notification = (
            f"❌ <b>Отмена записи</b>\n\n"
            f"{format_user_info(booking)}\n\n"
            f"💼 {booking['service']}\n"
            f"📅 {date_obj.strftime('%d.%m.%Y')}\n"
            f"🕐 {booking['booking_time']}"
        )
        await send_admin_notification(admin_notification)
        
        await callback.message.edit_text(text=cancel_text)
        await callback.answer(text="✅ Отменено")
    else:
        await callback.answer(text="❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("reschedule_"))
async def process_reschedule_booking(callback: CallbackQuery, state: FSMContext):
    """Начало переноса"""
    booking_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    booking = await db.get_booking_by_id(booking_id)
    
    if not booking or booking['user_id'] != user_id:
        await callback.answer(text="❌ Запись не найдена", show_alert=True)
        return
    
    await state.update_data(
        reschedule_booking_id=booking_id,
        old_service=booking['service'],
        old_date=booking['booking_date'],
        old_time=booking['booking_time'],
        old_booking=booking
    )
    
    await state.set_state(RescheduleStates.choosing_date)
    
    await callback.message.edit_text(
        text=f"🔄 Перенос:\n\n{format_booking_text(booking)}\n\n📅 Новая дата:",
        reply_markup=get_dates_keyboard(BOOKING_DAYS_AHEAD, with_back=False)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("date_"), RescheduleStates.choosing_date)
async def process_reschedule_date(callback: CallbackQuery, state: FSMContext):
    """Выбор новой даты"""
    date_str = callback.data.split("_")[1]
    new_date = datetime.strptime(date_str, "%Y%m%d")
    
    booking_date = new_date.strftime("%Y-%m-%d")
    await state.update_data(new_date=new_date, new_booking_date=booking_date)
    await state.set_state(RescheduleStates.choosing_time)
    
    data = await state.get_data()
    service = data.get('old_service')
    
    time_keyboard = await get_time_keyboard(booking_date, with_back=False)
    
    await callback.message.edit_text(
        text=f"🔄 Перенос:\n\nУслуга: {service}\nНовая дата: {new_date.strftime('%d.%m.%Y')}\n\n🕐 Время:",
        reply_markup=time_keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("time_"), RescheduleStates.choosing_time)
async def process_reschedule_time(callback: CallbackQuery, state: FSMContext):
    """Финал переноса"""
    new_time = callback.data.split("_")[1]
    
    data = await state.get_data()
    booking_id = data.get('reschedule_booking_id')
    service = data.get('old_service')
    old_date = data.get('old_date')
    old_time = data.get('old_time')
    new_booking_date = data.get('new_booking_date')
    new_date = data.get('new_date')
    old_booking = data.get('old_booking')
    
    user = callback.from_user
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or ""
    last_name = user.last_name or ""
    phone = old_booking.get('phone', '')
    
    deleted = await db.delete_booking(booking_id, user_id)
    
    if not deleted:
        await callback.answer(text="❌ Ошибка", show_alert=True)
        await state.clear()
        return
    
    success = await db.add_booking(
        user_id=user_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        service=service,
        booking_date=new_booking_date,
        booking_time=new_time,
        phone=phone
    )
    
    await state.clear()
    
    if success:
        old_date_obj = datetime.strptime(old_date, '%Y-%m-%d')
        
        confirmation_text = (
            "✅ Запись перенесена!\n\n"
            f"Было: {old_date_obj.strftime('%d.%m.%Y')} в {old_time}\n"
            f"Стало: {new_date.strftime('%d.%m.%Y')} в {new_time}\n\n"
            f"Услуга: {service}"
        )
        
        # Уведомление админу
        username_display = f"@{username}" if username else "нет"
        admin_notification = (
            f"🔄 <b>Перенос</b>\n\n"
            f"👤 {first_name} {last_name}\n"
            f"🆔 {user_id}\n"
            f"📱 {username_display}\n"
            f"📞 {phone if phone else 'нет'}\n\n"
            f"Было: {old_date_obj.strftime('%d.%m.%Y')} {old_time}\n"
            f"Стало: {new_date.strftime('%d.%m.%Y')} {new_time}\n"
            f"💼 {service}"
        )
        await send_admin_notification(admin_notification)
    else:
        confirmation_text = "❌ Новое время занято!\n\nСтарая запись отменена."
    
    await callback.message.edit_text(text=confirmation_text)
    await callback.answer()

# ============================================================================
# АДМИН-ПАНЕЛЬ
# ============================================================================

@router.message(F.text == "➕ Добавить клиента")
async def admin_add_client_start(message: Message, state: FSMContext):
    """Админ: добавление клиента"""
    if not is_admin(message.from_user.id):
        return
    
    await state.set_state(AdminAddClientStates.entering_name)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin_cancel")]
    ])
    
    await message.answer(text="➕ Добавление клиента\n\nВведите имя клиента:", reply_markup=keyboard)


@router.callback_query(F.data == "admin_cancel")
async def admin_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена действия админа"""
    await state.clear()
    await callback.message.delete()
    await callback.message.answer(text="❌ Отменено", reply_markup=get_admin_keyboard())
    await callback.answer()


@router.message(AdminAddClientStates.entering_name)
async def admin_add_client_name(message: Message, state: FSMContext):
    """Админ: имя клиента"""
    name_parts = message.text.strip().split()
    first_name = name_parts[0] if name_parts else "Клиент"
    last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
    
    await state.update_data(first_name=first_name, last_name=last_name)
    await state.set_state(AdminAddClientStates.entering_phone)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="skip_phone")],
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin_cancel")]
    ])
    
    await message.answer(
        text=f"👤 {first_name} {last_name}\n\n📞 Введите телефон\n(или пропустите):",
        reply_markup=keyboard
    )


@router.callback_query(F.data == "skip_phone", AdminAddClientStates.entering_phone)
async def admin_skip_phone(callback: CallbackQuery, state: FSMContext):
    """Пропуск телефона"""
    await state.update_data(phone=None)
    await state.set_state(AdminAddClientStates.choosing_service)
    await callback.message.edit_text(text="🎯 Выберите услугу:", reply_markup=get_services_keyboard(with_back=False))
    await callback.answer()


@router.message(AdminAddClientStates.entering_phone)
async def admin_add_client_phone(message: Message, state: FSMContext):
    """Админ: теле
фон"""
    phone = message.text.strip()
    if not phone.startswith('+'):
        phone = f"+{phone}"
    
    await state.update_data(phone=phone)
    await state.set_state(AdminAddClientStates.choosing_service)
    
    await message.answer(text="🎯 Выберите услугу:", reply_markup=get_services_keyboard(with_back=False))


@router.callback_query(F.data.startswith("service_"), AdminAddClientStates.choosing_service)
async def admin_add_client_service(callback: CallbackQuery, state: FSMContext):
    """Админ: услуга"""
    service_idx = int(callback.data.split("_")[1])
    selected_service = SERVICES[service_idx]
    
    await state.update_data(selected_service=selected_service)
    await state.set_state(AdminAddClientStates.choosing_date)
    
    await callback.message.edit_text(
        text=f"Услуга: {selected_service}\n\n📅 Дата:",
        reply_markup=get_dates_keyboard(BOOKING_DAYS_AHEAD, with_back=False)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("date_"), AdminAddClientStates.choosing_date)
async def admin_add_client_date(callback: CallbackQuery, state: FSMContext):
    """Админ: дата"""
    date_str = callback.data.split("_")[1]
    selected_date = datetime.strptime(date_str, "%Y%m%d")
    
    booking_date = selected_date.strftime("%Y-%m-%d")
    await state.update_data(selected_date=selected_date, booking_date=booking_date)
    await state.set_state(AdminAddClientStates.choosing_time)
    
    data = await state.get_data()
    service = data.get('selected_service')
    
    time_keyboard = await get_time_keyboard(booking_date, with_back=False)
    
    await callback.message.edit_text(
        text=f"Услуга: {service}\nДата: {selected_date.strftime('%d.%m.%Y')}\n\n🕐 Время:",
        reply_markup=time_keyboard
    )
    await callback.answer()


@router.callback_query(F.data.startswith("time_"), AdminAddClientStates.choosing_time)
async def admin_add_client_time(callback: CallbackQuery, state: FSMContext):
    """Админ: финал"""
    selected_time = callback.data.split("_")[1]
    
    data = await state.get_data()
    first_name = data.get('first_name')
    last_name = data.get('last_name', '')
    phone = data.get('phone')
    service = data.get('selected_service')
    booking_date = data.get('booking_date')
    selected_date = data.get('selected_date')
    
    # Генерируем ID
    generated_user_id = generate_random_user_id()
    
    success = await db.add_booking(
        user_id=generated_user_id,
        username="admin_added",
        first_name=first_name,
        last_name=last_name,
        service=service,
        booking_date=booking_date,
        booking_time=selected_time,
        phone=phone
    )
    
    await state.clear()
    
    if success:
        result_text = (
            "✅ Клиент добавлен!\n\n"
            f"👤 {first_name} {last_name}\n"
            f"📞 {phone if phone else 'нет'}\n"
            f"💼 {service}\n"
            f"📅 {selected_date.strftime('%d.%m.%Y')}\n"
            f"🕐 {selected_time}"
        )
    else:
        result_text = "❌ Слот занят"
    
    await callback.message.edit_text(text=result_text)
    await callback.message.answer(text="Что ещё?", reply_markup=get_admin_keyboard())
    await callback.answer()


@router.message(F.text == "🗑️ Удалить клиента")
async def admin_delete_client_start(message: Message, state: FSMContext):
    """Админ: удаление"""
    if not is_admin(message.from_user.id):
        return
    
    await state.set_state(AdminDeleteClientStates.entering_booking_id)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Отмена", callback_data="admin_cancel")]
    ])
    
    await message.answer(
        text="🗑️ Удаление\n\nВведите ID записи:",
        reply_markup=keyboard
    )


@router.message(AdminDeleteClientStates.entering_booking_id)
async def admin_delete_client_execute(message: Message, state: FSMContext):
    """Админ: выполнение удаления"""
    try:
        booking_id = int(message.text)
        booking = await db.get_booking_by_id(booking_id)
        if not booking:
            await message.answer("❌ Не найдено", reply_markup=get_admin_keyboard())
            await state.clear()
            return
        
        deleted = await db.delete_booking(booking_id, user_id=None)
        
        if deleted:
            await message.answer(
                text=f"✅ Удалено #{booking_id}\n\n{format_user_info(booking)}\n\n{format_booking_text(booking)}",
                reply_markup=get_admin_keyboard()
            )
        else:
            await message.answer("❌ Ошибка", reply_markup=get_admin_keyboard())
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Неверный ID")


@router.message(F.text == "👥 Просмотр клиентов")
async def admin_view_clients(message: Message):
    """Админ: просмотр всех"""
    if not is_admin(message.from_user.id):
        return
    
    bookings = await db.get_all_bookings()
    
    if not bookings:
        await message.answer(text="📭 Записей нет", reply_markup=get_admin_keyboard())
        return
    
    text = "👥 Все записи:\n\n"
    
    for booking in bookings:
        date_obj = datetime.strptime(booking['booking_date'], '%Y-%m-%d')
        
        username = booking.get('username', '')
        username_display = f"@{username}" if username and username not in ['None', '', 'admin_added'] else "нет"
        
        phone = booking.get('phone', '')
        phone_display = phone if phone and phone != 'None' else "нет"
        
        text += f"━━━━━━━━━━━━━\n"
        text += f"🆔 ID: {booking['id']}\n"
        text += f"👤 {booking.get('first_name')} {booking.get('last_name', '')}\n"
        text += f"📱 {username_display}\n"
        text += f"📞 {phone_display}\n"
        text += f"💼 {booking['service']}\n"
        text += f"📅 {date_obj.strftime('%d.%m.%Y')} {booking['booking_time']}\n"
    
    text += f"━━━━━━━━━━━━━\n📊 Всего: {len(bookings)}"
    
    if len(text) > 4000:
        parts = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for part in parts:
            await message.answer(part)
    else:
        await message.answer(text)
    
    await message.answer(text="Действие:", reply_markup=get_admin_keyboard())


@router.message(F.text == "📊 Аналитика")
async def admin_analytics(message: Message):
    """Админ: аналитика"""
    if not is_admin(message.from_user.id):
        return
    
    stats = await db.get_statistics_summary()
    
    text = "📊 Аналитика\n\n"
    text += f"📈 Всего: {stats['total_bookings']}\n"
    text += f"📅 Сегодня: {stats['today_bookings']}\n"
    text += f"👥 Клиентов: {stats['unique_clients']}\n\n"
    
    if stats['popular_services']:
        text += "🔥 Популярные:\n"
        for service, count in stats['popular_services']:
            text += f"  • {service}: {count}\n"
    
    text += "\n✨ Расширенная аналитика скоро! 😊"
    
    await message.answer(text=text, reply_markup=get_admin_keyboard())

# ============================================================================
# ЗАПУСК
# ============================================================================

async def main():
    """Запуск бота"""
    global bot_instance
    
    await db.init_db()
    await db.set_admin_id(ADMIN_ID)
    
    bot_instance = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    
    dp.include_router(router)
    
    logger.info("🚀 Бот запущен!")
    logger.info(f"👨‍💼 Admin ID: {ADMIN_ID}")
    logger.info(f"📱 Уведомления: {'✅' if ADMIN_ID else '❌'}")
    
    await bot_instance.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot_instance)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Стоп")
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")