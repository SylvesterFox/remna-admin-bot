from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from modules.handlers.self_service import get_linked_user
from modules.services.user_notifications import (
    get_enabled_notification_user_ids,
    get_last_notification_marker,
    set_last_notification_marker,
)

logger = logging.getLogger(__name__)


def _build_marker(days_left: int | None, expire_at: str | None) -> str | None:
    if days_left is None and not expire_at:
        return None
    return f"{expire_at or 'none'}:{days_left if days_left is not None else 'unknown'}"


def _get_days_left(expire_at: str | None) -> tuple[int | None, str]:
    if not expire_at:
        return None, "Не указана"
    try:
        expire_dt = datetime.fromisoformat(str(expire_at).replace("Z", "+00:00"))
        days_left = (expire_dt - datetime.now().astimezone(expire_dt.tzinfo)).days
        return days_left, str(expire_at)[:10]
    except Exception:
        return None, str(expire_at)[:10]


async def send_expiry_notifications_once(application) -> None:
    """Send expiry reminders to linked users who enabled notifications."""
    for telegram_id in get_enabled_notification_user_ids():
        try:
            user = await get_linked_user(telegram_id)
            if not user:
                continue

            days_left, expire_text = _get_days_left(user.get("expireAt"))
            if days_left not in {7, 3, 1, 0}:
                continue

            marker = _build_marker(days_left, expire_text)
            if marker and marker == get_last_notification_marker(telegram_id):
                continue

            if days_left == 0:
                text = f"⏰ Ваша подписка истекает сегодня.\nДата окончания: {expire_text}"
            else:
                text = f"⏰ До окончания вашей подписки осталось {days_left} дн.\nДата окончания: {expire_text}"

            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("📄 Открыть кабинет", callback_data="self_overview")]]
            )

            await application.bot.send_message(
                chat_id=telegram_id,
                text=text,
                reply_markup=keyboard,
            )
            if marker:
                set_last_notification_marker(telegram_id, marker)
        except Exception as exc:
            logger.error("Failed to send expiry notification to %s: %s", telegram_id, exc)


async def expiry_notifier_loop(application, interval_seconds: int = 3600) -> None:
    while True:
        await send_expiry_notifications_once(application)
        await asyncio.sleep(interval_seconds)
