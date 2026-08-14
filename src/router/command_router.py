"""Command router for Telegram bot slash commands."""

from typing import Optional
from telegram.client import TelegramClient
from config.prompts import WELCOME_TEXT, HELP_TEXT, RESET_TEXT
from storage.repositories import UserRepository, MemoryRepository

async def handle_command(
    command: str,
    chat_id: int,
    telegram_client: TelegramClient,
    user_id: Optional[int] = None,
    user_repo: Optional[UserRepository] = None,
    memory_repo: Optional[MemoryRepository] = None
) -> bool:
    """
    Evaluates slash commands. Returns True if command was handled, False otherwise.
    """
    clean_cmd = command.strip().split()[0].lower()
    
    if clean_cmd.startswith("/start"):
        await telegram_client.send_message(chat_id, WELCOME_TEXT, parse_mode="Markdown")
        return True
        
    if clean_cmd.startswith("/help"):
        await telegram_client.send_message(chat_id, HELP_TEXT, parse_mode="Markdown")
        return True
        
    if clean_cmd.startswith("/clear") or clean_cmd.startswith("/reset"):
        await telegram_client.send_message(chat_id, RESET_TEXT, parse_mode="Markdown")
        return True

    if clean_cmd.startswith("/id"):
        id_text = f"🆔 Your Telegram User ID: {user_id}" if user_id is not None else "⚠️ Could not determine Telegram User ID."
        await telegram_client.send_message(chat_id, id_text, parse_mode="")
        return True

    if clean_cmd.startswith("/memory"):
        if user_repo and user_repo.db.is_available:
            try:
                profile = await user_repo.get_user_profile(user_id) if user_id else None
                mem_count = await memory_repo.count_memories(user_id) if (memory_repo and user_id) else 0
                has_profile = profile is not None
                
                resp_text = (
                    "🧠 *Memory & State Status:*\n"
                    "• Database: Connected (D1 Active)\n"
                    f"• User Profile: {'Available' if has_profile else 'Not Created Yet'}\n"
                    f"• Long-term Memories: {mem_count}\n"
                )
                if profile and profile.get("last_seen_at"):
                    resp_text += f"• Last Active: {profile['last_seen_at'][:19].replace('T', ' ')} UTC\n"
            except Exception as e:
                resp_text = "🧠 *Memory Status:* Active (D1 Error occurred)"
        else:
            resp_text = (
                "🧠 *Memory & State Status:*\n"
                "• Database: Offline (D1 binding not attached)\n"
                "• User Profile: Ephemeral (In-Memory)\n"
                "• Long-term Memories: 0"
            )
        await telegram_client.send_message(chat_id, resp_text, parse_mode="Markdown")
        return True
        
    return False
