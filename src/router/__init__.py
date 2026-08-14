"""Routing package for commands and message dispatching."""

from src.router.command_router import handle_command
from src.router.message_router import dispatch_telegram_update

__all__ = [
    "handle_command",
    "dispatch_telegram_update",
]
