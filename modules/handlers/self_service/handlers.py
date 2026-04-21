from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
import logging

import qrcode
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.ext import ContextTypes

from modules.api.users import UserAPI
from modules.config import SELF_SERVICE_MENU
from modules.services.user_notifications import notifications_enabled, set_notifications_enabled
from modules.utils.formatters import escape_markdown, format_bytes

logger = logging.getLogger(__name__)


def _build_subscription_qr_image(subscription_url: str) -> BytesIO:
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(subscription_url)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


async def get_linked_user(telegram_id: int):
    """Return user linked to telegram_id, normalized to dict or None."""
    try:
        result = await UserAPI.get_user_by_telegram_id(telegram_id)
    except Exception as exc:
        logger.error("Failed to fetch user by telegram id %s: %s", telegram_id, exc)
        return None

    if isinstance(result, list):
        return result[0] if result else None
    if isinstance(result, dict):
        return result
    return None


def _self_service_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    notify_label = "🔔 Уведомления: Вкл" if notifications_enabled(telegram_id) else "🔕 Уведомления: Выкл"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📄 Моя подписка", callback_data="self_overview")],
            [InlineKeyboardButton("🔗 URL и QR", callback_data="self_subscription")],
            [InlineKeyboardButton("📊 Трафик и срок", callback_data="self_usage")],
            [InlineKeyboardButton(notify_label, callback_data="self_toggle_notifications")],
        ]
    )


def _format_expiry(user: dict) -> tuple[str, int | None]:
    expire_at = user.get("expireAt")
    if not expire_at:
        return "Не указана", None
    try:
        expire_dt = datetime.fromisoformat(str(expire_at).replace("Z", "+00:00"))
        days_left = (expire_dt - datetime.now().astimezone(expire_dt.tzinfo)).days
        return f"{str(expire_at)[:10]} ({days_left} дн.)", days_left
    except Exception:
        return str(expire_at)[:10], None


async def show_self_service_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    linked_user = await get_linked_user(user.id)
    if not linked_user:
        text = "⛔ Подписка, привязанная к вашему Telegram ID, не найдена."
        if update.callback_query:
            await update.callback_query.answer(text, show_alert=True)
        else:
            await update.message.reply_text(text)
        return SELF_SERVICE_MENU

    context.user_data["self_service_user"] = linked_user
    expiry_text, _ = _format_expiry(linked_user)
    username = escape_markdown(str(linked_user.get("username", "unknown")))
    text = (
        f"👤 *Личный кабинет*\n\n"
        f"Имя: `{username}`\n"
        f"Статус: {linked_user.get('status', 'UNKNOWN')}\n"
        f"Истекает: {expiry_text}\n\n"
        f"Выберите действие:"
    )
    reply_markup = _self_service_keyboard(user.id)

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode="Markdown")

    return SELF_SERVICE_MENU


async def _send_self_subscription_qr(update: Update, context: ContextTypes.DEFAULT_TYPE, user: dict):
    subscription_url = user.get("subscriptionUrl")
    if not subscription_url:
        await update.callback_query.answer("URL подписки не найден", show_alert=True)
        return

    caption = f"Подписка для {user.get('username', 'unknown')}\n{subscription_url}"
    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=InputFile(_build_subscription_qr_image(subscription_url), filename="subscription.png"),
        caption=caption,
        reply_to_message_id=update.callback_query.message.message_id if update.callback_query else None,
    )


async def handle_self_service_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    linked_user = await get_linked_user(update.effective_user.id)
    if not linked_user:
        await query.edit_message_text("⛔ Подписка, привязанная к вашему Telegram ID, не найдена.")
        return SELF_SERVICE_MENU

    context.user_data["self_service_user"] = linked_user
    data = query.data

    if data == "self_overview":
        expiry_text, _ = _format_expiry(linked_user)
        username = escape_markdown(str(linked_user.get("username", "unknown")))
        text = (
            f"📄 *Информация о подписке*\n\n"
            f"Имя: `{username}`\n"
            f"Статус: {linked_user.get('status', 'UNKNOWN')}\n"
            f"Использовано: {format_bytes(linked_user.get('usedTrafficBytes') or 0)}\n"
            f"Лимит: {format_bytes(linked_user.get('trafficLimitBytes') or 0)}\n"
            f"Истекает: {expiry_text}\n"
        )
        await query.edit_message_text(
            text=text,
            reply_markup=_self_service_keyboard(update.effective_user.id),
            parse_mode="Markdown",
        )
        return SELF_SERVICE_MENU

    if data == "self_subscription":
        await _send_self_subscription_qr(update, context, linked_user)
        subscription_url = escape_markdown(str(linked_user.get("subscriptionUrl", "Не указан")))
        text = (
            f"🔗 *URL подписки*\n\n"
            f"`{subscription_url}`\n\n"
            f"QR-код отправлен отдельным сообщением."
        )
        await query.edit_message_text(
            text=text,
            reply_markup=_self_service_keyboard(update.effective_user.id),
            parse_mode="Markdown",
        )
        return SELF_SERVICE_MENU

    if data == "self_usage":
        end_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        usage = await UserAPI.get_user_usage_by_range(linked_user["uuid"], start_date, end_date)
        usage_total = 0
        if isinstance(usage, list):
            for entry in usage:
                try:
                    usage_total += int(entry.get("total", 0))
                except Exception:
                    continue

        expiry_text, _ = _format_expiry(linked_user)
        text = (
            f"📊 *Статистика подписки*\n\n"
            f"Текущий расход: {format_bytes(linked_user.get('usedTrafficBytes') or 0)}\n"
            f"Лимит: {format_bytes(linked_user.get('trafficLimitBytes') or 0)}\n"
            f"За 30 дней: {format_bytes(usage_total)}\n"
            f"За всё время: {format_bytes(linked_user.get('lifetimeUsedTrafficBytes') or 0)}\n"
            f"Истекает: {expiry_text}\n"
        )
        await query.edit_message_text(
            text=text,
            reply_markup=_self_service_keyboard(update.effective_user.id),
            parse_mode="Markdown",
        )
        return SELF_SERVICE_MENU

    if data == "self_toggle_notifications":
        current = notifications_enabled(update.effective_user.id)
        set_notifications_enabled(update.effective_user.id, not current)
        state_text = "включены" if not current else "выключены"
        await query.edit_message_text(
            text=f"🔔 Уведомления об окончании подписки {state_text}.",
            reply_markup=_self_service_keyboard(update.effective_user.id),
        )
        return SELF_SERVICE_MENU

    return await show_self_service_menu(update, context)
