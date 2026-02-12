"""
Модуль работы с базой данных для бота салона красоты
Версия 4.1 - Универсальный модуль БД

ВАЖНО: Этот файл НЕ ТРОГАТЬ при обновлении бота!
Можно подключать к любым версиям бота.

При обновлении бота:
1. Замените все файлы КРОМЕ database.py и beauty_salon.db
2. База данных полностью сохранится
3. Все записи клиентов останутся на месте
"""

import aiosqlite
import logging
from typing import List, Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

# Путь к файлу базы данных (ЕДИНЫЙ для всех версий бота)
DATABASE_PATH = "beauty_salon.db"


class Database:
    """
    Класс для работы с базой данных салона красоты
    Все операции асинхронные
    """
    
    def __init__(self, db_path: str = DATABASE_PATH):
        """
        Инициализация базы данных
        
        Args:
            db_path: Путь к файлу базы данных
        """
        self.db_path = db_path
    
    async def init_db(self):
        """
        Создание всех необходимых таблиц в базе данных
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Таблица записей клиентов
            await db.execute("""
                CREATE TABLE IF NOT EXISTS bookings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    phone TEXT,
                    service TEXT NOT NULL,
                    booking_date TEXT NOT NULL,
                    booking_time TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(booking_date, booking_time)
                )
            """)
            
            # Добавляем колонку phone если её нет (для обновления старых БД)
            try:
                await db.execute("ALTER TABLE bookings ADD COLUMN phone TEXT")
                await db.commit()
                logger.info("✅ Колонка phone добавлена в существующую БД")
            except:
                pass  # Колонка уже существует
            
            # Таблица настроек (для хранения admin_id)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            
            # Таблица статистики для аналитики
            await db.execute("""
                CREATE TABLE IF NOT EXISTS statistics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action_type TEXT NOT NULL,
                    user_id INTEGER,
                    details TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await db.commit()
            logger.info("✅ База данных инициализирована")
    
    # ========================================================================
    # РАБОТА С НАСТРОЙКАМИ
    # ========================================================================
    
    async def get_admin_id(self) -> Optional[int]:
        """
        Получить ID администратора
        
        Returns:
            Optional[int]: ID администратора или None
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT value FROM settings WHERE key = 'admin_id'"
            ) as cursor:
                row = await cursor.fetchone()
                return int(row[0]) if row else None
    
    async def set_admin_id(self, admin_id: int):
        """
        Установить ID администратора
        
        Args:
            admin_id: Telegram ID администратора
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO settings (key, value)
                VALUES ('admin_id', ?)
                """,
                (str(admin_id),)
            )
            await db.commit()
            logger.info(f"✅ Admin ID установлен: {admin_id}")
    
    # ========================================================================
    # РАБОТА С ЗАПИСЯМИ
    # ========================================================================
    
    async def add_booking(
        self, 
        user_id: int, 
        username: str,
        first_name: str,
        last_name: str,
        service: str, 
        booking_date: str, 
        booking_time: str,
        phone: str = None
    ) -> bool:
        """
        Добавление новой записи в базу данных
        
        Args:
            user_id: Telegram ID пользователя
            username: @username пользователя
            first_name: Имя
            last_name: Фамилия
            service: Название услуги
            booking_date: Дата в формате YYYY-MM-DD
            booking_time: Время в формате HH:MM
            phone: Номер телефона (опционально)
            
        Returns:
            bool: True если запись успешно добавлена, False если слот занят
        """
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO bookings 
                    (user_id, username, first_name, last_name, phone, service, booking_date, booking_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, username, first_name, last_name, phone, service, booking_date, booking_time)
                )
                await db.commit()
                
                # Логируем в статистику
                await self.add_statistics('booking_created', user_id, f'{service} on {booking_date} {booking_time}')
                
                logger.info(f"✅ Запись добавлена: user={user_id}, date={booking_date}, time={booking_time}")
                return True
        except aiosqlite.IntegrityError:
            logger.warning(f"⚠️ Слот уже занят: date={booking_date}, time={booking_time}")
            return False
    
    async def get_user_bookings(self, user_id: int) -> List[Dict]:
        """
        Получение всех записей конкретного пользователя
        
        Args:
            user_id: Telegram ID пользователя
            
        Returns:
            List[Dict]: Список записей пользователя
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, service, booking_date, booking_time, created_at
                FROM bookings
                WHERE user_id = ?
                ORDER BY booking_date, booking_time
                """,
                (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_all_bookings(self) -> List[Dict]:
        """
        Получение ВСЕХ записей (для админки)
        
        Returns:
            List[Dict]: Список всех записей
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, user_id, username, first_name, last_name, phone,
                       service, booking_date, booking_time, created_at
                FROM bookings
                ORDER BY booking_date, booking_time
                """
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def delete_booking(self, booking_id: int, user_id: int = None) -> bool:
        """
        Удаление записи по ID
        
        Args:
            booking_id: ID записи в базе данных
            user_id: Telegram ID пользователя (для безопасности, None для админа)
            
        Returns:
            bool: True если запись удалена, False если не найдена
        """
        async with aiosqlite.connect(self.db_path) as db:
            if user_id:
                # Обычный пользователь - проверяем владельца
                cursor = await db.execute(
                    "DELETE FROM bookings WHERE id = ? AND user_id = ?",
                    (booking_id, user_id)
                )
            else:
                # Админ - удаляет любую запись
                cursor = await db.execute(
                    "DELETE FROM bookings WHERE id = ?",
                    (booking_id,)
                )
            
            await db.commit()
            deleted = cursor.rowcount > 0
            
            if deleted:
                await self.add_statistics('booking_deleted', user_id, f'booking_id={booking_id}')
                logger.info(f"🗑️ Запись удалена: booking_id={booking_id}")
            
            return deleted
    
    async def get_occupied_slots(self, booking_date: str) -> List[str]:
        """
        Получение списка занятых временных слотов на определенную дату
        
        Args:
            booking_date: Дата в формате YYYY-MM-DD
            
        Returns:
            List[str]: Список занятых временных слотов
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT booking_time FROM bookings WHERE booking_date = ?",
                (booking_date,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
    
    async def get_booking_by_id(self, booking_id: int) -> Optional[Dict]:
        """
        Получение записи по ID
        
        Args:
            booking_id: ID записи
            
        Returns:
            Optional[Dict]: Данные записи или None если не найдена
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, user_id, username, first_name, last_name, phone,
                       service, booking_date, booking_time
                FROM bookings
                WHERE id = ?
                """,
                (booking_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def search_booking_by_user_id(self, user_id: int) -> List[Dict]:
        """
        Поиск записей по Telegram ID (для админки)
        
        Args:
            user_id: Telegram ID пользователя
            
        Returns:
            List[Dict]: Список записей
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, user_id, username, first_name, last_name, phone,
                       service, booking_date, booking_time, created_at
                FROM bookings
                WHERE user_id = ?
                ORDER BY booking_date, booking_time
                """,
                (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    # ========================================================================
    # СТАТИСТИКА
    # ========================================================================
    
    async def add_statistics(self, action_type: str, user_id: int = None, details: str = None):
        """
        Добавить запись в статистику
        
        Args:
            action_type: Тип действия (booking_created, booking_deleted, etc.)
            user_id: ID пользователя
            details: Дополнительные детали
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO statistics (action_type, user_id, details)
                VALUES (?, ?, ?)
                """,
                (action_type, user_id, details)
            )
            await db.commit()
    
    async def get_statistics_summary(self) -> Dict:
        """
        Получить сводку статистики
        
        Returns:
            Dict: Сводная статистика
"""
        async with aiosqlite.connect(self.db_path) as db:
            # Общее количество записей
            async with db.execute("SELECT COUNT(*) FROM bookings") as cursor:
                total_bookings = (await cursor.fetchone())[0]
            
            # Записи за сегодня
            today = datetime.now().strftime('%Y-%m-%d')
            async with db.execute(
                "SELECT COUNT(*) FROM bookings WHERE booking_date = ?",
                (today,)
            ) as cursor:
                today_bookings = (await cursor.fetchone())[0]
            
            # Уникальные клиенты
            async with db.execute("SELECT COUNT(DISTINCT user_id) FROM bookings") as cursor:
                unique_clients = (await cursor.fetchone())[0]
            
            # Популярные услуги
            async with db.execute(
                """
                SELECT service, COUNT(*) as count
                FROM bookings
                GROUP BY service
                ORDER BY count DESC
                LIMIT 3
                """
            ) as cursor:
                popular_services = await cursor.fetchall()
            
            return {
                'total_bookings': total_bookings,
                'today_bookings': today_bookings,
                'unique_clients': unique_clients,
                'popular_services': popular_services
            }


# Создаем глобальный экземпляр базы данных
db = Database()