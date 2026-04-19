"""
Helper functions for user-friendly selection of entities (users, inbounds, nodes)
instead of working with UUIDs directly
"""
import logging
from typing import List, Dict, Optional, Tuple
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from modules.api.users import UserAPI
from modules.api.inbounds import InboundAPI
from modules.api.nodes import NodeAPI
from modules.utils.formatters import escape_markdown

logger = logging.getLogger(__name__)

class SelectionHelper:
    """Helper class for entity selection with user-friendly interface"""
    
    @staticmethod
    async def get_users_selection_keyboard(
        page: int = 0, 
        per_page: int = 8,
        callback_prefix: str = "select_user",
        include_back: bool = True,
        max_per_row: int = 1
    ) -> Tuple[InlineKeyboardMarkup, Dict]:
        """
        Create keyboard for user selection with pagination
        Returns: (keyboard, users_data)
        """
        try:
            response = await UserAPI.get_all_users()
            if not response or not response.get("users"):
                keyboard = []
                if include_back:
                    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
                return InlineKeyboardMarkup(keyboard), {}
            
            users = response["users"]
            total_users = len(users)
            total_pages = (total_users + per_page - 1) // per_page
            
            start_idx = page * per_page
            end_idx = min(start_idx + per_page, total_users)
            
            keyboard = []
            users_data = {}
            
            # Add user buttons
            for i in range(start_idx, end_idx):
                user = users[i]
                status_emoji = "✅" if user["status"] == "ACTIVE" else "❌"
                display_name = f"{status_emoji} {user['username']}"
                
                callback_data = f"{callback_prefix}_{user['uuid']}"
                users_data[user['uuid']] = user
                
                keyboard.append([InlineKeyboardButton(display_name, callback_data=callback_data)])
            
            # Add pagination if needed
            if total_pages > 1:
                pagination_row = []
                if page > 0:
                    pagination_row.append(InlineKeyboardButton("⬅️", callback_data=f"users_page_{page-1}"))
                
                pagination_row.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="page_info"))
                
                if page < total_pages - 1:
                    pagination_row.append(InlineKeyboardButton("➡️", callback_data=f"users_page_{page+1}"))
                
                keyboard.append(pagination_row)
            
            if include_back:
                keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
            
            return InlineKeyboardMarkup(keyboard), users_data
            
        except Exception as e:
            logger.error(f"Error creating users selection keyboard: {e}")
            keyboard = []
            if include_back:
                keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
            return InlineKeyboardMarkup(keyboard), {}
    
    @staticmethod
    async def get_inbounds_selection_keyboard(
        callback_prefix: str = "select_inbound",
        include_back: bool = True,
        max_per_row: int = 1
    ) -> Tuple[InlineKeyboardMarkup, Dict]:
        """
        Create keyboard for inbound selection
        Returns: (keyboard, inbounds_data)
        """
        try:
            inbounds = await InboundAPI.get_inbounds()
            if not inbounds:
                keyboard = []
                if include_back:
                    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
                return InlineKeyboardMarkup(keyboard), {}
            
            keyboard = []
            inbounds_data = {}
            
            for inbound in inbounds:
                display_name = f"🔌 {inbound['tag']} ({inbound['type']}, :{inbound['port']})"
                callback_data = f"{callback_prefix}_{inbound['uuid']}"
                inbounds_data[inbound['uuid']] = inbound
                
                keyboard.append([InlineKeyboardButton(display_name, callback_data=callback_data)])
            
            if include_back:
                keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
            
            return InlineKeyboardMarkup(keyboard), inbounds_data
            
        except Exception as e:
            logger.error(f"Error creating inbounds selection keyboard: {e}")
            keyboard = []
            if include_back:
                keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
            return InlineKeyboardMarkup(keyboard), {}
    
    @staticmethod
    async def get_nodes_selection_keyboard(
        callback_prefix: str = "select_node",
        include_back: bool = True
    ) -> Tuple[InlineKeyboardMarkup, Dict]:
        """
        Create keyboard for node selection
        Returns: (keyboard, nodes_data)
        """
        try:
            response = await NodeAPI.get_all_nodes()
            if not response:
                keyboard = []
                if include_back:
                    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
                return InlineKeyboardMarkup(keyboard), {}
            
            nodes = response if isinstance(response, list) else response.get("nodes", [])
            keyboard = []
            nodes_data = {}
            
            for node in nodes:
                status_emoji = "🟢" if not node.get("isDisabled", False) and node.get("isConnected", False) else "🔴"
                display_name = f"{status_emoji} {node['name']} ({node.get('countryCode', 'XX')})"
                
                callback_data = f"{callback_prefix}_{node['uuid']}"
                nodes_data[node['uuid']] = node
                
                keyboard.append([InlineKeyboardButton(display_name, callback_data=callback_data)])
            
            if include_back:
                keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
            
            return InlineKeyboardMarkup(keyboard), nodes_data
            
        except Exception as e:
            logger.error(f"Error creating nodes selection keyboard: {e}")
            keyboard = []
            if include_back:
                keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
            return InlineKeyboardMarkup(keyboard), {}
    
    @staticmethod
    async def search_users_by_query(query: str, search_type: str = "username") -> List[Dict]:
        """
        Search users by different criteria
        search_type: username, telegram_id, email, tag
        """
        try:
            if search_type == "username":
                response = await UserAPI.get_user_by_username(query)
                return [response] if response else []
            elif search_type == "telegram_id":
                response = await UserAPI.get_user_by_telegram_id(query)
                return response if isinstance(response, list) else [response] if response else []
            elif search_type == "email":
                response = await UserAPI.get_user_by_email(query)
                return response if isinstance(response, list) else [response] if response else []
            elif search_type == "tag":
                response = await UserAPI.get_user_by_tag(query)
                return response if isinstance(response, list) else [response] if response else []
            else:
                return []
        except Exception as e:
            logger.error(f"Error searching users: {e}")
            return []
    
    @staticmethod
    def create_user_info_keyboard(user_uuid: str, action_prefix: str = "user_action", is_admin: bool = False) -> InlineKeyboardMarkup:
        """Create keyboard with user actions"""
        rows = []

        if is_admin:
            rows.extend([
                [
                    InlineKeyboardButton("✏️ Редактировать", callback_data=f"{action_prefix}_edit_{user_uuid}"),
                    InlineKeyboardButton("🔄 Обновить данные", callback_data=f"{action_prefix}_refresh_{user_uuid}")
                ],
                [
                    InlineKeyboardButton("🚫 Отключить", callback_data=f"{action_prefix}_disable_{user_uuid}"),
                    InlineKeyboardButton("✅ Включить", callback_data=f"{action_prefix}_enable_{user_uuid}")
                ],
                [
                    InlineKeyboardButton("📊 Сбросить трафик", callback_data=f"{action_prefix}_reset_traffic_{user_uuid}"),
                    InlineKeyboardButton("🔐 Отозвать подписку", callback_data=f"{action_prefix}_revoke_{user_uuid}")
                ],
                [
                    InlineKeyboardButton("🗑️ Удалить", callback_data=f"{action_prefix}_delete_{user_uuid}")
                ]
            ])
        else:
            rows.append([InlineKeyboardButton("🔄 Обновить данные", callback_data=f"{action_prefix}_refresh_{user_uuid}")])

        rows.append([InlineKeyboardButton("🔗 URL и QR подписки", callback_data=f"{action_prefix}_subscription_{user_uuid}")])
        rows.append([InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_users")])
        return InlineKeyboardMarkup(rows)

    @staticmethod
    def create_inbound_info_keyboard(inbound_uuid: str, action_prefix: str = "inbound_action") -> InlineKeyboardMarkup:
        """Create keyboard with inbound actions"""
        keyboard = [
            [
                InlineKeyboardButton("👥 Добавить всем пользователям", callback_data=f"{action_prefix}_add_users_{inbound_uuid}"),
                InlineKeyboardButton("👥 Убрать у всех пользователей", callback_data=f"{action_prefix}_remove_users_{inbound_uuid}")
            ],
            [
                InlineKeyboardButton("🖥️ Добавить на все ноды", callback_data=f"{action_prefix}_add_nodes_{inbound_uuid}"),
                InlineKeyboardButton("🖥️ Убрать со всех нод", callback_data=f"{action_prefix}_remove_nodes_{inbound_uuid}")
            ],
            [
                InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_inbounds")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    @staticmethod
    def create_node_info_keyboard(node_uuid: str, action_prefix: str = "node_action") -> InlineKeyboardMarkup:
        """Create keyboard with node actions"""
        keyboard = [
            [
                InlineKeyboardButton("✅ Включить", callback_data=f"{action_prefix}_enable_{node_uuid}"),
                InlineKeyboardButton("🚫 Отключить", callback_data=f"{action_prefix}_disable_{node_uuid}")
            ],
            [
                InlineKeyboardButton("🔄 Перезапустить", callback_data=f"{action_prefix}_restart_{node_uuid}"),
                InlineKeyboardButton("✏️ Редактировать", callback_data=f"{action_prefix}_edit_{node_uuid}")
            ],
            [
                InlineKeyboardButton("📊 Статистика", callback_data=f"{action_prefix}_stats_{node_uuid}"),
                InlineKeyboardButton("🗑️ Удалить", callback_data=f"{action_prefix}_delete_{node_uuid}")
            ],
            [
                InlineKeyboardButton("🔙 Назад к списку", callback_data="back_to_nodes")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)    @staticmethod
    async def get_user_by_identifier(identifier: str) -> Optional[Dict]:
        """
        Smart user lookup - try to find user by username, UUID, or telegram ID
        """
        try:
            # Try by username first
            try:
                user = await UserAPI.get_user_by_username(identifier)
                if user:
                    return user
            except Exception:
                pass
            
            # Try by UUID if it looks like UUID
            if len(identifier) == 36 and identifier.count('-') == 4:
                try:
                    user = await UserAPI.get_user_by_uuid(identifier)
                    if user:
                        return user
                except Exception:
                    pass
            
            # Try by telegram ID if it's numeric
            if identifier.isdigit():
                try:
                    users = await UserAPI.get_user_by_telegram_id(identifier)
                    if users and len(users) > 0:
                        return users[0]
                except Exception:
                    pass
            
            return None
        except Exception as e:
            logger.error(f"Error in smart user lookup: {e}")
            return None

    @staticmethod
    async def get_inbound_by_identifier(identifier: str) -> Optional[Dict]:
        """
        Smart inbound lookup - try to find inbound by tag or UUID
        """
        try:
            inbounds = await InboundAPI.get_inbounds()
            if not inbounds:
                return None
            
            # Try by tag first
            for inbound in inbounds:
                if inbound.get('tag', '').lower() == identifier.lower():
                    return inbound
            
            # Try by UUID
            for inbound in inbounds:
                if inbound.get('uuid') == identifier:
                    return inbound
            
            return None
        except Exception as e:
            logger.error(f"Error in smart inbound lookup: {e}")
            return None

    @staticmethod
    async def get_node_by_identifier(identifier: str) -> Optional[Dict]:
        """
        Smart node lookup - try to find node by name or UUID
        """
        try:
            response = await NodeAPI.get_all_nodes()
            if not response:
                return None
            
            nodes = response if isinstance(response, list) else response.get("nodes", [])
            
            # Try by name first
            for node in nodes:
                if node.get('name', '').lower() == identifier.lower():
                    return node
            
            # Try by UUID
            for node in nodes:
                if node.get('uuid') == identifier:
                    return node
            
            return None
        except Exception as e:
            logger.error(f"Error in smart node lookup: {e}")
            return None
