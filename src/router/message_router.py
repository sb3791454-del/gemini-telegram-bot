"""Main update and message dispatcher."""

import logging
from typing import Optional
from config.settings import Settings
from telegram.client import TelegramClient
from telegram.auth import is_user_authorized
from ai.gemini_client import GeminiClient
from ai.prompts_builder import select_relevant_memories, format_prompt_with_memories
from router.command_router import handle_command
from config.prompts import UNAUTHORIZED_DENIAL_TEXT, IMAGE_ERROR_TEXT, FALLBACK_ERROR_TEXT
from storage.repositories import UserRepository, MemoryRepository

logger = logging.getLogger("worker.router")

async def dispatch_telegram_update(
    update: dict,
    settings: Settings,
    telegram_client: TelegramClient,
    gemini_client: GeminiClient,
    user_repo: Optional[UserRepository] = None,
    memory_repo: Optional[MemoryRepository] = None
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

    # 1. Authorization Gatekeeper (Fail-Closed: evaluated before DB writes and AI calls)
    if not is_user_authorized(user_id, settings):
        await telegram_client.send_message(chat_id, UNAUTHORIZED_DENIAL_TEXT, parse_mode="Markdown")
        return

    # 2. Update Authorized User Profile in D1 (Graceful/Non-blocking)
    if user_repo and user_id:
        try:
            display_name = from_user.get("first_name", "")
            username = from_user.get("username", "")
            await user_repo.upsert_user_profile(user_id, display_name=display_name, username=username)
        except Exception as e:
            logger.error(f"Error persisting user profile: {e}")

    text = message.get("text", "").strip()
    photo = message.get("photo")
    caption = message.get("caption", "").strip()

    # 3. Check for Commands (Evaluated before any Gemini calls)
    if text.startswith("/"):
        handled = await handle_command(
            text,
            chat_id,
            telegram_client,
            user_id=user_id,
            user_repo=user_repo,
            memory_repo=memory_repo
        )
        if handled:
            return

    # 4. Handle Photos / Multimodal Vision
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

    # 5. Handle Ordinary Text Messages with Context-Aware Long-Term Memory Injection
    if text:
        await telegram_client.send_chat_action(chat_id, "typing")
        try:
            # Step 5a: Retrieve user's stored memories from D1 (non-blocking / resilient)
            relevant_memories = []
            if memory_repo and user_id and memory_repo.db.is_available:
                try:
                    all_user_memories = await memory_repo.get_all_memories(user_id)
                    relevant_memories = select_relevant_memories(text, all_user_memories, max_memories=5)
                except Exception as e:
                    logger.error(f"Error selecting relevant memories: {e}")

            # Step 5b: Construct prompt with relevant long-term memory context (if any match)
            final_prompt = format_prompt_with_memories(text, relevant_memories)

            reply = await gemini_client.generate_text(final_prompt, model_name=settings.gemini_model)
            await telegram_client.send_message(chat_id, reply, parse_mode="")
        except Exception as e:
            logger.error(f"Error processing text message: {e}")
            await telegram_client.send_message(chat_id, FALLBACK_ERROR_TEXT, parse_mode="")
        return
