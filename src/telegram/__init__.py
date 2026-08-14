"""Telegram interface package for Sultan Assistant."""

from src.telegram.client import TelegramClient
from src.telegram.formatting import chunk_message
from src.telegram.auth import is_user_authorized

__all__ = [
    "TelegramClient",
    "chunk_message",
    "is_user_authorized",
]
