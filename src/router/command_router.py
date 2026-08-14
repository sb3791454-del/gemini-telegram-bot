"""Command router for Telegram bot slash commands."""

from telegram.client import TelegramClient
from config.prompts import WELCOME_TEXT, HELP_TEXT, RESET_TEXT

async def handle_command(command: str, chat_id: int, telegram_client: TelegramClient) -> bool:
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
        
    return False
