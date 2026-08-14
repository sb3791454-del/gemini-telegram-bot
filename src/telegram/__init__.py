"""Telegram interface package for Sultan Assistant."""

from telegram.client import TelegramClient
from telegram.formatting import chunk_message
from telegram.auth import is_user_authorized

__all__ = [
    "TelegramClient",
    "chunk_message",
    "is_user_authorized",
]
