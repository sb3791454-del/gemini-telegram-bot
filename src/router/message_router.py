"""Main update and message dispatcher."""

import logging
from config.settings import Settings
from telegram.client import TelegramClient
from telegram.auth import is_user_authorized
from ai.gemini_client import GeminiClient
from router.command_router import handle_command
from config.prompts import UNAUTHORIZED_DENIAL_TEXT, IMAGE_ERROR_TEXT, FALLBACK_ERROR_TEXT

logger = logging.getLogger("worker.router")

async def dispatch_telegram_update(
    update: dict,
    settings: Settings,
    telegram_client: TelegramClient,
    gemini_client: GeminiClient
):
    """Processes an incoming Telegram update dictionary."""
    message = update.get("message")
    if not message:
        return

    chat_id = message.get("chat", {}).get("id")
    if not chat_id:
        return

    from_user = message.get("from", {})
    user_id = from_user.get("id")

    # 1. Authorization Gatekeeper (Fail-Closed)
    if not is_user_authorized(user_id, settings):
        await telegram_client.send_message(chat_id, UNAUTHORIZED_DENIAL_TEXT, parse_mode="Markdown")
        return

    text = message.get("text", "").strip()
    photo = message.get("photo")
    caption = message.get("caption", "").strip()

    # 2. Check for Commands (Evaluated before any Gemini calls)
    if text.startswith("/"):
        handled = await handle_command(text, chat_id, telegram_client, user_id=user_id)
        if handled:
            return

    # 3. Handle Photos / Multimodal Vision
    if photo:
        await telegram_client.send_chat_action(chat_id, "typing")
        try:
            highest_res_photo = photo[-1]
            file_id = highest_res_photo.get("file_id")
            image_bytes = await telegram_client.get_file_bytes(file_id)
            reply = await gemini_client.generate_vision(image_bytes, caption=caption, model_name=settings.gemini_model)
            await telegram_client.send_message(chat_id, reply, parse_mode="")
        except Exception as e:
            logger.error(f"Error processing photo message: {e}")
            await telegram_client.send_message(chat_id, IMAGE_ERROR_TEXT, parse_mode="")
        return

    # 4. Handle Ordinary Text Messages
    if text:
        await telegram_client.send_chat_action(chat_id, "typing")
        try:
            reply = await gemini_client.generate_text(text, model_name=settings.gemini_model)
            await telegram_client.send_message(chat_id, reply, parse_mode="")
        except Exception as e:
            logger.error(f"Error processing text message: {e}")
            await telegram_client.send_message(chat_id, FALLBACK_ERROR_TEXT, parse_mode="")
        return
