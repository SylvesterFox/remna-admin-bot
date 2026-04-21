from datetime import datetime, timedelta
from io import BytesIO
import logging
import random
import string
from typing import Dict, Optional, Any
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    KeyboardButton,
    KeyboardButtonRequestUser,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import ContextTypes, ConversationHandler
import re
import asyncio
import qrcode

from modules.config import (
    MAIN_MENU, USER_MENU, SELECTING_USER, WAITING_FOR_INPUT, CONFIRM_ACTION,
    EDIT_USER, EDIT_FIELD, EDIT_VALUE, CREATE_USER, CREATE_USER_FIELD, USER_FIELDS
)

# Константы для callback_data
class CallbackData:
    # Основные действия
    LIST_USERS = "list_users"
    SEARCH_USER = "search_user"
    CREATE_USER = "create_user"
    BACK_TO_MAIN = "back_to_main"
    BACK_TO_USERS = "back_to_users"
    BACK_TO_LIST = "back_to_list"
    
    # Действия с пользователями
    VIEW_USER = "view_"
    EDIT_USER = "edit_"
    DISABLE_USER = "disable_"
    ENABLE_USER = "enable_"
    RESET_TRAFFIC = "reset_"
    REVOKE_SUBSCRIPTION = "revoke_"
    DELETE_USER = "delete_"
    USER_STATS = "stats_"
    USER_HWID = "hwid_"
    
    # Подтверждения
    CONFIRM_ACTION = "confirm_action"
    FINAL_DELETE_USER = "final_delete_user"
    
    # Создание пользователей
    TEMPLATE = "template_"
    CREATE_MANUAL = "create_manual"
    CANCEL_CREATE = "cancel_create"
    USE_TEMPLATE = "use_template_"
    CUSTOMIZE_TEMPLATE = "customize_template_"
    FINISH_TEMPLATE_USER = "finish_template_user"
    ADD_OPTIONAL_FIELDS = "add_optional_fields"
    USE_TEMPLATE_VALUE = "use_template_value_"
    SKIP_FIELD = "skip_field"
    
    # Поля создания
    CREATE_FIELD = "create_field_"
    CREATE_DATE = "create_date_"
    CREATE_TRAFFIC = "create_traffic_"
    CREATE_DESC = "create_desc_"
    CREATE_DEVICE = "create_device_"
    
    # Редактирование полей
    EDIT_FIELD = "edit_field_"
    
    # HWID устройства
    ADD_HWID = "add_hwid_"
    DEL_HWID = "del_hwid_"
    CONFIRM_DEL_HWID = "confirm_del_hwid_"
    
    # Пагинация
    PREV_PAGE = "prev_page"
    NEXT_PAGE = "next_page"
    PAGE_INFO = "page_info"
    USERS_PAGE = "users_page_"
    
    # SelectionHelper
    SELECT_USER = "select_user_"
    USER_ACTION = "user_action_"
    BACK = "back"

# Константы для сообщений
class Messages:
    # Ошибки авторизации
    NOT_AUTHORIZED = "⛔ Вы не авторизованы для использования этого бота."
    
    # Общие ошибки
    USER_NOT_FOUND = "❌ Пользователь не найден или ошибка при получении данных."
    ERROR_LOADING = "❌ Ошибка при загрузке данных."
    INVALID_INPUT = "❌ Неверный формат ввода."
    OPERATION_FAILED = "❌ Не удалось выполнить операцию."
    
    # Успешные операции
    USER_CREATED = "✅ Пользователь успешно создан!"
    USER_UPDATED = "✅ Пользователь успешно обновлен!"
    USER_DELETED = "✅ Пользователь успешно удален!"
    FIELD_UPDATED = "✅ Поле успешно обновлено."
    
    # Предупреждения
    CONFIRM_DELETE = "⚠️ Вы уверены, что хотите удалить пользователя?"
    CONFIRM_DISABLE = "⚠️ Вы уверены, что хотите отключить пользователя?"
    CONFIRM_ENABLE = "⚠️ Вы уверены, что хотите включить пользователя?"
    CONFIRM_RESET = "⚠️ Вы уверены, что хотите сбросить трафик пользователя?"
    CONFIRM_REVOKE = "⚠️ Вы уверены, что хотите отозвать подписку пользователя?"
from modules.api.users import UserAPI
from modules.api.internal_squads import InternalSquadAPI
from modules.utils.formatters import format_bytes, format_user_details, format_user_details_safe, escape_markdown, safe_edit_message
from modules.utils.selection_helpers import SelectionHelper
from modules.utils.auth import (
    check_admin,
    check_authorization,
    get_user_role,
    is_admin_user,
    INSUFFICIENT_PERMISSIONS_MESSAGE
)
from modules.handlers.core.start import show_main_menu

logger = logging.getLogger(__name__)


def _build_subscription_qr_image(subscription_url: str) -> BytesIO:
    """Build a QR code image for the provided subscription URL."""
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(subscription_url)
    qr.make(fit=True)

    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


async def _send_subscription_qr(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user: Dict[str, Any],
    *,
    reply_to_message_id: Optional[int] = None,
) -> bool:
    """Send subscription URL QR code as a separate photo message."""
    subscription_url = user.get("subscriptionUrl")
    if not subscription_url:
        return False

    qr_buffer = _build_subscription_qr_image(subscription_url)
    username = user.get("username", "unknown")
    caption = f"QR подписки для {username}\n{subscription_url}"

    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=InputFile(qr_buffer, filename=f"subscription-{username}.png"),
        caption=caption,
        reply_to_message_id=reply_to_message_id,
    )
    return True


TELEGRAM_USER_PICKER_REQUEST_ID = 1001


async def _send_user_request_keyboard(
    update: Update,
    prompt: str = "Нажмите кнопку ниже, чтобы выбрать пользователя в Telegram.",
) -> None:
    """Send a one-time reply keyboard that opens Telegram user picker."""
    keyboard = ReplyKeyboardMarkup(
        [[
            KeyboardButton(
                "👤 Выбрать пользователя",
                request_user=KeyboardButtonRequestUser(
                    request_id=TELEGRAM_USER_PICKER_REQUEST_ID,
                    user_is_bot=False,
                ),
            )
        ]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

    target_message = update.callback_query.message if update.callback_query else update.message
    if target_message:
        await target_message.reply_text(prompt, reply_markup=keyboard)


async def _show_internal_squads_selector(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Render internal squads multi-select step for user creation."""
    squads = context.user_data.get("available_internal_squads")
    if squads is None:
        squads = await InternalSquadAPI.get_all_internal_squads()
        context.user_data["available_internal_squads"] = squads

    selected = set(context.user_data["create_user"].get("activeInternalSquads", []))

    keyboard = []
    if squads:
        for squad in squads:
            squad_uuid = squad.get("uuid")
            squad_name = squad.get("name", "Без имени")
            if not squad_uuid:
                continue
            prefix = "✅" if squad_uuid in selected else "⬜"
            keyboard.append([
                InlineKeyboardButton(
                    f"{prefix} {squad_name}",
                    callback_data=f"create_squad_toggle_{squad_uuid}",
                )
            ])
        keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="create_squad_done")])
    else:
        keyboard.append([InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")])

    keyboard.append([InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")])
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")])

    message = "🛡️ *Выберите внутренние сквады*\n\n"
    if squads:
        message += "Можно выбрать несколько сквадов. Нажимайте по пунктам, затем `Готово`."
    else:
        message += "Не удалось получить список внутренних сквадов."

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )


async def _show_edit_internal_squads_selector(update: Update, context: ContextTypes.DEFAULT_TYPE, user: Dict[str, Any]):
    """Render internal squads multi-select step for editing a user."""
    squads = context.user_data.get("available_internal_squads")
    if squads is None:
        squads = await InternalSquadAPI.get_all_internal_squads()
        context.user_data["available_internal_squads"] = squads

    selected = set(context.user_data.get("edit_active_internal_squads", []))

    keyboard = []
    if squads:
        for squad in squads:
            squad_uuid = squad.get("uuid")
            squad_name = squad.get("name", "Без имени")
            if not squad_uuid:
                continue
            prefix = "✅" if squad_uuid in selected else "⬜"
            keyboard.append([
                InlineKeyboardButton(
                    f"{prefix} {squad_name}",
                    callback_data=f"edit_squad_toggle_{squad_uuid}",
                )
            ])
        keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="edit_squad_done")])
    else:
        keyboard.append([InlineKeyboardButton("🔄 Обновить список", callback_data=f"edit_field_activeInternalSquads")])

    keyboard.append([InlineKeyboardButton("🔙 Назад к выбору поля", callback_data=f"edit_{user['uuid']}")])
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data=f"view_{user['uuid']}")])

    message = f"📝 *Редактирование поля: Внутренние сквады*\n\n"
    if squads:
        message += "Нажимайте по сквадам, чтобы включать и выключать их для пользователя.\n"
        message += "Когда закончите, нажмите `Готово`."
    else:
        message += "Не удалось получить список внутренних сквадов."

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.callback_query.edit_message_text(
        text=message,
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )

# Декоратор для проверки авторизации
def require_authorization(func):
    """Декоратор для проверки авторизации пользователя"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if not check_authorization(update.effective_user):
            if update.callback_query:
                await update.callback_query.answer(Messages.NOT_AUTHORIZED, show_alert=True)
            else:
                await update.message.reply_text(Messages.NOT_AUTHORIZED)
            return ConversationHandler.END

        user_id = update.effective_user.id
        context.user_data['role'] = get_user_role(user_id)
        context.user_data['is_admin'] = is_admin_user(user_id)

        return await func(update, context, *args, **kwargs)
    return wrapper

# Декоратор для логирования действий пользователей
def log_user_action(action: str):
    """Декоратор для логирования действий пользователей"""
    def decorator(func):
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id if update.effective_user else "unknown"
            username = update.effective_user.username if update.effective_user else "unknown"
            
            logger.info(f"User action: {action} by user {username} (ID: {user_id})")
            
            try:
                result = await func(update, context, *args, **kwargs)
                logger.info(f"Action {action} completed successfully for user {username}")
                return result
            except Exception as e:
                logger.error(f"Action {action} failed for user {username}: {str(e)}")
                raise
        return wrapper
    return decorator

# Обработка ошибок
class ErrorHandler:
    """Класс для обработки ошибок"""
    
    @staticmethod
    async def handle_api_error(update: Update, context: ContextTypes.DEFAULT_TYPE, error: Exception, operation: str = "операция") -> bool:
        """Обрабатывает ошибки API"""
        logger.error(f"API error during {operation}: {str(error)}")
        
        error_message = f"❌ Ошибка при выполнении {operation}.\n\n"
        
        if "connection" in str(error).lower():
            error_message += "🔌 Проблема с подключением к серверу. Попробуйте позже."
        elif "timeout" in str(error).lower():
            error_message += "⏰ Превышено время ожидания. Попробуйте позже."
        elif "unauthorized" in str(error).lower() or "forbidden" in str(error).lower():
            error_message += "🔒 Недостаточно прав для выполнения операции."
        elif "not found" in str(error).lower():
            error_message += "🔍 Запрашиваемые данные не найдены."
        else:
            error_message += "⚠️ Внутренняя ошибка сервера. Обратитесь к администратору."
        
        keyboard = KeyboardBuilder.create_back_button()
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text=error_message,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception as edit_error:
                logger.error(f"Error editing message: {edit_error}")
                await update.callback_query.answer("❌ Ошибка при обновлении сообщения")
        else:
            await update.message.reply_text(
                text=error_message,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        
        return True
    
    @staticmethod
    async def handle_validation_error(update: Update, context: ContextTypes.DEFAULT_TYPE, error_message: str, back_callback: str = CallbackData.BACK_TO_USERS) -> bool:
        """Обрабатывает ошибки валидации"""
        keyboard = KeyboardBuilder.create_back_button(back_callback)
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text=f"❌ {error_message}",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception as edit_error:
                logger.error(f"Error editing message: {edit_error}")
                await update.callback_query.answer("❌ Ошибка валидации")
        else:
            await update.message.reply_text(
                text=f"❌ {error_message}",
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        
        return True
    
    @staticmethod
    async def handle_unexpected_error(update: Update, context: ContextTypes.DEFAULT_TYPE, error: Exception, operation: str = "операция") -> bool:
        """Обрабатывает неожиданные ошибки"""
        logger.error(f"Unexpected error during {operation}: {str(error)}", exc_info=True)
        
        error_message = f"❌ Произошла неожиданная ошибка при выполнении {operation}.\n\n"
        error_message += "🛠️ Обратитесь к администратору системы."
        
        keyboard = KeyboardBuilder.create_back_button()
        
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text=error_message,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception as edit_error:
                logger.error(f"Error editing message: {edit_error}")
                await update.callback_query.answer("❌ Критическая ошибка")
        else:
            await update.message.reply_text(
                text=error_message,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        
        return True

# Кэширование данных пользователей
class UserCache:
    """Класс для кэширования данных пользователей"""
    
    def __init__(self, cache_ttl: int = 300):  # 5 минут по умолчанию
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = cache_ttl
    
    def _is_expired(self, timestamp: float) -> bool:
        """Проверяет, истек ли срок кэша"""
        return datetime.now().timestamp() - timestamp > self._cache_ttl
    
    async def get_user(self, uuid: str) -> Optional[Dict[str, Any]]:
        """Получает пользователя из кэша или API"""
        cache_key = f"user_{uuid}"
        
        if cache_key in self._cache:
            cached_data = self._cache[cache_key]
            if not self._is_expired(cached_data['timestamp']):
                logger.debug(f"User {uuid} found in cache")
                return cached_data['data']
            else:
                # Удаляем устаревшие данные
                del self._cache[cache_key]
        
        # Периодически очищаем кэш (каждый 10-й запрос)
        if len(self._cache) % 10 == 0:
            self.cleanup_expired()
        
        # Получаем данные из API
        try:
            user_data = await UserAPI.get_user_by_uuid(uuid)
            if user_data:
                self._cache[cache_key] = {
                    'data': user_data,
                    'timestamp': datetime.now().timestamp()
                }
                logger.debug(f"User {uuid} cached")
            return user_data
        except Exception as e:
            logger.error(f"Error fetching user {uuid}: {e}")
            return None
    
    async def get_all_users(self) -> Optional[list]:
        """Получает всех пользователей из кэша или API"""
        cache_key = "all_users"
        
        if cache_key in self._cache:
            cached_data = self._cache[cache_key]
            if not self._is_expired(cached_data['timestamp']):
                logger.debug("All users found in cache")
                return cached_data['data']
            else:
                del self._cache[cache_key]
        
        # Получаем данные из API
        try:
            response = await UserAPI.get_all_users()
            users = []
            
            if isinstance(response, dict):
                if 'users' in response:
                    users = response['users'] or []
                elif 'response' in response and isinstance(response['response'], dict) and 'users' in response['response']:
                    users = response['response']['users'] or []
            elif isinstance(response, list):
                users = response
            
            if users:
                self._cache[cache_key] = {
                    'data': users,
                    'timestamp': datetime.now().timestamp()
                }
                logger.debug(f"Cached {len(users)} users")
            
            return users
        except Exception as e:
            logger.error(f"Error fetching all users: {e}")
            return None
    
    def invalidate_user(self, uuid: str):
        """Инвалидирует кэш конкретного пользователя"""
        cache_key = f"user_{uuid}"
        if cache_key in self._cache:
            del self._cache[cache_key]
            logger.debug(f"Cache invalidated for user {uuid}")
    
    def invalidate_all_users(self):
        """Инвалидирует кэш всех пользователей"""
        self._cache.clear()
        logger.debug("All users cache invalidated")
    
    def cleanup_expired(self):
        """Очищает устаревшие записи из кэша"""
        current_time = datetime.now().timestamp()
        expired_keys = [
            key for key, data in self._cache.items()
            if current_time - data['timestamp'] > self._cache_ttl
        ]
        
        for key in expired_keys:
            del self._cache[key]
        
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

# Глобальный экземпляр кэша
user_cache = UserCache()

# Функция для ручной очистки кэша
def cleanup_cache():
    """Очищает устаревшие записи из кэша"""
    try:
        user_cache.cleanup_expired()
        logger.debug("Cache cleanup completed")
    except Exception as e:
        logger.error(f"Error during cache cleanup: {e}")

# Утилиты для работы с клавиатурами
class KeyboardBuilder:
    """Класс для создания клавиатур"""
    
    @staticmethod
    def create_main_menu(is_admin: bool):
        """Создает главное меню пользователей"""
        rows = [
            [InlineKeyboardButton("📋 Список всех пользователей", callback_data=CallbackData.LIST_USERS)],
            [InlineKeyboardButton("🔍 Поиск пользователя", callback_data=CallbackData.SEARCH_USER)]
        ]
        if is_admin:
            rows.append([InlineKeyboardButton("➕ Создать пользователя", callback_data=CallbackData.CREATE_USER)])
        rows.append([InlineKeyboardButton("🔙 Назад в главное меню", callback_data=CallbackData.BACK_TO_MAIN)])
        return InlineKeyboardMarkup(rows)
    
    @staticmethod
    def create_back_button(callback_data: str = CallbackData.BACK_TO_USERS):
        """Создает кнопку 'Назад'"""
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=callback_data)]])
    
    @staticmethod
    def create_confirmation_buttons(confirm_callback: str, cancel_callback: str, confirm_text: str = "✅ Да", cancel_text: str = "❌ Отмена"):
        """Создает кнопки подтверждения"""
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(confirm_text, callback_data=confirm_callback)],
            [InlineKeyboardButton(cancel_text, callback_data=cancel_callback)]
        ])
    
    @staticmethod
    def create_user_actions_keyboard(uuid: str, user_status: str = "ACTIVE"):
        """Создает клавиатуру действий с пользователем"""
        keyboard = [
            [InlineKeyboardButton("📝 Редактировать", callback_data=f"{CallbackData.EDIT_USER}{uuid}")],
            [InlineKeyboardButton("🔄 Сбросить трафик", callback_data=f"{CallbackData.RESET_TRAFFIC}{uuid}")],
            [InlineKeyboardButton("📊 Статистика", callback_data=f"{CallbackData.USER_STATS}{uuid}")],
            [InlineKeyboardButton("📱 Устройства HWID", callback_data=f"{CallbackData.USER_HWID}{uuid}")]
        ]
        if user_status == "ACTIVE":
            keyboard.append([InlineKeyboardButton("🔴 Отключить", callback_data=f"{CallbackData.DISABLE_USER}{uuid}")])
        else:
            keyboard.append([InlineKeyboardButton("🟢 Включить", callback_data=f"{CallbackData.ENABLE_USER}{uuid}")])
        keyboard.append([InlineKeyboardButton("🔄 Отозвать подписку", callback_data=f"{CallbackData.REVOKE_SUBSCRIPTION}{uuid}")])
        keyboard.append([InlineKeyboardButton("🗑️ Удалить", callback_data=f"{CallbackData.DELETE_USER}{uuid}")])
        keyboard.append([InlineKeyboardButton("🔙 Назад к списку", callback_data=CallbackData.BACK_TO_LIST)])
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_pagination_buttons(current_page: int, total_pages: int, callback_prefix: str = "page"):
        """Создает кнопки пагинации"""
        keyboard = []
        
        if current_page > 0:
            keyboard.append(InlineKeyboardButton("◀️ Назад", callback_data=f"{callback_prefix}_{current_page - 1}"))
        
        if current_page < total_pages - 1:
            keyboard.append(InlineKeyboardButton("Вперед ▶️", callback_data=f"{callback_prefix}_{current_page + 1}"))
        
        return keyboard

# Дополнительные утилиты
class UserUtils:
    """Утилиты для работы с пользователями"""
    
    @staticmethod
    def format_user_status(status: str) -> str:
        """Форматирует статус пользователя"""
        status_map = {
            "ACTIVE": "✅ Активен",
            "INACTIVE": "❌ Неактивен",
            "EXPIRED": "⏰ Истек",
            "SUSPENDED": "🚫 Заблокирован"
        }
        return status_map.get(status, f"❓ {status}")
    
    @staticmethod
    def format_traffic_usage(used: int, limit: int) -> str:
        """Форматирует использование трафика"""
        if limit == 0:
            return f"📊 {format_bytes(used)} / Безлимитный"
        
        percent = (used / limit) * 100
        status_emoji = "🟢" if percent < 50 else "🟡" if percent < 90 else "🔴"
        
        return f"📊 {format_bytes(used)} / {format_bytes(limit)} ({percent:.1f}%) {status_emoji}"
    
    @staticmethod
    def format_expiration_date(expire_at: str) -> str:
        """Форматирует дату истечения"""
        try:
            expire_date = datetime.fromisoformat(expire_at.replace('Z', '+00:00'))
            days_left = (expire_date - datetime.now().astimezone()).days
            
            if days_left < 0:
                return f"⏰ Истек {abs(days_left)} дней назад"
            elif days_left == 0:
                return "⏰ Истекает сегодня"
            elif days_left <= 7:
                return f"⚠️ Истекает через {days_left} дней"
            else:
                return f"📅 Истекает через {days_left} дней"
        except Exception:
            return f"📅 {expire_at[:10]}"
    
    @staticmethod
    def get_user_summary(user: Dict[str, Any]) -> str:
        """Создает краткое описание пользователя"""
        lines = [
            f"👤 *{escape_markdown(user.get('username', 'Без имени'))}*",
            f"🆔 `{user.get('uuid', 'N/A')}`",
            f"📊 {UserUtils.format_traffic_usage(user.get('usedTrafficBytes', 0), user.get('trafficLimitBytes', 0))}",
            f"📅 {UserUtils.format_expiration_date(user.get('expireAt', ''))}",
            f"📱 {UserUtils.format_user_status(user.get('status', 'UNKNOWN'))}"
        ]
        
        if user.get('email'):
            lines.append(f"📧 {escape_markdown(user['email'])}")
        
        if user.get('tag'):
            lines.append(f"🏷️ {escape_markdown(user['tag'])}")
        
        return "\n".join(lines)

# Массовые операции
class BulkOperations:
    """Класс для массовых операций с пользователями"""
    
    @staticmethod
    async def bulk_disable_users(uuids: list[str]) -> Dict[str, bool]:
        """Массовое отключение пользователей"""
        results = {}
        
        for uuid in uuids:
            try:
                result = await UserAPI.disable_user(uuid)
                results[uuid] = result
                if result:
                    user_cache.invalidate_user(uuid)
            except Exception as e:
                logger.error(f"Error disabling user {uuid}: {e}")
                results[uuid] = False
        
        return results
    
    @staticmethod
    async def bulk_enable_users(uuids: list[str]) -> Dict[str, bool]:
        """Массовое включение пользователей"""
        results = {}
        
        for uuid in uuids:
            try:
                result = await UserAPI.enable_user(uuid)
                results[uuid] = result
                if result:
                    user_cache.invalidate_user(uuid)
            except Exception as e:
                logger.error(f"Error enabling user {uuid}: {e}")
                results[uuid] = False
        
        return results
    
    @staticmethod
    async def bulk_reset_traffic(uuids: list[str]) -> Dict[str, bool]:
        """Массовый сброс трафика"""
        results = {}
        
        for uuid in uuids:
            try:
                result = await UserAPI.reset_user_traffic(uuid)
                results[uuid] = result
                if result:
                    user_cache.invalidate_user(uuid)
            except Exception as e:
                logger.error(f"Error resetting traffic for user {uuid}: {e}")
                results[uuid] = False
        
        return results
    
    @staticmethod
    def format_bulk_results(results: Dict[str, bool], operation: str) -> str:
        """Форматирует результаты массовых операций"""
        successful = sum(1 for success in results.values() if success)
        total = len(results)
        
        message = f"📊 *Результаты массовой операции: {operation}*\n\n"
        message += f"✅ Успешно: {successful}/{total}\n"
        message += f"❌ Ошибок: {total - successful}/{total}\n\n"
        
        if successful < total:
            failed_uuids = [uuid for uuid, success in results.items() if not success]
            message += f"❌ Неудачные UUID: `{', '.join(failed_uuids[:5])}`"
            if len(failed_uuids) > 5:
                message += f" и еще {len(failed_uuids) - 5}..."
        
        return message

# Валидаторы данных
class DataValidators:
    """Класс для валидации данных"""
    
    @staticmethod
    def validate_username(username: str) -> tuple[bool, str]:
        """Валидация имени пользователя"""
        if not username:
            return False, "Имя пользователя не может быть пустым"
        
        if not re.match(r"^[a-zA-Z0-9_-]{6,34}$", username):
            return False, "Имя пользователя должно содержать только буквы, цифры, подчеркивания и дефисы. Длина от 6 до 34 символов"
        
        return True, ""
    
    @staticmethod
    def validate_email(email: str) -> tuple[bool, str]:
        """Валидация email"""
        if not email:
            return True, ""  # Email не обязателен
        
        if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
            return False, "Неверный формат email"
        
        return True, ""
    
    @staticmethod
    def validate_telegram_id(telegram_id: str) -> tuple[bool, str, int]:
        """Валидация Telegram ID"""
        if not telegram_id:
            return True, "", 0  # Telegram ID не обязателен
        
        try:
            tid = int(telegram_id)
            if tid <= 0:
                return False, "Telegram ID должен быть положительным числом", 0
            return True, "", tid
        except ValueError:
            return False, "Telegram ID должен быть целым числом", 0
    
    @staticmethod
    def validate_date(date_str: str) -> tuple[bool, str, str]:
        """Валидация даты"""
        if not date_str:
            return True, "", ""  # Дата не обязательна
        
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            formatted_date = date_obj.strftime("%Y-%m-%dT00:00:00.000Z")
            return True, "", formatted_date
        except ValueError:
            return False, "Неверный формат даты. Используйте YYYY-MM-DD", ""
    
    @staticmethod
    def validate_traffic_limit(traffic_str: str) -> tuple[bool, str, int]:
        """Валидация лимита трафика"""
        if not traffic_str:
            return True, "", 0  # Лимит не обязателен
        
        try:
            traffic = int(traffic_str)
            if traffic < 0:
                return False, "Лимит трафика не может быть отрицательным", 0
            return True, "", traffic
        except ValueError:
            return False, "Лимит трафика должен быть целым числом", 0
    
    @staticmethod
    def validate_device_limit(device_str: str) -> tuple[bool, str, int]:
        """Валидация лимита устройств"""
        if not device_str:
            return True, "", 0  # Лимит не обязателен
        
        try:
            devices = int(device_str)
            if devices < 0:
                return False, "Лимит устройств не может быть отрицательным", 0
            return True, "", devices
        except ValueError:
            return False, "Лимит устройств должен быть целым числом", 0

@require_authorization
@log_user_action("show_users_menu")
async def show_users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show users menu"""
    reply_markup = KeyboardBuilder.create_main_menu(context.user_data.get('is_admin', False))

    message = (
        "👥 *Управление пользователями*\n\n"
        "🔍 *Поиск:* введите любую часть имени, Telegram ID, UUID, короткого UUID, email, тега или описания.\n\n"
        "Выберите действие:"
    )

    await safe_edit_message(
        update.callback_query,
        message,
        reply_markup,
        "Markdown"
    )

@require_authorization
@log_user_action("handle_users_menu")
async def handle_users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle users menu selection"""
    query = update.callback_query
    await query.answer()

    data = query.data
    is_admin = context.user_data.get('is_admin', False)

    try:
        logger.debug(f"handle_user_selection received callback data: {data}")
    except Exception:
        pass

    if data == CallbackData.LIST_USERS:
        await list_users(update, context)
        return SELECTING_USER

    elif data == CallbackData.SEARCH_USER:
        back_markup = KeyboardBuilder.create_back_button()
        search_prompt = (
            "🔍 Введите текст для поиска пользователя:\n\n"
            "💡 *Пример:* имя, часть описания, email, тег, UUID или Telegram ID."
        )
        await safe_edit_message(
            query,
            search_prompt,
            back_markup,
            "Markdown"
        )
        context.user_data["search_type"] = "generic"
        return WAITING_FOR_INPUT
        
    elif data in (CallbackData.CREATE_USER, "menu_create_user"):
        await start_create_user(update, context)
        return CREATE_USER_FIELD

    elif data == CallbackData.BACK_TO_USERS:
        await show_users_menu(update, context)
        return USER_MENU

    elif data == CallbackData.BACK_TO_MAIN:
        await show_main_menu(update, context)
        return MAIN_MENU

    return USER_MENU

async def search_users_by_term(term: str):
    """Fetch users and filter by generic term"""
    try:
        users = await user_cache.get_all_users()
        if not users:
            return []
    except Exception as e:
        logger.error(f"Error fetching users for search: {e}")
        return []

    term_lower = term.lower()
    matches = []
    seen = set()

    for user in users:
        if not isinstance(user, dict):
            continue
        user_uuid = str(user.get('uuid') or '')
        if not user_uuid or user_uuid in seen:
            continue

        fields = [
            str(user.get('username') or ''),
            str(user.get('description') or ''),
            str(user.get('email') or ''),
            str(user.get('tag') or ''),
            str(user.get('shortUuid') or ''),
            user_uuid,
            str(user.get('telegramId') or '')
        ]

        if any(term_lower in field.lower() for field in fields if field):
            matches.append(user)
            seen.add(user_uuid)

    matches.sort(key=lambda u: (u.get('username') or '').lower())
    return matches


async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all users with improved selection interface"""
    await update.callback_query.edit_message_text("📋 Загрузка списка пользователей...")

    try:
        # Use SelectionHelper for user-friendly interface
        keyboard, users_data = await SelectionHelper.get_users_selection_keyboard(
            callback_prefix="select_user",
            include_back=True,
            max_per_row=1
        )
        
        if not users_data:
            keyboard = [[InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_users")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                "❌ Пользователи не найдены.",
                reply_markup=reply_markup
            )
            return USER_MENU

        # Store users data for later use
        context.user_data["users_data"] = users_data
        
        message = f"👥 *Список пользователей* ({len(users_data)} шт.)\n\n"
        message += "Выберите пользователя для просмотра подробной информации:"

        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        
        return SELECTING_USER
        
    except Exception as e:
        logger.error(f"Error in list_users: {e}")
        keyboard = [[InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_users")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            f"❌ Ошибка при загрузке списка пользователей: {str(e)}",
            reply_markup=reply_markup
        )
        return USER_MENU

    if not users or not users.get("users"):
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_users")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            "❌ Пользователи не найдены или ошибка при получении списка.",
            reply_markup=reply_markup
        )
        return USER_MENU

    # Create a paginated list of users
    users_per_page = 5
    context.user_data["users"] = users["users"]
    context.user_data["current_page"] = 0
    context.user_data["users_per_page"] = users_per_page

    await send_users_page(update, context)
    return SELECTING_USER

async def send_users_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a page of users"""
    users = context.user_data["users"]
    current_page = context.user_data["current_page"]
    users_per_page = context.user_data["users_per_page"]

    start_idx = current_page * users_per_page
    end_idx = min(start_idx + users_per_page, len(users))

    message = f"👥 *Пользователи* (Страница {current_page + 1}/{(len(users) + users_per_page - 1) // users_per_page}):\n\n"

    for i in range(start_idx, end_idx):
        user = users[i]
        status_emoji = "✅" if user["status"] == "ACTIVE" else "❌"
        
        # Format expiration date
        try:
            expire_date = datetime.fromisoformat(user['expireAt'].replace('Z', '+00:00'))
            days_left = (expire_date - datetime.now().astimezone()).days
            expire_status = "🟢" if days_left > 7 else "🟡" if days_left > 0 else "🔴"
            expire_text = f"{user['expireAt'][:10]} ({days_left} дней)"
        except Exception:
            expire_status = "📅"
            expire_text = user['expireAt'][:10]
        
        message += f"{i+1}. {status_emoji} *{escape_markdown(user['username'])}*\n"
        message += f"   🔑 ID: `{user['shortUuid']}`\n"
        message += f"   📈 Трафик: {format_bytes(user['usedTrafficBytes'])}/{format_bytes(user['trafficLimitBytes'])}\n"
        message += f"   {expire_status} Истекает: {expire_text}\n\n"

    # Create navigation buttons
    keyboard = []
    nav_row = []

    if current_page > 0:
        nav_row.append(InlineKeyboardButton("◀️ Назад", callback_data="prev_page"))

    if end_idx < len(users):
        nav_row.append(InlineKeyboardButton("Вперед ▶️", callback_data="next_page"))

    if nav_row:
        keyboard.append(nav_row)

    # Add action buttons for each user
    for i in range(start_idx, end_idx):
        user = users[i]
        user_row = [
            InlineKeyboardButton(f"👤 {user['username']}", callback_data=f"view_{user['uuid']}")
        ]
        keyboard.append(user_row)

    # Add back button
    keyboard.append([InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_users")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

async def handle_user_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user selection with improved UI"""
    # Проверяем авторизацию
    if not check_authorization(update.effective_user):
        await update.callback_query.answer("⛔ Вы не авторизованы для использования этого бота.", show_alert=True)
        return ConversationHandler.END
    
    query = update.callback_query
    await query.answer()

    data = query.data

    # Handle new SelectionHelper callbacks
    if data.startswith("select_user_"):
        user_uuid = data.split("_", 2)[2]
        await show_user_details(update, context, user_uuid)
        return SELECTING_USER

    # Handle back button from SelectionHelper
    elif data == "back":
        await show_users_menu(update, context)
        return USER_MENU

    # Handle pagination from SelectionHelper
    elif data.startswith("users_page_"):
        page = int(data.split("_")[2])
        try:
            keyboard, users_data = await SelectionHelper.get_users_selection_keyboard(
                callback_prefix="select_user",
                include_back=True,
                max_per_row=1,
                page=page
            )
            
            context.user_data["users_data"] = users_data
            
            message = f"👥 *Список пользователей* ({len(users_data)} шт.) - страница {page + 1}\n\n"
            message += "Выберите пользователя для просмотра подробной информации:"

            await query.edit_message_text(
                text=message,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error in pagination: {e}")
            await show_users_menu(update, context)
            return USER_MENU

    elif data == "page_info":
        await query.answer("Это текущая страница. Используйте стрелки, чтобы переключать список.")
        return SELECTING_USER

    # Legacy support for old callback patterns
    elif data == "prev_page":
        context.user_data["current_page"] -= 1
        await send_users_page(update, context)

    elif data == "next_page":
        context.user_data["current_page"] += 1
        await send_users_page(update, context)

    elif data == "back_to_users":
        await show_users_menu(update, context)
        return USER_MENU

    elif data == "back_to_list":
        await list_users(update, context)
        return SELECTING_USER

    elif data.startswith("view_"):
        uuid = data.split("_")[1]
        try:
            logger.debug(f"Opening user details for uuid={uuid}")
        except Exception:
            pass
        await show_user_details(update, context, uuid)
        
    elif data.startswith("add_hwid_"):
        uuid = data.split("_")[2]
        await start_add_hwid(update, context, uuid)
        return WAITING_FOR_INPUT
        
    elif data.startswith("del_hwid_"):
        parts = data.split("_")
        uuid = parts[2]
        hwid = parts[3]
        await delete_hwid_device(update, context, uuid, hwid)

    return SELECTING_USER

async def show_user_details(update: Update, context: ContextTypes.DEFAULT_TYPE, uuid):
    """Show user details (safe formatting to avoid Markdown parse issues)"""
    try:
        logger.debug(f"show_user_details called for uuid={uuid}")
    except Exception:
        pass
    user = await user_cache.get_user(uuid)
    context.user_data.pop("search_type", None)
    context.user_data.pop("waiting_for", None)
    if not user:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_users")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(
            "❌ Пользователь не найден или ошибка при получении данных.",
            reply_markup=reply_markup
        )
        return USER_MENU

    # Формируем безопасное сообщение без Markdown
    try:
        message = format_user_details_safe(user)
    except Exception as e:
        logger.error(f"Error formatting user details (safe): {e}")
        message = f"👤 Пользователь: {user.get('username','')}\n🆔 UUID: {user.get('uuid','')}\n📊 Статус: {user.get('status','')}"

    keyboard = SelectionHelper.create_user_info_keyboard(
        uuid,
        action_prefix="user_action",
        is_admin=context.user_data.get('is_admin', False),
    )

    # Safety net: ensure the subscription button is present even if another path rebuilt the markup.
    has_subscription_button = any(
        any(button.callback_data == f"user_action_subscription_{uuid}" for button in row)
        for row in keyboard.inline_keyboard
    )
    if not has_subscription_button:
        rows = list(keyboard.inline_keyboard[:-1])
        rows.append([InlineKeyboardButton("🔗 URL и QR подписки", callback_data=f"user_action_subscription_{uuid}")])
        rows.append(list(keyboard.inline_keyboard[-1]))
        keyboard = InlineKeyboardMarkup(rows)

    logger.info(
        "User details keyboard for %s contains callbacks: %s",
        uuid,
        [button.callback_data for row in keyboard.inline_keyboard for button in row],
    )

    try:
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error sending user details: {e}")
        try:
            await update.callback_query.edit_message_caption(
                caption=message,
                reply_markup=keyboard
            )
        except Exception as e2:
            logger.error(f"Fallback to edit_message_caption failed: {e2}")
            await update.callback_query.answer("❌ Ошибка при отображении данных")

    context.user_data["current_user"] = user
    return SELECTING_USER

async def handle_user_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user action with improved SelectionHelper support"""
    # Проверяем авторизацию
    if not check_authorization(update.effective_user):
        await update.callback_query.answer("⛔ Вы не авторизованы для использования этого бота.", show_alert=True)
        return ConversationHandler.END
    
    query = update.callback_query
    await query.answer()

    data = query.data
    is_admin = context.user_data.get('is_admin', False)

    # Handle new SelectionHelper callback patterns
    if data.startswith("user_action_"):
        action_parts = data.split("_")
        if len(action_parts) >= 4:
            action = action_parts[2]
            admin_only_actions = {"edit", "disable", "enable", "reset", "revoke", "delete", "hwid"}
            if not is_admin and action in admin_only_actions:
                await query.answer(INSUFFICIENT_PERMISSIONS_MESSAGE, show_alert=True)
                return SELECTING_USER

            uuid = "_".join(action_parts[3:])  # Handle UUIDs with underscores
            
            if action == "edit":
                return await start_edit_user(update, context, uuid)
            elif action == "refresh":
                await show_user_details(update, context, uuid)
                return SELECTING_USER
            elif action == "subscription":
                user = await user_cache.get_user(uuid)
                if not user or not user.get("subscriptionUrl"):
                    await query.answer("У пользователя нет URL подписки", show_alert=True)
                    return SELECTING_USER

                await _send_subscription_qr(update, context, user)
                await query.answer("URL и QR подписки отправлены", show_alert=False)
                return SELECTING_USER
            elif action == "disable":
                context.user_data["action"] = "disable"
                context.user_data["uuid"] = uuid
                
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Да, отключить", callback_data="confirm_action"),
                        InlineKeyboardButton("❌ Отмена", callback_data=f"view_{uuid}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"⚠️ Вы уверены, что хотите отключить пользователя?\n\nUUID: `{uuid}`",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
                return CONFIRM_ACTION
            elif action == "enable":
                context.user_data["action"] = "enable"
                context.user_data["uuid"] = uuid
                
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Да, включить", callback_data="confirm_action"),
                        InlineKeyboardButton("❌ Отмена", callback_data=f"view_{uuid}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"⚠️ Вы уверены, что хотите включить пользователя?\n\nUUID: `{uuid}`",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
                return CONFIRM_ACTION
            elif action == "reset" and len(action_parts) >= 5 and action_parts[3] == "traffic":
                context.user_data["action"] = "reset"
                context.user_data["uuid"] = "_".join(action_parts[4:])
                
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Да, сбросить", callback_data="confirm_action"),
                        InlineKeyboardButton("❌ Отмена", callback_data=f"view_{uuid}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"⚠️ Вы уверены, что хотите сбросить трафик пользователя?\n\nUUID: `{uuid}`",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
                return CONFIRM_ACTION
            elif action == "revoke":
                context.user_data["action"] = "revoke"
                context.user_data["uuid"] = uuid
                
                keyboard = [
                    [
                        InlineKeyboardButton("✅ Да, отозвать", callback_data="confirm_action"),
                        InlineKeyboardButton("❌ Отмена", callback_data=f"view_{uuid}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    f"⚠️ Вы уверены, что хотите отозвать подписку пользователя?\n\nUUID: `{uuid}`",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
                return CONFIRM_ACTION
            elif action == "delete":
                # Confirm user deletion with extra protection
                await confirm_delete_user(update, context, uuid)
                return CONFIRM_ACTION

    admin_only_prefixes = ("disable_", "enable_", "reset_", "revoke_", "delete_", "edit_", "add_hwid_", "del_hwid_", "confirm_del_hwid_")
    if not is_admin and data.startswith(admin_only_prefixes):
        await query.answer(INSUFFICIENT_PERMISSIONS_MESSAGE, show_alert=True)
        return SELECTING_USER

    # Legacy support for back navigation
    if data == "back_to_list":
        await list_users(update, context)
        return SELECTING_USER

    elif data == "back_to_users":
        await show_users_menu(update, context)
        return USER_MENU

    elif data.startswith("disable_"):
        uuid = data.split("_")[1]
        context.user_data["action"] = "disable"
        context.user_data["uuid"] = uuid
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, отключить", callback_data="confirm_action"),
                InlineKeyboardButton("❌ Отмена", callback_data=f"view_{uuid}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"⚠️ Вы уверены, что хотите отключить пользователя?\n\nUUID: `{uuid}`",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return CONFIRM_ACTION

    elif data.startswith("enable_"):
        uuid = data.split("_")[1]
        context.user_data["action"] = "enable"
        context.user_data["uuid"] = uuid
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, включить", callback_data="confirm_action"),
                InlineKeyboardButton("❌ Отмена", callback_data=f"view_{uuid}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"⚠️ Вы уверены, что хотите включить пользователя?\n\nUUID: `{uuid}`",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return CONFIRM_ACTION

    elif data.startswith("reset_"):
        uuid = data.split("_")[1]
        context.user_data["action"] = "reset"
        context.user_data["uuid"] = uuid
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, сбросить", callback_data="confirm_action"),
                InlineKeyboardButton("❌ Отмена", callback_data=f"view_{uuid}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"⚠️ Вы уверены, что хотите сбросить трафик пользователя?\n\nUUID: `{uuid}`",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return CONFIRM_ACTION

    elif data.startswith("revoke_"):
        uuid = data.split("_")[1]
        context.user_data["action"] = "revoke"
        context.user_data["uuid"] = uuid
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Да, отозвать", callback_data="confirm_action"),
                InlineKeyboardButton("❌ Отмена", callback_data=f"view_{uuid}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"⚠️ Вы уверены, что хотите отозвать подписку пользователя?\n\nUUID: `{uuid}`",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return CONFIRM_ACTION

    elif data.startswith("edit_"):
        uuid = data.split("_")[1]
        return await start_edit_user(update, context, uuid)
        
    elif data.startswith("hwid_"):
        uuid = data.split("_")[1]
        return await show_user_hwid_devices(update, context, uuid)
        
    elif data.startswith("stats_"):
        uuid = data.split("_")[1]
        return await show_user_stats(update, context, uuid)
        
    elif data.startswith("confirm_del_hwid_"):
        parts = data.split("_")
        uuid = parts[3]
        hwid = parts[4]
        return await confirm_delete_hwid_device(update, context, uuid, hwid)

    return SELECTING_USER

@check_admin
async def handle_action_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle action confirmation"""
    query = update.callback_query
    await query.answer()

    data = query.data

    # Handle final delete confirmation
    if data == "final_delete_user":
        return await execute_user_deletion(update, context)

    if data == "confirm_action":
        action = context.user_data.get("action")
        uuid = context.user_data.get("uuid")
        
        if not action or not uuid:
            await query.edit_message_text("❌ Ошибка: действие или UUID не найдены.")
            return SELECTING_USER
        
        result = None
        action_text = ""
        
        if action == "disable":
            result = await UserAPI.disable_user(uuid)
            action_text = "отключен"
        elif action == "enable":
            result = await UserAPI.enable_user(uuid)
            action_text = "включен"
        elif action == "reset":
            result = await UserAPI.reset_user_traffic(uuid)
            action_text = "сброшен трафик"
        elif action == "revoke":
            result = await UserAPI.revoke_user_subscription(uuid)
            action_text = "отозвана подписка"
        
        if result:
            keyboard = [
                [InlineKeyboardButton("👁️ Просмотр пользователя", callback_data=f"view_{uuid}")],
                [InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_list")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"✅ Пользователь успешно {action_text}.\n\nUUID: `{uuid}`",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            keyboard = [
                [InlineKeyboardButton("🔙 Назад", callback_data=f"view_{uuid}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"❌ Не удалось выполнить действие: {action}.\n\nUUID: `{uuid}`",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    else:
        uuid = context.user_data.get("uuid")
        if uuid:
            await show_user_details(update, context, uuid)
        else:
            await show_users_menu(update, context)
            return USER_MENU

    return SELECTING_USER

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text input"""
    # Check if we're waiting for HWID input
    if context.user_data.get("waiting_for") == "hwid":
        return await handle_hwid_input(update, context)
    
    # Check if we're searching for a user
    search_type = context.user_data.get("search_type")

    if not search_type:
        # Check if we're in user creation mode
        if "create_user_fields" in context.user_data and "current_field_index" in context.user_data:
            return await handle_create_user_input(update, context)
    
        # If we're not in any special mode, show an error
        await update.message.reply_text("❌ Ошибка: тип поиска не найден.")
        await show_users_menu(update, context)
        return USER_MENU

    search_value = update.message.text.strip()

    if search_type in ("generic", "username"):
        term = search_value.strip()
        if len(term) < 2:
            back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_users")]])
            await update.message.reply_text(
                "❗ Введите минимум 2 символа для поиска.",
                reply_markup=back_markup
            )
            return WAITING_FOR_INPUT

        matches = await search_users_by_term(term)

        if not matches:
            back_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_users")]])
            try:
                await update.message.reply_text(
                    f"❌ Пользователи по запросу `{escape_markdown(term)}` не найдены.",
                    reply_markup=back_markup,
                    parse_mode="Markdown"
                )
            except Exception:
                await update.message.reply_text(
                    f"❌ Пользователи по запросу '{term}' не найдены.",
                    reply_markup=back_markup
                )
            return USER_MENU

        if len(matches) == 1:
            user = matches[0]
            try:
                message = format_user_details_safe(user)

                keyboard = [
                    [
                        InlineKeyboardButton("🔄 Сбросить трафик", callback_data=f"reset_{user['uuid']}"),
                        InlineKeyboardButton("📝 Редактировать", callback_data=f"edit_{user['uuid']}")
                    ]
                ]

                if user.get('status') == 'ACTIVE':
                    keyboard.append([
                        InlineKeyboardButton("🔴 Отключить", callback_data=f"disable_{user['uuid']}"),
                        InlineKeyboardButton("🔄 Отозвать подписку", callback_data=f"revoke_{user['uuid']}")
                    ])
                else:
                    keyboard.append([
                        InlineKeyboardButton("🟢 Включить", callback_data=f"enable_{user['uuid']}"),
                        InlineKeyboardButton("🔄 Отозвать подписку", callback_data=f"revoke_{user['uuid']}")
                    ])

                keyboard.append([InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_users")])
                reply_markup = InlineKeyboardMarkup(keyboard)

                try:
                    await update.message.reply_text(
                        text=message,
                        reply_markup=reply_markup
                    )
                except Exception as e:
                    logger.error(f"Error sending formatted message with Markdown: {e}")
                    await update.message.reply_text(
                        text=message,
                        reply_markup=reply_markup
                    )

                context.user_data["current_user"] = user
                return SELECTING_USER
            except Exception as e:
                logger.error(f"Error formatting user details in search: {e}")
                keyboard = [[InlineKeyboardButton(f"👤 {user.get('username', 'Без имени')}", callback_data=f"view_{user.get('uuid')}")]]
                keyboard.append([InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_users")])
                reply_markup = InlineKeyboardMarkup(keyboard)

                await update.message.reply_text(
                    text=f"Найден пользователь: {user.get('username','Без имени')}",
                    reply_markup=reply_markup
                )
                context.user_data["current_user"] = user
                return SELECTING_USER

        max_results = 10
        keyboard = []
        message_lines = [
            f"🔍 Найдено {len(matches)} пользователей по запросу `{escape_markdown(term)}`:",
            ""
        ]

        for index, user in enumerate(matches[:max_results], 1):
            username = user.get('username') or 'Без имени'
            status = user.get('status') or 'UNKNOWN'
            message_lines.append(f"{index}. {escape_markdown(username)} — {escape_markdown(str(status))}")
            user_uuid = user.get('uuid')
            if user_uuid:
                keyboard.append([InlineKeyboardButton(f"👤 {username}", callback_data=f"view_{user_uuid}")])

        if len(matches) > max_results:
            message_lines.append("")
            message_lines.append(f"Показаны первые {max_results} результатов. Уточните запрос для более точного поиска.")

        keyboard.append([InlineKeyboardButton("🔙 Назад в меню", callback_data="back_to_users")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        message_text = "\n".join(message_lines)

        try:
            await update.message.reply_text(
                text=message_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error sending search results with Markdown: {e}")
            plain_text = message_text.replace('`', '')
            await update.message.reply_text(
                text=plain_text,
                reply_markup=reply_markup
            )

        return SELECTING_USER

    else:  # Text input
        field = context.user_data["edit_field"]
        user = context.user_data["edit_user"]
        value = update.message.text.strip()
        
        # Process the value based on the field
        if field == "expireAt":
            try:
                # Validate date format
                date_obj = datetime.strptime(value, "%Y-%m-%d")
                value = date_obj.strftime("%Y-%m-%dT00:00:00.000Z")
            except ValueError:
                keyboard = [
                    [InlineKeyboardButton("🔙 Назад", callback_data=f"edit_{user['uuid']}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "❌ Неверный формат даты. Используйте YYYY-MM-DD.",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
                return EDIT_USER
        
        elif field == "trafficLimitBytes":
            try:
                value = int(value)
                if value < 0:
                    raise ValueError("Traffic limit cannot be negative")
            except ValueError:
                keyboard = [
                    [InlineKeyboardButton("🔙 Назад", callback_data=f"edit_{user['uuid']}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "❌ Неверный формат числа. Введите целое число >= 0.",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
                return EDIT_USER
        
        elif field == "telegramId":
            try:
                value = int(value)
            except ValueError:
                keyboard = [
                    [InlineKeyboardButton("🔙 Назад", callback_data=f"edit_{user['uuid']}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "❌ Неверный формат Telegram ID. Введите целое число.",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
                return EDIT_USER
                
        elif field == "hwidDeviceLimit":
            try:
                value = int(value)
                if value < 0:
                    raise ValueError("Device limit cannot be negative")
                
                # Если устанавливается лимит устройств > 0, добавляем в обновляемые данные trafficLimitStrategy=NO_RESET
                if value > 0:
                    update_data["trafficLimitStrategy"] = "NO_RESET"
                    logger.info(f"Auto-setting trafficLimitStrategy=NO_RESET when setting hwidDeviceLimit to {value} for user {user['uuid']}")
            except ValueError:
                keyboard = [
                    [InlineKeyboardButton("🔙 Назад", callback_data=f"edit_{user['uuid']}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await update.message.reply_text(
                    "❌ Неверный формат числа. Введите целое число >= 0.",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
                return EDIT_USER
        
        # Update the user with the new value
        update_data = {field: value}
        result = await UserAPI.update_user(user["uuid"], update_data)
        
        if result:
            keyboard = [
                [InlineKeyboardButton("👁️ Просмотр пользователя", callback_data=f"view_{user['uuid']}")],
                [InlineKeyboardButton("📝 Продолжить редактирование", callback_data=f"edit_{user['uuid']}")],
                [InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_list")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"✅ Поле {field} успешно обновлено.",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            keyboard = [
                [InlineKeyboardButton("🔙 Назад", callback_data=f"edit_{user['uuid']}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"❌ Не удалось обновить поле {field}.",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        
        return EDIT_USER

@check_admin
async def start_create_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start creating a new user - first show template selection"""
    # Clear any previous user creation data
    context.user_data.pop("create_user", None)
    context.user_data.pop("create_user_fields", None)
    context.user_data.pop("current_field_index", None)
    context.user_data.pop("search_type", None)  # Clear search type to avoid confusion
    context.user_data.pop("using_template", None)
    
    # Initialize user creation data
    context.user_data["create_user"] = {}
    
    # Show template selection
    await show_template_selection(update, context)
    return CREATE_USER_FIELD

async def show_template_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show template selection menu"""
    from modules.utils.presets import get_template_names
    
    message = "🎯 *Создание пользователя*\n\n"
    message += "Выберите готовый шаблон или создайте пользователя вручную:\n\n"
    message += "📋 *Готовые шаблоны* содержат все необходимые настройки\n"
    message += "⚙️ *Ручное создание* позволяет настроить каждое поле отдельно"
    
    # Создаем кнопки для шаблонов
    keyboard = []
    templates = get_template_names()
    
    # Добавляем кнопки шаблонов по 2 в ряду
    for i in range(0, len(templates), 2):
        row = []
        for j in range(2):
            if i + j < len(templates):
                template_name = templates[i + j]
                row.append(InlineKeyboardButton(
                    template_name, 
                    callback_data=f"template_{template_name}"
                ))
        keyboard.append(row)
    
    # Добавляем кнопки управления
    keyboard.extend([
        [InlineKeyboardButton("⚙️ Создать вручную", callback_data="create_manual")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

async def handle_template_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, template_name: str):
    """Handle template selection and show confirmation"""
    from modules.utils.presets import get_template_by_name, format_template_info
    
    template = get_template_by_name(template_name)
    if not template:
        await update.callback_query.edit_message_text(
            "❌ Шаблон не найден. Попробуйте еще раз.",
            parse_mode="Markdown"
        )
        return CREATE_USER_FIELD
    
    # Сохраняем выбранный шаблон
    context.user_data["selected_template"] = template_name
    context.user_data["using_template"] = True
    
    # Показываем информацию о шаблоне
    message = "📋 *Предпросмотр шаблона*\n\n"
    message += format_template_info(template_name)
    message += "\n\n💡 *Что дальше?*\n"
    message += "• Вы можете использовать шаблон как есть, только указав имя пользователя\n"
    message += "• Или настроить дополнительные поля (email, Telegram ID, тег и т.д.)"
    
    keyboard = [
        [InlineKeyboardButton("✅ Использовать шаблон", callback_data=f"use_template_{template_name}")],
        [InlineKeyboardButton("⚙️ Настроить дополнительно", callback_data=f"customize_template_{template_name}")],
        [InlineKeyboardButton("🔙 Выбрать другой шаблон", callback_data="back_to_templates")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        text=message,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def start_template_creation(update: Update, context: ContextTypes.DEFAULT_TYPE, template_name: str, customize: bool = False):
    """Start user creation with selected template"""
    from modules.utils.presets import apply_template_to_user_data
    
    # Применяем шаблон
    context.user_data["create_user"] = apply_template_to_user_data({}, template_name)
    context.user_data["using_template"] = True
    context.user_data["template_name"] = template_name
    
    if customize:
        # Полная настройка - проходим все поля
        context.user_data["create_user_fields"] = list(USER_FIELDS.keys())
        context.user_data["current_field_index"] = 0
    else:
        # Только имя пользователя и опциональные поля
        context.user_data["create_user_fields"] = ["username"]
        context.user_data["current_field_index"] = 0
    
    # Начинаем с первого поля
    await ask_for_field(update, context)
    return CREATE_USER_FIELD

async def ask_for_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask for a field value when creating a user"""
    fields = context.user_data["create_user_fields"]
    index = context.user_data["current_field_index"]

    if index >= len(fields):
        # All fields collected, create the user
        return await finish_create_user(update, context)

    field = fields[index]
    field_name = USER_FIELDS[field]
    
    # Проверяем, используется ли шаблон
    using_template = context.user_data.get("using_template", False)
    current_value = context.user_data["create_user"].get(field)
    
    # Если используется шаблон и поле уже заполнено, показываем текущее значение
    template_info = ""
    if using_template and current_value is not None:
        if field == "trafficLimitBytes":
            from modules.utils.formatters import format_bytes
            display_value = "Безлимитный" if current_value == 0 else format_bytes(current_value)
            template_info = f"\n🎯 *Значение из шаблона:* {display_value}"
        elif field == "hwidDeviceLimit":
            if current_value == 0:
                display_value = "Без лимита"
            elif current_value == 1:
                display_value = "1 устройство"
            elif current_value in [2, 3, 4]:
                display_value = f"{current_value} устройства"
            else:
                display_value = f"{current_value} устройств"
            template_info = f"\n🎯 *Значение из шаблона:* {display_value}"
        elif field == "trafficLimitStrategy":
            strategy_map = {
                "NO_RESET": "Без сброса",
                "DAY": "Ежедневно",
                "WEEK": "Еженедельно",
                "MONTH": "Ежемесячно"
            }
            display_value = strategy_map.get(current_value, current_value)
            template_info = f"\n🎯 *Значение из шаблона:* {display_value}"
        else:
            template_info = f"\n🎯 *Значение из шаблона:* {current_value}"

    # Special handling for username when using template
    if field == "username":
        template_name = context.user_data.get("template_name", "")
        message = f"👤 *Введите имя пользователя*\n\n"
        if using_template:
            message += f"Выбранный шаблон: {template_name}\n"
            message += "Введите уникальное имя пользователя (6-34 символа, только буквы, цифры, дефисы и подчеркивания):"
        else:
            message += "Введите имя пользователя:"
        
        # После ввода имени предлагаем дополнительные поля
        if using_template and len(fields) == 1:  # Только username в списке полей
            keyboard = [
                [InlineKeyboardButton("✅ Создать пользователя", callback_data="finish_template_user")],
                [InlineKeyboardButton("⚙️ Добавить дополнительные поля", callback_data="add_optional_fields")],
                [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")],
                [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
            ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)

    # Special handling for expireAt
    elif field == "expireAt":
        # Default to 30 days from now
        message = f"📅 *Выберите или введите дату истечения*{template_info}\n\n"
        message += "Введите дату в формате YYYY-MM-DD или выберите один из пресетов ниже:"
        
        # Создаем пресеты дат с разными периодами
        today = datetime.now()
        keyboard = [
            [
                InlineKeyboardButton("1 день", callback_data=f"create_date_{(today + timedelta(days=1)).strftime('%Y-%m-%d')}"),
                InlineKeyboardButton("3 дня", callback_data=f"create_date_{(today + timedelta(days=3)).strftime('%Y-%m-%d')}"),
                InlineKeyboardButton("7 дней", callback_data=f"create_date_{(today + timedelta(days=7)).strftime('%Y-%m-%d')}")
            ],
            [
                InlineKeyboardButton("10 дней", callback_data=f"create_date_{(today + timedelta(days=10)).strftime('%Y-%m-%d')}"),
                InlineKeyboardButton("30 дней", callback_data=f"create_date_{(today + timedelta(days=30)).strftime('%Y-%m-%d')}"),
                InlineKeyboardButton("60 дней", callback_data=f"create_date_{(today + timedelta(days=60)).strftime('%Y-%m-%d')}")
            ],
            [
                InlineKeyboardButton("90 дней", callback_data=f"create_date_{(today + timedelta(days=90)).strftime('%Y-%m-%d')}"),
                InlineKeyboardButton("180 дней", callback_data=f"create_date_{(today + timedelta(days=180)).strftime('%Y-%m-%d')}"),
                InlineKeyboardButton("365 дней", callback_data=f"create_date_{(today + timedelta(days=365)).strftime('%Y-%m-%d')}")
            ],
            [InlineKeyboardButton("80 лет 👑", callback_data=f"create_date_{(today + timedelta(days=365*80)).strftime('%Y-%m-%d')}")],
            [InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        
        return CREATE_USER_FIELD

    elif field == "activeInternalSquads":
        await _show_internal_squads_selector(update, context)
        return CREATE_USER_FIELD
    
    # Special handling for trafficLimitBytes
    elif field == "trafficLimitBytes":
        message = f"📈 *Выберите лимит трафика*\n\nВыберите один из пресетов или введите своё значение в байтах:"
        
        # Создаём пресеты трафика с шагом по 200 ГБ до 1 ТБ (и другие популярные)
        # Конвертация в байты: умножаем на 1024^3
        GB = 1024 * 1024 * 1024
        keyboard = [
            [
                InlineKeyboardButton("50 ГБ", callback_data=f"create_traffic_{50 * GB}"),
                InlineKeyboardButton("100 ГБ", callback_data=f"create_traffic_{100 * GB}"),
                InlineKeyboardButton("200 ГБ", callback_data=f"create_traffic_{200 * GB}")
            ],
            [
                InlineKeyboardButton("400 ГБ", callback_data=f"create_traffic_{400 * GB}"),
                InlineKeyboardButton("600 ГБ", callback_data=f"create_traffic_{600 * GB}"),
                InlineKeyboardButton("800 ГБ", callback_data=f"create_traffic_{800 * GB}")
            ],
            [
                InlineKeyboardButton("1 ТБ", callback_data=f"create_traffic_{1024 * GB}"),
                InlineKeyboardButton("2 ТБ", callback_data=f"create_traffic_{2048 * GB}"),
                InlineKeyboardButton("5 ТБ", callback_data=f"create_traffic_{5120 * GB}")
            ],
            [
                InlineKeyboardButton("Безлимитный", callback_data="create_traffic_0")
            ],
            [InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
        ]
        
        # Логирование для отладки
        logger.debug(f"Setting up traffic limit buttons with callback data: create_traffic_0 for unlimited")
        logger.debug(f"First button callback: {keyboard[0][0].callback_data}")
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        
        return CREATE_USER_FIELD

    # Special handling for description
    elif field == "description":
        message = f"📝 *Введите описание пользователя*\n\nВыберите один из шаблонов или введите своё описание:"
        
        # Создаём шаблоны для часто используемых описаний
        keyboard = [
            [InlineKeyboardButton("Стандартный пользователь", callback_data="create_desc_Стандартный пользователь")],
            [InlineKeyboardButton("VIP-клиент", callback_data="create_desc_VIP-клиент")],
            [InlineKeyboardButton("Тестовый аккаунт", callback_data="create_desc_Тестовый аккаунт")],
            [InlineKeyboardButton("Корпоративный клиент", callback_data="create_desc_Корпоративный клиент")],
            [InlineKeyboardButton("Демо-аккаунт", callback_data="create_desc_Демо-аккаунт")],
            [InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        
        return CREATE_USER_FIELD

    elif field == "telegramId":
        message = (
            f"📱 *Введите Telegram ID*{template_info}\n\n"
            "Введите ID вручную или выберите пользователя через Telegram-панель."
        )
        keyboard = [
            [InlineKeyboardButton("👤 Выбрать пользователя", callback_data="request_user_for_telegram_id")],
            [InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

        return CREATE_USER_FIELD
    
    # Special handling for hwidDeviceLimit
    elif field == "hwidDeviceLimit":
        message = f"📱 *Выберите лимит устройств*\n\nВыберите один из пресетов или введите своё значение:"
        
        # Создаём пресеты для лимита устройств
        keyboard = [
            [
                InlineKeyboardButton("1 устройство", callback_data="create_device_1"),
                InlineKeyboardButton("2 устройства", callback_data="create_device_2"),
                InlineKeyboardButton("3 устройства", callback_data="create_device_3")
            ],
            [
                InlineKeyboardButton("4 устройства", callback_data="create_device_4"),
                InlineKeyboardButton("5 устройств", callback_data="create_device_5"),
                InlineKeyboardButton("10 устройств", callback_data="create_device_10")
            ],
            [
                InlineKeyboardButton("Без лимита (0)", callback_data="create_device_0")
            ],
            [InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        
        return CREATE_USER_FIELD
        
    # Special handling for trafficLimitStrategy
    elif field == "trafficLimitStrategy":
        keyboard = [
            [InlineKeyboardButton("NO_RESET - Без сброса", callback_data="create_field_NO_RESET")],
            [InlineKeyboardButton("DAY - Ежедневно", callback_data="create_field_DAY")],
            [InlineKeyboardButton("WEEK - Еженедельно", callback_data="create_field_WEEK")],
            [InlineKeyboardButton("MONTH - Ежемесячно", callback_data="create_field_MONTH")],
            [InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = f"🔄 Выберите стратегию сброса трафика:"
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        
        return CREATE_USER_FIELD

    else:
        message = f"Введите {field_name}:{template_info}"

    keyboard = [[InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")]]

    # Для шаблонов добавляем кнопку "использовать значение из шаблона"
    if using_template and current_value is not None and field not in ["username"]:
        if field == "trafficLimitBytes":
            display_value = "Безлимитный" if current_value == 0 else format_bytes(current_value)
            keyboard.insert(0, [InlineKeyboardButton(f"✅ Оставить: {display_value}", callback_data=f"use_template_value_{field}")])
        elif field == "hwidDeviceLimit":
            if current_value == 0:
                display_value = "Без лимита"
            elif current_value == 1:
                display_value = "1 устройство"
            elif current_value in [2, 3, 4]:
                display_value = f"{current_value} устройства"
            else:
                display_value = f"{current_value} устройств"
            keyboard.insert(0, [InlineKeyboardButton(f"✅ Оставить: {display_value}", callback_data=f"use_template_value_{field}")])
        elif field == "trafficLimitStrategy":
            strategy_map = {
                "NO_RESET": "Без сброса",
                "DAY": "Ежедневно", 
                "WEEK": "Еженедельно",
                "MONTH": "Ежемесячно"
            }
            display_value = strategy_map.get(current_value, current_value)
            keyboard.insert(0, [InlineKeyboardButton(f"✅ Оставить: {display_value}", callback_data=f"use_template_value_{field}")])
        else:
            keyboard.insert(0, [InlineKeyboardButton(f"✅ Оставить: {current_value}", callback_data=f"use_template_value_{field}")])

    # Add cancel button
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_create")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    return CREATE_USER_FIELD

@check_admin
async def handle_create_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user input when creating a user"""
    query = update.callback_query

    if query:
        await query.answer()
        data = query.data
        
        if data == "skip_field":
            fields = context.user_data.get("create_user_fields", [])
            index = context.user_data.get("current_field_index", 0)
            if index < len(fields) and fields[index] == "telegramId" and query.message:
                await query.message.reply_text("Telegram ID пропущен.", reply_markup=ReplyKeyboardRemove())
            context.user_data.pop("create_user_description_prefix", None)
            # Skip this field
            context.user_data["current_field_index"] += 1
            await ask_for_field(update, context)
            return CREATE_USER_FIELD
        
        # elif data == "cancel_create":
        #     # Cancel user creation - handled by separate handler
        #     await show_users_menu(update, context)
        #     return USER_MENU
        
        elif data == "back_to_main":
            fields = context.user_data.get("create_user_fields", [])
            index = context.user_data.get("current_field_index", 0)
            if index < len(fields) and fields[index] == "telegramId" and query.message:
                await query.message.reply_text("Возвращаемся в главное меню.", reply_markup=ReplyKeyboardRemove())
            # Return to main menu
            await show_main_menu(update, context)
            return MAIN_MENU
        
        # Обработка выбора шаблона
        elif data.startswith("template_"):
            template_name = data[9:]  # убираем "template_"
            await handle_template_selection(update, context, template_name)
            return CREATE_USER_FIELD
        
        elif data == "create_manual":
            # Создание вручную - используем весь список полей
            context.user_data["create_user_fields"] = list(USER_FIELDS.keys())
            context.user_data["current_field_index"] = 0
            context.user_data["using_template"] = False
            await ask_for_field(update, context)
            return CREATE_USER_FIELD
        
        elif data == "back_to_templates":
            await show_template_selection(update, context)
            return CREATE_USER_FIELD
        
        elif data.startswith("use_template_"):
            template_name = data[13:]  # убираем "use_template_"
            await start_template_creation(update, context, template_name, customize=False)
            return CREATE_USER_FIELD
        
        elif data.startswith("customize_template_"):
            template_name = data[19:]  # убираем "customize_template_"
            await start_template_creation(update, context, template_name, customize=True)
            return CREATE_USER_FIELD
        
        elif data == "finish_template_user":
            # Завершаем создание пользователя с шаблоном
            return await finish_create_user(update, context)
        
        elif data == "add_optional_fields":
            # Добавляем дополнительные поля
            optional_fields = ["expireAt", "activeInternalSquads", "telegramId", "email", "tag"]
            current_fields = context.user_data["create_user_fields"]
            # Добавляем поля, которых еще нет
            for field in optional_fields:
                if field not in current_fields:
                    current_fields.append(field)
            context.user_data["create_user_fields"] = current_fields
            context.user_data["current_field_index"] += 1  # переходим к следующему полю
            await ask_for_field(update, context)
            return CREATE_USER_FIELD
        
        elif data.startswith("use_template_value_"):
            # Использовать значение из шаблона для поля
            field_name = data[19:]  # убираем "use_template_value_"
            # Значение уже есть в данных пользователя из шаблона
            context.user_data["current_field_index"] += 1
            await ask_for_field(update, context)
            return CREATE_USER_FIELD
        
        elif data.startswith("create_field_"):
            # Handle selection for fields with predefined values
            value = data[13:]  # Берем всё, что идет после "create_field_", чтобы избежать обрезания значений
            fields = context.user_data["create_user_fields"]
            index = context.user_data["current_field_index"]
            field = fields[index]
            
            # Логирование для отладки, чтобы видеть какое значение устанавливается
            logger.info(f"Setting field {field} to value '{value}' from callback data '{data}'")
            
            context.user_data["create_user"][field] = value
            context.user_data["current_field_index"] += 1
            await ask_for_field(update, context)
            return CREATE_USER_FIELD
            
        elif data.startswith("create_date_"):
            # Handle selection for date presets
            date_str = data[12:] # Получаем YYYY-MM-DD из коллбэка
            fields = context.user_data["create_user_fields"]
            index = context.user_data["current_field_index"]
            field = fields[index]
            
            if field == "expireAt":
                # Конвертируем дату в нужный формат
                try:
                    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                    value = date_obj.strftime("%Y-%m-%dT00:00:00.000Z")
                    context.user_data["create_user"][field] = value
                    
                    # Показываем сообщение о выбранной дате
                    await query.edit_message_text(
                        f"✅ Выбрана дата истечения: {date_str}",
                        parse_mode="Markdown"
                    )
                    
                    # Переходим к следующему полю
                    context.user_data["current_field_index"] += 1
                    await ask_for_field(update, context)
                except ValueError as e:
                    logger.error(f"Error parsing date: {e}")
                    await query.edit_message_text(
                        "❌ Ошибка при обработке даты. Пожалуйста, выберите другую дату или введите вручную.",
                        parse_mode="Markdown"
                    )
            
            return CREATE_USER_FIELD

        elif data.startswith("create_squad_toggle_"):
            squad_uuid = data.replace("create_squad_toggle_", "", 1)
            fields = context.user_data["create_user_fields"]
            index = context.user_data["current_field_index"]
            field = fields[index]

            if field == "activeInternalSquads":
                selected = context.user_data["create_user"].get("activeInternalSquads", [])
                if squad_uuid in selected:
                    selected = [uuid for uuid in selected if uuid != squad_uuid]
                else:
                    selected = [*selected, squad_uuid]
                context.user_data["create_user"]["activeInternalSquads"] = selected
                await _show_internal_squads_selector(update, context)
            return CREATE_USER_FIELD

        elif data == "create_squad_done":
            fields = context.user_data["create_user_fields"]
            index = context.user_data["current_field_index"]
            field = fields[index]

            if field == "activeInternalSquads":
                selected = context.user_data["create_user"].get("activeInternalSquads", [])
                readable = f"{len(selected)} шт." if selected else "не выбраны"
                await query.edit_message_text(
                    f"✅ Внутренние сквады: {readable}",
                    parse_mode="Markdown",
                )
                context.user_data["current_field_index"] += 1
                await ask_for_field(update, context)
            return CREATE_USER_FIELD
            
        elif data.startswith("create_traffic_"):
            # Handle selection for traffic limit presets
            try:
                # Отладочный лог для анализа входящих данных
                logger.debug(f"Processing traffic selection with data: '{data}'")
                
                # Получаем значение в байтах из коллбэка
                traffic_bytes_str = data[14:]  # отрезаем префикс 'create_traffic_'
                logger.debug(f"Extracted traffic value string: '{traffic_bytes_str}'")
                
                fields = context.user_data["create_user_fields"]
                index = context.user_data["current_field_index"]
                field = fields[index]
                
                if field == "trafficLimitBytes":
                    # Преобразуем строку в число, игнорируя разделители
                    sanitized_value = traffic_bytes_str.strip().replace(' ', '').replace(',', '')
                    sanitized_value = sanitized_value.lstrip('_')
                    sanitized_value = ''.join(ch for ch in sanitized_value if ch.isdigit())
                    value = int(sanitized_value) if sanitized_value else 0
                    context.user_data["create_user"][field] = value
                    
                    # Форматируем значение в читаемый вид
                    from modules.utils.formatters import format_bytes
                    readable_value = format_bytes(value)
                    
                    # Для безлимитного трафика (0) показываем особое сообщение
                    if value == 0:
                        readable_value = "Безлимитный"
                    
                    # Показываем сообщение о выбранном лимите
                    await query.edit_message_text(
                        f"✅ Выбран лимит трафика: {readable_value}",
                        parse_mode="Markdown"
                    )
                    
                    # Переходим к следующему полю
                    context.user_data["current_field_index"] += 1
                    await ask_for_field(update, context)
            except ValueError as e:
                logger.error(f"Error parsing traffic limit: {e}")
                await query.edit_message_text(
                    "❌ Ошибка при обработке лимита трафика. Пожалуйста, выберите другое значение или введите вручную.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Unexpected error processing traffic limit: {e}", exc_info=True)
                await query.edit_message_text(
                    "❌ Произошла ошибка. Пожалуйста, попробуйте другое значение или обратитесь к администратору.",
                    parse_mode="Markdown"
                )
            
            return CREATE_USER_FIELD
            
        elif data.startswith("create_desc_"):
            try:
                # Отладочный лог для анализа входящих данных
                logger.debug(f"Processing description template with data: '{data}'")
                
                # Получаем текст описания из коллбэка
                description = data[12:]  # отрезаем префикс 'create_desc_'
                logger.debug(f"Extracted description: '{description}'")
                
                fields = context.user_data["create_user_fields"]
                index = context.user_data["current_field_index"]
                field = fields[index]
                
                if field == "description":
                    context.user_data["create_user_description_prefix"] = description
                    context.user_data["create_user"][field] = description
                    
                    await query.edit_message_text(
                        (
                            f"✅ Выбрано описание: {description} (по шаблону)\n\n"
                            "дополните описание"
                        ),
                        parse_mode="Markdown"
                    )
            except Exception as e:
                logger.error(f"Unexpected error processing description template: {e}", exc_info=True)
                await query.edit_message_text(
                    "❌ Произошла ошибка при обработке шаблона описания. Пожалуйста, введите описание вручную.",
                    parse_mode="Markdown"
                )
                context.user_data["current_field_index"] += 1
                await ask_for_field(update, context)
            
            return CREATE_USER_FIELD

        elif data == "request_user_for_telegram_id":
            fields = context.user_data["create_user_fields"]
            index = context.user_data["current_field_index"]
            field = fields[index]

            if field == "telegramId":
                await _send_user_request_keyboard(
                    update,
                    prompt=(
                        "Telegram откроет панель выбора пользователя.\n"
                        "После выбора я подставлю его Telegram ID в подписку."
                    ),
                )
                await query.answer("Появилась кнопка выбора пользователя", show_alert=False)
            return CREATE_USER_FIELD
            
        elif data.startswith("create_device_"):
            # Handle selection for device limit presets
            try:
                # Отладочный лог для анализа входящих данных
                logger.debug(f"Processing device limit selection with data: '{data}'")
                
                # Получаем значение лимита устройств из коллбэка
                device_limit_str = data[14:]  # отрезаем префикс 'create_device_'
                logger.debug(f"Extracted device limit value string: '{device_limit_str}'")
                
                fields = context.user_data["create_user_fields"]
                index = context.user_data["current_field_index"]
                field = fields[index]
                
                if field == "hwidDeviceLimit":
                    # Преобразуем строку в число
                    value = int(device_limit_str)
                    context.user_data["create_user"][field] = value
                    
                    # Формируем читаемое представление (с правильным окончанием для числа устройств)
                    if value == 0:
                        readable_value = "Без лимита"
                    elif value == 1:
                        readable_value = "1 устройство"
                    elif value in [2, 3, 4]:
                        readable_value = f"{value} устройства"
                    else:
                        readable_value = f"{value} устройств"
                    
                    # Если установлен лимит устройств > 0, нужно также установить trafficLimitStrategy = NO_RESET
                    if value > 0:
                        # Явно устанавливаем стратегию NO_RESET
                        context.user_data["create_user"]["trafficLimitStrategy"] = "NO_RESET"
                        logger.info(f"Auto-setting trafficLimitStrategy=NO_RESET for user with hwidDeviceLimit={value}")
                    
                    # Показываем сообщение о выбранном лимите
                    await query.edit_message_text(
                        f"✅ Выбран лимит устройств: {readable_value}",
                        parse_mode="Markdown"
                    )
                    
                    # Переходим к следующему полю
                    context.user_data["current_field_index"] += 1
                    await ask_for_field(update, context)
            except ValueError as e:
                logger.error(f"Error parsing device limit: {e}")
                await query.edit_message_text(
                    "❌ Ошибка при обработке лимита устройств. Пожалуйста, выберите другое значение или введите вручную.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Unexpected error processing device limit: {e}", exc_info=True)
                await query.edit_message_text(
                    "❌ Произошла ошибка. Пожалуйста, попробуйте другое значение или обратитесь к администратору.",
                    parse_mode="Markdown"
                )
            
            return CREATE_USER_FIELD

    else:  # Text/user_shared input
        try:
            fields = context.user_data["create_user_fields"]
            index = context.user_data["current_field_index"]
            field = fields[index]
            user_shared = update.message.user_shared
            value = (update.message.text or "").strip()
            
            # Process the value based on the field
            if field == "username":
                # Validate username format
                if not re.match(r"^[a-zA-Z0-9_-]{6,34}$", value):
                    keyboard = [[InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        "❌ Неверный формат имени пользователя. Используйте только буквы, цифры, подчеркивания и дефисы. Длина должна быть от 6 до 34 символов.",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                    return CREATE_USER_FIELD
            
            elif field == "expireAt":
                try:
                    # Validate date format
                    date_obj = datetime.strptime(value, "%Y-%m-%d")
                    value = date_obj.strftime("%Y-%m-%dT00:00:00.000Z")
                except ValueError:
                    keyboard = [[InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        "❌ Неверный формат даты. Используйте YYYY-MM-DD.",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                    return CREATE_USER_FIELD
            
            elif field == "trafficLimitBytes":
                try:
                    value = int(value)
                    if value < 0:
                        raise ValueError("Traffic limit cannot be negative")
                except ValueError:
                    keyboard = [[InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        "❌ Неверный формат числа. Введите целое число >= 0.",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                    return CREATE_USER_FIELD
            
            elif field == "telegramId":
                try:
                    if user_shared:
                        value = int(user_shared.user_id)
                    else:
                        value = int(value)
                        await update.message.reply_text(
                            f"✅ Telegram ID сохранен: {value}",
                            reply_markup=ReplyKeyboardRemove(),
                        )
                except ValueError:
                    keyboard = [[InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        "❌ Неверный формат Telegram ID. Введите целое число.",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                    return CREATE_USER_FIELD

                if user_shared:
                    await update.message.reply_text(
                        f"✅ Telegram ID выбранного пользователя: {value}",
                        reply_markup=ReplyKeyboardRemove(),
                    )
            
            elif field == "tag":
                if value and not re.match(r"^[A-Z0-9_]{1,16}$", value):
                    keyboard = [[InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        "❌ Неверный формат тега. Используйте только ЗАГЛАВНЫЕ буквы, цифры и подчеркивания. Максимальная длина - 16 символов.",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                    return CREATE_USER_FIELD
            
            elif field == "email":
                if value and not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", value):
                    keyboard = [[InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        "❌ Неверный формат email.",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                    return CREATE_USER_FIELD
                    
            elif field == "hwidDeviceLimit":
                try:
                    value = int(value)
                    if value < 0:
                        raise ValueError("Device limit cannot be negative")
                    
                    # Если установлен лимит устройств > 0, нужно также установить trafficLimitStrategy = NO_RESET
                    if value > 0:
                        # Явно устанавливаем стратегию NO_RESET
                        context.user_data["create_user"]["trafficLimitStrategy"] = "NO_RESET"
                        logger.info(f"Auto-setting trafficLimitStrategy=NO_RESET for user with hwidDeviceLimit={value}")
                except ValueError:
                    keyboard = [[InlineKeyboardButton("⏩ Пропустить", callback_data="skip_field")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        "❌ Неверный формат числа. Введите целое число >= 0.",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                    return CREATE_USER_FIELD

            elif field == "description":
                description_prefix = context.user_data.pop("create_user_description_prefix", None)
                if description_prefix:
                    if value:
                        value = f"{description_prefix} {value}".strip()
                    else:
                        value = description_prefix
            
            # Store the value and move to the next field
            context.user_data["create_user"][field] = value
            
            # Если устанавливается лимит устройств, проверим и установим правильную стратегию трафика
            if field == "hwidDeviceLimit" and isinstance(value, int) and value > 0:
                context.user_data["create_user"]["trafficLimitStrategy"] = "NO_RESET"
                logger.info(f"Setting trafficLimitStrategy=NO_RESET because hwidDeviceLimit={value}")
                
            context.user_data["current_field_index"] += 1
            
            # Log the current state of the user creation data
            logger.debug(f"Current user creation data: {context.user_data['create_user']}")
            
            # Ask for the next field
            await ask_for_field(update, context)
            return CREATE_USER_FIELD
            
        except Exception as e:
            # Handle any unexpected errors
            logger.error(f"Error in handle_create_user_input: {e}")
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_users")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"❌ Произошла ошибка при обработке ввода: {str(e)}",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return USER_MENU

async def finish_create_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finish creating a user"""
    user_data = context.user_data["create_user"]

    # Generate random username if not provided (20 characters, alphanumeric)
    if "username" not in user_data or not user_data["username"]:
        characters = string.ascii_letters + string.digits
        random_username = ''.join(random.choice(characters) for _ in range(20))
        user_data["username"] = random_username
        logger.info(f"Generated random username: {random_username}")

    # Set default values for required fields if not provided
    if "trafficLimitStrategy" not in user_data:
        user_data["trafficLimitStrategy"] = "NO_RESET"
    
    # Set default traffic limit (100 GB in bytes) if not provided
    if "trafficLimitBytes" not in user_data:
        user_data["trafficLimitBytes"] = 100 * 1024 * 1024 * 1024  # 100 GB in bytes
    
    # Set default device limit if not provided
    if "hwidDeviceLimit" not in user_data:
        user_data["hwidDeviceLimit"] = 1
    
    # Set default description if not provided
    if "description" not in user_data or not user_data["description"]:
        user_data["description"] = f"Автоматически созданный пользователь {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    
    # Set default reset day if not provided
    if "resetDay" not in user_data:
        user_data["resetDay"] = 1

    # Если установлен лимит устройств (hwidDeviceLimit), убедимся, что стратегия сброса трафика установлена правильно
    if "hwidDeviceLimit" in user_data and user_data.get("hwidDeviceLimit", 0) > 0:
        # Принудительно устанавливаем NO_RESET для корректной работы с лимитом устройств
        user_data["trafficLimitStrategy"] = "NO_RESET"
        logger.info(f"Setting trafficLimitStrategy=NO_RESET for user with hwidDeviceLimit={user_data['hwidDeviceLimit']}")

    if "expireAt" not in user_data:
        # Default to 30 days from now
        user_data["expireAt"] = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%dT00:00:00.000Z")

    # Log data for debugging
    logger.debug(f"Creating user with data: {user_data}")
    logger.info(f"Creating user with trafficLimitStrategy: {user_data.get('trafficLimitStrategy')}")

    # Create the user
    result = await UserAPI.create_user(user_data)

    if result:
        keyboard = [
            [InlineKeyboardButton("👁️ Просмотр пользователя", callback_data=f"view_{result['uuid']}")],
            [InlineKeyboardButton("🔗 URL и QR подписки", callback_data=f"user_action_subscription_{result['uuid']}")],
            [InlineKeyboardButton("🔙 Назад в главное меню", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = f"✅ Пользователь успешно создан!\n\n"
        message += f"👤 Имя: {escape_markdown(result.get('username',''))}\n"
        message += f"🆔 UUID: `{result.get('uuid','')}`\n"
        if result.get('shortUuid'):
            message += f"🔑 Короткий UUID: `{result['shortUuid']}`\n"
        # v208 может не возвращать subscriptionUuid — показываем только URL, если есть
        if result.get('subscriptionUrl'):
            message += f"\n🔗 URL подписки: `{result['subscriptionUrl']}`\n"
        # Clear creation context now that user is created
        for key in (
            "create_user",
            "create_user_fields",
            "current_field_index",
            "using_template",
            "search_type",
            "waiting_for",
            "create_user_description_prefix",
            "available_internal_squads",
        ):
            context.user_data.pop(key, None)

        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            if result.get("subscriptionUrl"):
                await _send_subscription_qr(
                    update,
                    context,
                    result,
                    reply_to_message_id=update.callback_query.message.message_id,
                )
        else:
            summary_message = await update.message.reply_text(
                text=message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            if result.get("subscriptionUrl"):
                await _send_subscription_qr(
                    update,
                    context,
                    result,
                    reply_to_message_id=summary_message.message_id,
                )
        
        return SELECTING_USER
    else:
        keyboard = [
            [InlineKeyboardButton("🔄 Попробовать снова", callback_data="create_user")],
            [InlineKeyboardButton("🔙 Назад в главное меню", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        error_message = "❌ Не удалось создать пользователя. "
        
        # Check for specific validation errors
        if "username" not in user_data:
            error_message += "Отсутствует имя пользователя."
        elif "trafficLimitStrategy" not in user_data:
            error_message += "Отсутствует стратегия сброса трафика."
        elif "expireAt" not in user_data:
            error_message += "Отсутствует дата истечения."
        else:
            error_message += "Пожалуйста, проверьте введенные данные."
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=error_message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                text=error_message,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        
        return MAIN_MENU

async def show_user_hwid_devices(update: Update, context: ContextTypes.DEFAULT_TYPE, uuid: str):
    """Show user HWID devices"""
    devices = await UserAPI.get_user_hwid_devices(uuid)
    user = context.user_data.get("current_user") or await UserAPI.get_user_by_uuid(uuid)
    
    if not devices:
        keyboard = [
            [InlineKeyboardButton("➕ Добавить устройство", callback_data=f"add_hwid_{uuid}")],
            [InlineKeyboardButton("🔙 Назад", callback_data=f"view_{uuid}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            f"📱 *Устройства HWID пользователя {escape_markdown(user['username'])}*\n\n"
            f"Устройства не найдены. Вы можете добавить новое устройство.",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return SELECTING_USER
    
    message = f"📱 *Устройства HWID пользователя {escape_markdown(user['username'])}*\n\n"
    
    for i, device in enumerate(devices):
        message += f"{i+1}. HWID: `{device['hwid']}`\n"
        if device.get("platform"):
            message += f"   📱 Платформа: {escape_markdown(device['platform'])}\n"
        if device.get("osVersion"):
            message += f"   🖥️ Версия ОС: {escape_markdown(device['osVersion'])}\n"
        if device.get("deviceModel"):
            message += f"   📱 Модель: {escape_markdown(device['deviceModel'])}\n"
        if device.get("createdAt"):
            message += f"   🕒 Добавлено: {device['createdAt'][:10]}\n"
        message += "\n"
    
    # Add action buttons
    keyboard = [
        [InlineKeyboardButton("➕ Добавить устройство", callback_data=f"add_hwid_{uuid}")],
        [InlineKeyboardButton("🔙 Назад к пользователю", callback_data=f"view_{uuid}")]
    ]
    
    # Add delete buttons for each device
    for i, device in enumerate(devices):
        keyboard.append([
            InlineKeyboardButton(f"❌ Удалить {i+1}", callback_data=f"del_hwid_{uuid}_{device['hwid']}")
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        text=message,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    
    return SELECTING_USER

async def show_user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE, uuid):
    """Show user statistics"""
    user = context.user_data.get("current_user") or await UserAPI.get_user_by_uuid(uuid)
    
    # Get usage for last 30 days
    end_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    usage = await UserAPI.get_user_usage_by_range(uuid, start_date, end_date)
    
    if not usage:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data=f"view_{uuid}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            f"❌ Статистика не найдена или ошибка при получении данных.\n\nПользователь: {escape_markdown(user['username'])}",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return SELECTING_USER
    
    message = f"📊 *Статистика пользователя {escape_markdown(user['username'])}*\n\n"
    
    # Current usage
    message += f"📈 *Текущее использование*:\n"
    message += f"  • Использовано: {format_bytes(user['usedTrafficBytes'])}\n"
    message += f"  • Лимит: {format_bytes(user['trafficLimitBytes'])}\n"
    
    if user['trafficLimitBytes'] > 0:
        percent = (user['usedTrafficBytes'] / user['trafficLimitBytes']) * 100
        message += f"  • Процент: {percent:.2f}%\n"
    
    message += f"  • За все время: {format_bytes(user['lifetimeUsedTrafficBytes'])}\n\n"
    
    # Usage by node
    if usage:
        message += f"📊 *Использование по серверам (за 30 дней)*:\n"
        
        # Group by node
        node_usage = {}
        for entry in usage:
            node_uuid = entry.get("nodeUuid")
            node_name = entry.get("nodeName", "Неизвестный сервер")
            total = entry.get("total", 0)
            
            if node_uuid not in node_usage:
                node_usage[node_uuid] = {
                    "name": node_name,
                    "total": 0
                }
            
            node_usage[node_uuid]["total"] += total
        
        # Sort by usage
        sorted_nodes = sorted(node_usage.values(), key=lambda x: x["total"], reverse=True)
        
        for i, node in enumerate(sorted_nodes):
            message += f"  • {escape_markdown(node['name'])}: {format_bytes(node['total'])}\n"
    
    # Add action buttons
    keyboard = [
        [InlineKeyboardButton("🔙 Назад к пользователю", callback_data=f"view_{uuid}")],
        [InlineKeyboardButton("🔄 Обновить статистику", callback_data=f"stats_{uuid}")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        text=message,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    
    return SELECTING_USER

async def start_add_hwid(update: Update, context: ContextTypes.DEFAULT_TYPE, uuid):
    """Start adding a HWID device"""
    user = context.user_data.get("current_user") or await UserAPI.get_user_by_uuid(uuid)
    
    context.user_data["add_hwid_uuid"] = uuid
    
    keyboard = [[InlineKeyboardButton("🔙 Отмена", callback_data=f"hwid_{uuid}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        f"📱 *Добавление устройства HWID для пользователя {escape_markdown(user['username'])}*\n\n"
        f"Введите HWID устройства:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    
    context.user_data["waiting_for"] = "hwid"
    return WAITING_FOR_INPUT

async def delete_hwid_device(update: Update, context: ContextTypes.DEFAULT_TYPE, uuid, hwid):
    """Delete a HWID device"""
    user = context.user_data.get("current_user") or await UserAPI.get_user_by_uuid(uuid)
    
    # Confirm deletion
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_del_hwid_{uuid}_{hwid}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"hwid_{uuid}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        f"⚠️ *Удаление устройства HWID*\n\n"
        f"Вы уверены, что хотите удалить устройство с HWID `{hwid}` "
        f"для пользователя {escape_markdown(user['username'])}?",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    
    return SELECTING_USER

async def confirm_delete_hwid_device(update: Update, context: ContextTypes.DEFAULT_TYPE, uuid, hwid):
    """Confirm and delete a HWID device"""
    result = await UserAPI.delete_user_hwid_device(uuid, hwid)
    
    if result:
        message = f"✅ Устройство с HWID `{hwid}` успешно удалено."
    else:
        message = f"❌ Не удалось удалить устройство с HWID `{hwid}`."
    
    keyboard = [[InlineKeyboardButton("🔙 Назад к устройствам", callback_data=f"hwid_{uuid}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.callback_query.edit_message_text(
        message,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    
    return SELECTING_USER

async def handle_hwid_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle HWID input"""
    uuid = context.user_data.get("add_hwid_uuid")
    if not uuid:
        await update.message.reply_text("❌ Ошибка: UUID пользователя не найден.")
        return SELECTING_USER
    
    hwid = update.message.text.strip()
    
    # Добавляем устройство
    result = await UserAPI.add_user_hwid_device(uuid, hwid)
    
    if result:
        keyboard = [[InlineKeyboardButton("🔙 Назад к устройствам", callback_data=f"hwid_{uuid}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"✅ Устройство с HWID `{hwid}` успешно добавлено.",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    else:
        keyboard = [[InlineKeyboardButton("🔙 Назад к устройствам", callback_data=f"hwid_{uuid}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"❌ Не удалось добавить устройство с HWID `{hwid}`.",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    
    return SELECTING_USER

def register_user_handlers(application):
    """Register user handlers"""
    # This function would register all the user-related handlers
    pass
async def confirm_delete_user(update: Update, context: ContextTypes.DEFAULT_TYPE, uuid: str):
    """Show button-based confirmation for user deletion."""
    try:
        user = await UserAPI.get_user_by_uuid(uuid)
        if not user:
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_users")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.callback_query.edit_message_text(
                "❌ Пользователь не найден.",
                reply_markup=reply_markup
            )
            return USER_MENU

        context.user_data["delete_user"] = user
        context.user_data["action"] = "delete"
        context.user_data["uuid"] = uuid

        username = escape_markdown(str(user.get("username") or "Без имени"))
        user_uuid = str(user.get("uuid") or uuid)
        status = str(user.get("status") or "UNKNOWN")
        used_traffic = format_bytes(user.get("usedTrafficBytes") or 0)
        expire_at_raw = user.get("expireAt")
        expire_at = str(expire_at_raw)[:10] if expire_at_raw else "Не указана"

        message_lines = [
            "🚨 *ВНИМАНИЕ! УДАЛЕНИЕ ПОЛЬЗОВАТЕЛЯ* 🚨",
            "",
            "⚠️ Вы собираетесь НАВСЕГДА удалить пользователя:",
            f"👤 *Имя:* `{username}`",
            f"🆔 *UUID:* `{user_uuid}`",
            f"📊 *Статус:* {status}",
            f"📈 *Использовано трафика:* {used_traffic}",
            f"📅 *Дата истечения:* {expire_at}",
            "",
            "💀 *ЭТО ДЕЙСТВИЕ НЕЛЬЗЯ ОТМЕНИТЬ!*",
            "Будут удалены статистика, устройства HWID, история использования и настройки.",
            "",
            "🛡️ Подтвердите удаление кнопкой ниже:"
        ]

        keyboard = [
            [InlineKeyboardButton("🗑️ Да, удалить навсегда", callback_data="final_delete_user")],
            [InlineKeyboardButton("❌ Отмена", callback_data=f"view_{uuid}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await update.callback_query.edit_message_text(
                text="\n".join(message_lines),
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        except Exception as send_error:
            logger.error(f"Error sending deletion confirmation message: {send_error}")
            await update.callback_query.edit_message_text(
                text="\n".join(message_lines),
                reply_markup=reply_markup
            )

        return CONFIRM_ACTION

    except Exception as e:
        logger.error(f"Error in confirm_delete_user: {e}")
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_users")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.callback_query.edit_message_text(
            "❌ Ошибка при подготовке удаления пользователя.",
            reply_markup=reply_markup
        )
        return USER_MENU

async def execute_user_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute the actual user deletion"""
    try:
        user_to_delete = context.user_data.get("delete_user")
        if not user_to_delete:
            await update.callback_query.edit_message_text("❌ Ошибка: данные пользователя для удаления не найдены.")
            return USER_MENU
        
        uuid = user_to_delete.get('uuid')
        username = user_to_delete.get('username', 'Без имени')
        if not uuid:
            await update.callback_query.edit_message_text("❌ Ошибка: UUID пользователя не найден.")
            return USER_MENU
        
        # Show deletion in progress
        await update.callback_query.edit_message_text(
            f"🗑️ Удаление пользователя `{escape_markdown(username)}`...\n\nПожалуйста, подождите...",
            parse_mode="Markdown"
        )
        
        # Perform the deletion
        result = await UserAPI.delete_user(uuid)
        
        # Clear stored deletion data
        context.user_data.pop("delete_user", None)
        context.user_data.pop("action", None)
        context.user_data.pop("uuid", None)
        context.user_data.pop("waiting_for", None)
        
        if result:
            keyboard = [
                [InlineKeyboardButton("📋 Список пользователей", callback_data="list_users")],
                [InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                f"✅ **Пользователь успешно удален!**\n\n"
                f"👤 Имя: `{escape_markdown(username)}`\n"
                f"🆔 UUID: `{uuid}`\n\n"
                f"🗑️ Все данные пользователя были удалены навсегда.",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            
            # Log the deletion for audit purposes
            logger.warning(f"User deleted: {username} (UUID: {uuid}) by admin {update.effective_user.id}")
            
        else:
            keyboard = [
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data=f"user_action_delete_{uuid}")],
                [InlineKeyboardButton("🔙 Назад к списку", callback_data="list_users")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.callback_query.edit_message_text(
                f"❌ **Не удалось удалить пользователя!**\n\n"
                f"👤 Имя: `{escape_markdown(username)}`\n"
                f"🆔 UUID: `{uuid}`\n\n"
                f"Возможные причины:\n"
                f"• Пользователь уже удален\n"
                f"• Ошибка соединения с сервером\n"
                f"• Недостаточно прав доступа\n\n"
                f"Попробуйте еще раз или обратитесь к администратору.",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        
        return USER_MENU
        
    except Exception as e:
        logger.error(f"Error in execute_user_deletion: {e}")
        
        # Clear stored deletion data
        context.user_data.pop("delete_user", None)
        context.user_data.pop("action", None)
        context.user_data.pop("uuid", None)
        context.user_data.pop("waiting_for", None)
        
        keyboard = [
            [InlineKeyboardButton("🔙 Назад к списку", callback_data="list_users")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            f"❌ **Критическая ошибка при удалении пользователя!**\n\n"
            f"Ошибка: `{str(e)}`\n\n"
            f"Обратитесь к администратору системы.",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
        return USER_MENU


async def start_edit_user(update: Update, context: ContextTypes.DEFAULT_TYPE, uuid: str):
    """Start editing a user"""
    # Проверяем авторизацию
    if not check_authorization(update.effective_user):
        await update.callback_query.answer("⛔ Вы не авторизованы для использования этого бота.", show_alert=True)
        return ConversationHandler.END
    
    # Получаем данные пользователя
    user = await UserAPI.get_user_by_uuid(uuid)
    if not user:
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_users")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.callback_query.edit_message_text(
            "❌ Пользователь не найден или ошибка при получении данных.",
            reply_markup=reply_markup
        )
        return USER_MENU
    
    # Сохраняем данные пользователя для редактирования
    context.user_data["edit_user"] = user
    context.user_data["edit_field"] = None
    
    # Создаем меню выбора поля для редактирования
    keyboard = []
    for field_key, field_name in USER_FIELDS.items():
        if field_key in user:  # Показываем только поля, которые есть у пользователя
            keyboard.append([InlineKeyboardButton(f"📝 {field_name}", callback_data=f"edit_field_{field_key}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад к пользователю", callback_data=f"view_{uuid}")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = f"📝 *Редактирование пользователя {escape_markdown(user['username'])}*\n\n"
    message += "Выберите поле для редактирования:"
    
    await update.callback_query.edit_message_text(
        text=message,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    
    return EDIT_USER

@check_admin
async def handle_edit_field_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle edit field selection"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    is_admin = context.user_data.get('is_admin', False)

    if data.startswith("edit_field_"):
        field = data[11:]  # убираем "edit_field_"
        user = context.user_data["edit_user"]
        
        if field not in user:
            await query.edit_message_text("❌ Поле не найдено в данных пользователя.")
            return EDIT_USER
        
        # Сохраняем выбранное поле
        context.user_data["edit_field"] = field
        field_name = USER_FIELDS.get(field, field)

        if field == "activeInternalSquads":
            current_value = user.get(field) or []
            selected = []
            for squad in current_value:
                if isinstance(squad, dict) and squad.get("uuid"):
                    selected.append(squad["uuid"])
                elif isinstance(squad, str):
                    selected.append(squad)
            context.user_data["edit_active_internal_squads"] = selected
            await _show_edit_internal_squads_selector(update, context, user)
            return EDIT_VALUE
        
        # Показываем текущее значение и запрашиваем новое
        current_value = user[field]
        if field == "trafficLimitBytes":
            from modules.utils.formatters import format_bytes
            display_value = "Безлимитный" if current_value == 0 else format_bytes(current_value)
        elif field == "expireAt":
            display_value = current_value[:10] if current_value else "Не указана"
        else:
            display_value = str(current_value) if current_value else "Не указано"
        
        message = f"📝 *Редактирование поля: {field_name}*\n\n"
        message += f"Текущее значение: `{display_value}`\n\n"
        message += f"Введите новое значение для поля {field_name}:"
        
        keyboard = [
            [InlineKeyboardButton("🔙 Назад к выбору поля", callback_data=f"edit_{user['uuid']}")],
            [InlineKeyboardButton("❌ Отмена", callback_data=f"view_{user['uuid']}")]
        ]
        # Add preset inline buttons for specific fields
        preset_keyboard = []
        if field == "expireAt":
            message += "\nВы можете ввести дату в формате `YYYY-MM-DD` для установки точной даты,\n"
            message += "или нажать на кнопку, чтобы добавить дни к текущему сроку:\n"
            preset_keyboard.extend([
                [
                    InlineKeyboardButton("➕ 30 дн.", callback_data="edit_expire_plus_30"),
                    InlineKeyboardButton("➕ 60 дн.", callback_data="edit_expire_plus_60"),
                    InlineKeyboardButton("➕ 90 дн.", callback_data="edit_expire_plus_90"),
                ],
                [
                    InlineKeyboardButton("➕ 180 дн.", callback_data="edit_expire_plus_180"),
                    InlineKeyboardButton("➕ 360 дн.", callback_data="edit_expire_plus_360"),
                ],
            ])
        elif field == "trafficLimitBytes":
            message += "\nВведите лимит в ГБ (целое число). `0` — безлимит.\nИли выберите готовое значение ниже:"
            preset_keyboard.extend([
                [
                    InlineKeyboardButton("0 (безлимит)", callback_data="edit_traffic_gb_0"),
                    InlineKeyboardButton("10 ГБ", callback_data="edit_traffic_gb_10"),
                    InlineKeyboardButton("50 ГБ", callback_data="edit_traffic_gb_50"),
                ],
                [
                    InlineKeyboardButton("100 ГБ", callback_data="edit_traffic_gb_100"),
                    InlineKeyboardButton("300 ГБ", callback_data="edit_traffic_gb_300"),
                    InlineKeyboardButton("500 ГБ", callback_data="edit_traffic_gb_500"),
                ],
            ])
        elif field == "trafficLimitStrategy":
            message += "\nВыберите стратегию сброса: `NO_RESET` (без сброса), `DAY`, `WEEK`, `MONTH`."
            preset_keyboard.extend([
                [
                    InlineKeyboardButton("NO_RESET", callback_data="edit_strategy_NO_RESET"),
                    InlineKeyboardButton("DAY", callback_data="edit_strategy_DAY"),
                ],
                [
                    InlineKeyboardButton("WEEK", callback_data="edit_strategy_WEEK"),
                    InlineKeyboardButton("MONTH", callback_data="edit_strategy_MONTH"),
                ],
            ])
        elif field == "hwidDeviceLimit":
            message += "\nВведите лимит устройств (целое число). `0` — без ограничений.\nИли выберите готовое значение ниже:"
            preset_keyboard.extend([
                [
                    InlineKeyboardButton("0", callback_data="edit_devices_0"),
                    InlineKeyboardButton("1", callback_data="edit_devices_1"),
                    InlineKeyboardButton("2", callback_data="edit_devices_2"),
                ],
                [
                    InlineKeyboardButton("3", callback_data="edit_devices_3"),
                    InlineKeyboardButton("5", callback_data="edit_devices_5"),
                    InlineKeyboardButton("10", callback_data="edit_devices_10"),
                ],
            ])
        elif field == "telegramId":
            message += "\n\nИли откройте Telegram-панель и выберите пользователя:"
            preset_keyboard.append([
                InlineKeyboardButton("👤 Выбрать пользователя", callback_data="edit_request_user_telegram_id"),
            ])

        if preset_keyboard:
            keyboard = preset_keyboard + keyboard
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        
        return EDIT_VALUE

    elif data.startswith("edit_"):
        # Return to the edit menu for this user
        try:
            uuid = data.split("_", 1)[1]
        except Exception:
            return EDIT_USER
        return await start_edit_user(update, context, uuid)

    elif data.startswith("view_"):
        uuid = data.split("_")[1]
        await show_user_details(update, context, uuid)
        return SELECTING_USER
    
    elif data == "back_to_users":
        await show_users_menu(update, context)
        return USER_MENU
    
    return EDIT_USER

@check_admin
async def handle_edit_field_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle edit field value input"""
    # Handle navigation callbacks while in EDIT_VALUE state
    if hasattr(update, "callback_query") and update.callback_query:
        query = update.callback_query
        await query.answer()
        data = query.data
        user = context.user_data.get("edit_user")

        # Preset handlers for inline buttons while editing a value
        if user is not None:
            if data.startswith("edit_squad_toggle_"):
                squad_uuid = data.replace("edit_squad_toggle_", "", 1)
                selected = context.user_data.get("edit_active_internal_squads", [])
                if squad_uuid in selected:
                    selected = [uuid for uuid in selected if uuid != squad_uuid]
                else:
                    selected = [*selected, squad_uuid]
                context.user_data["edit_active_internal_squads"] = selected
                await _show_edit_internal_squads_selector(update, context, user)
                return EDIT_VALUE

            elif data == "edit_squad_done":
                selected = context.user_data.get("edit_active_internal_squads", [])
                update_data = {"activeInternalSquads": selected}
                result = await UserAPI.update_user(user["uuid"], update_data)
                if result:
                    context.user_data["edit_user"]["activeInternalSquads"] = [
                        squad for squad in context.user_data.get("available_internal_squads", [])
                        if squad.get("uuid") in selected
                    ]
                    keyboard = [
                        [InlineKeyboardButton("👤 К пользователю", callback_data=f"view_{user['uuid']}")],
                        [InlineKeyboardButton("✏️ Продолжить редактирование", callback_data=f"edit_{user['uuid']}")],
                        [InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_list")],
                    ]
                    await query.edit_message_text(
                        text=f"✅ Внутренние сквады обновлены: {len(selected)} шт.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                    )
                    context.user_data.pop("edit_active_internal_squads", None)
                    return EDIT_USER
                await query.edit_message_text(
                    text="❌ Не удалось обновить внутренние сквады.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f"edit_{user['uuid']}")]]),
                )
                return EDIT_VALUE

            if data.startswith("edit_expire_plus_"):
                try:
                    days = int(data.split("_")[-1])
                except Exception:
                    return EDIT_VALUE

                # Base on current expireAt if valid, otherwise today
                base_date = None
                try:
                    if user.get("expireAt"):
                        base_date = datetime.fromisoformat(user['expireAt'].replace('Z', '+00:00'))
                except Exception:
                    base_date = None
                if base_date is None:
                    base_date = datetime.now().astimezone()

                new_date = (base_date + timedelta(days=days)).strftime("%Y-%m-%dT00:00:00.000Z")
                update_data = {"expireAt": new_date}

                result = await UserAPI.update_user(user["uuid"], update_data)
                if result:
                    context.user_data["edit_user"]["expireAt"] = new_date
                    keyboard = [
                        [InlineKeyboardButton("👤 К пользователю", callback_data=f"view_{user['uuid']}")],
                        [InlineKeyboardButton("✏️ Продолжить редактирование", callback_data=f"edit_{user['uuid']}")],
                        [InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_list")],
                    ]
                    await query.edit_message_text(
                        text=f"✅ Дата истечения обновлена: {new_date[:10]}",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    return EDIT_USER
                else:
                    await query.edit_message_text(
                        text="❌ Не удалось обновить дату истечения.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f"edit_{user['uuid']}")]])
                    )
                    return EDIT_VALUE

            elif data.startswith("edit_traffic_gb_"):
                try:
                    gb = int(data.split("_")[-1])
                    bytes_value = 0 if gb == 0 else gb * 1024 * 1024 * 1024
                except Exception:
                    return EDIT_VALUE
                update_data = {"trafficLimitBytes": bytes_value}
                result = await UserAPI.update_user(user["uuid"], update_data)
                if result:
                    context.user_data["edit_user"]["trafficLimitBytes"] = bytes_value
                    shown = "Безлимитный" if bytes_value == 0 else f"{gb} ГБ"
                    keyboard = [
                        [InlineKeyboardButton("👤 К пользователю", callback_data=f"view_{user['uuid']}")],
                        [InlineKeyboardButton("✏️ Продолжить редактирование", callback_data=f"edit_{user['uuid']}")],
                        [InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_list")],
                    ]
                    await query.edit_message_text(
                        text=f"✅ Лимит трафика обновлён: {shown}",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    return EDIT_USER
                else:
                    await query.edit_message_text(
                        text="❌ Не удалось обновить лимит трафика.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f"edit_{user['uuid']}")]])
                    )
                    return EDIT_VALUE

            elif data.startswith("edit_strategy_"):
                strategy = data.split("_", 2)[2]
                if strategy not in ("NO_RESET", "DAY", "WEEK", "MONTH"):
                    return EDIT_VALUE
                update_data = {"trafficLimitStrategy": strategy}
                result = await UserAPI.update_user(user["uuid"], update_data)
                if result:
                    context.user_data["edit_user"]["trafficLimitStrategy"] = strategy
                    keyboard = [
                        [InlineKeyboardButton("👤 К пользователю", callback_data=f"view_{user['uuid']}")],
                        [InlineKeyboardButton("✏️ Продолжить редактирование", callback_data=f"edit_{user['uuid']}")],
                        [InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_list")],
                    ]
                    await query.edit_message_text(
                        text=f"✅ Стратегия сброса трафика обновлена: {strategy}",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    return EDIT_USER
                else:
                    await query.edit_message_text(
                        text="❌ Не удалось обновить стратегию сброса трафика.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f"edit_{user['uuid']}")]])
                    )
                    return EDIT_VALUE

            elif data.startswith("edit_devices_"):
                try:
                    devices = int(data.split("_")[-1])
                except Exception:
                    return EDIT_VALUE
                if devices < 0:
                    return EDIT_VALUE
                update_data = {"hwidDeviceLimit": devices}
                if devices > 0:
                    update_data["trafficLimitStrategy"] = "NO_RESET"
                result = await UserAPI.update_user(user["uuid"], update_data)
                if result:
                    context.user_data["edit_user"].update(update_data)
                    shown = "Без ограничений" if devices == 0 else str(devices)
                    keyboard = [
                        [InlineKeyboardButton("👤 К пользователю", callback_data=f"view_{user['uuid']}")],
                        [InlineKeyboardButton("✏️ Продолжить редактирование", callback_data=f"edit_{user['uuid']}")],
                        [InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_list")],
                    ]
                    await query.edit_message_text(
                        text=f"✅ Лимит устройств обновлён: {shown}",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                    return EDIT_USER
                else:
                    await query.edit_message_text(
                        text="❌ Не удалось обновить лимит устройств.",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=f"edit_{user['uuid']}")]])
                    )
                    return EDIT_VALUE

            elif data == "edit_request_user_telegram_id":
                if context.user_data.get("edit_field") == "telegramId":
                    await _send_user_request_keyboard(
                        update,
                        "Нажмите кнопку ниже, чтобы выбрать пользователя для поля Telegram ID.",
                    )
                return EDIT_VALUE

        if data.startswith("edit_"):
            try:
                uuid = data.split("_", 1)[1]
            except Exception:
                return EDIT_USER
            return await start_edit_user(update, context, uuid)
        elif data.startswith("view_"):
            uuid = data.split("_", 1)[1]
            context.user_data.pop("edit_active_internal_squads", None)
            await show_user_details(update, context, uuid)
            return SELECTING_USER
        elif data == "back_to_users":
            context.user_data.pop("edit_active_internal_squads", None)
            await show_users_menu(update, context)
            return USER_MENU
        return EDIT_VALUE

    field = context.user_data.get("edit_field")
    user = context.user_data.get("edit_user")
    
    if not field or not user:
        await update.message.reply_text("❌ Ошибка: данные для редактирования не найдены.")
        return USER_MENU

    if update.message.user_shared:
        if field != "telegramId":
            await update.message.reply_text(
                "❌ Выбор пользователя доступен только для поля Telegram ID.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return EDIT_VALUE
        value = int(update.message.user_shared.user_id)
    else:
        value = update.message.text.strip()
    
    # Process the value based on the field
    if field == "expireAt":
        try:
            # Validate date format
            date_obj = datetime.strptime(value, "%Y-%m-%d")
            value = date_obj.strftime("%Y-%m-%dT00:00:00.000Z")
        except ValueError:
            keyboard = [
                [InlineKeyboardButton("🔙 Назад", callback_data=f"edit_{user['uuid']}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ Неверный формат даты. Используйте YYYY-MM-DD.",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return EDIT_USER
    
    elif field == "trafficLimitBytes":
        try:
            gb = int(value)
            if gb < 0:
                raise ValueError("Traffic limit cannot be negative")
            # Convert GB to bytes (0 stays unlimited)
            value = 0 if gb == 0 else gb * 1024 * 1024 * 1024
        except ValueError:
            keyboard = [
                [InlineKeyboardButton("🔙 Назад", callback_data=f"edit_{user['uuid']}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ Неверный формат. Введите целое число ГБ (0 — безлимит).",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return EDIT_USER
    
    elif field == "telegramId":
        try:
            value = int(value)
        except ValueError:
            keyboard = [
                [InlineKeyboardButton("🔙 Назад", callback_data=f"edit_{user['uuid']}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ Неверный формат Telegram ID. Введите целое число.",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return EDIT_USER
            
    elif field == "hwidDeviceLimit":
        try:
            value = int(value)
            if value < 0:
                raise ValueError("Device limit cannot be negative")
        except ValueError:
            keyboard = [
                [InlineKeyboardButton("🔙 Назад", callback_data=f"edit_{user['uuid']}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "❌ Неверный формат числа. Введите целое число >= 0.",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            return EDIT_USER
    
    # Update the user with the new value
    update_data = {field: value}
    
    # Если устанавливается лимит устройств > 0, добавляем в обновляемые данные trafficLimitStrategy=NO_RESET
    if field == "hwidDeviceLimit" and value > 0:
        update_data["trafficLimitStrategy"] = "NO_RESET"
        logger.info(f"Auto-setting trafficLimitStrategy=NO_RESET when setting hwidDeviceLimit to {value} for user {user['uuid']}")
    result = await UserAPI.update_user(user["uuid"], update_data)
    
    if result:
        context.user_data["edit_user"][field] = value
        keyboard = [
            [InlineKeyboardButton("👁️ Просмотр пользователя", callback_data=f"view_{user['uuid']}")],
            [InlineKeyboardButton("📝 Продолжить редактирование", callback_data=f"edit_{user['uuid']}")],
            [InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_list")]
        ]
        inline_reply_markup = InlineKeyboardMarkup(keyboard)

        if update.message.user_shared:
            await update.message.reply_text(
                f"✅ Поле {field} успешно обновлено.",
                reply_markup=ReplyKeyboardRemove(),
            )
            await update.message.reply_text(
                "Что делаем дальше?",
                reply_markup=inline_reply_markup,
            )
        else:
            await update.message.reply_text(
            f"✅ Поле {field} успешно обновлено.",
                reply_markup=inline_reply_markup,
                parse_mode="Markdown"
            )
    else:
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data=f"edit_{user['uuid']}")]
        ]
        inline_reply_markup = InlineKeyboardMarkup(keyboard)

        if update.message.user_shared:
            await update.message.reply_text(
                "❌ Не удалось обновить поле Telegram ID.",
                reply_markup=ReplyKeyboardRemove(),
            )
            await update.message.reply_text(
                "Можно вернуться назад и попробовать снова.",
                reply_markup=inline_reply_markup,
            )
        else:
            await update.message.reply_text(
                f"❌ Не удалось обновить поле {field}.",
                reply_markup=inline_reply_markup,
                parse_mode="Markdown"
            )
    
    return EDIT_USER

@check_admin
async def handle_cancel_user_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle cancel user creation"""
    query = update.callback_query
    await query.answer("Создание пользователя отменено")
    if query.message:
        await query.message.reply_text("Создание пользователя отменено.", reply_markup=ReplyKeyboardRemove())
    
    # Очищаем контекст создания пользователя
    keys_to_remove = [
        'create_user', 'create_user_fields', 'current_field_index', 
        'using_template', 'template_name', 'selected_template',
        'search_type', 'waiting_for', 'create_user_description_prefix',
        'available_internal_squads'
    ]
    
    for key in keys_to_remove:
        context.user_data.pop(key, None)
    
    # Возвращаемся в меню пользователей
    await show_users_menu(update, context)
    return USER_MENU
