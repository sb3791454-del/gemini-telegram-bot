"""User authorization and access control."""

import logging
from config.settings import Settings

logger = logging.getLogger("worker.auth")

def is_user_authorized(user_id: int | None, settings: Settings) -> bool:
    """
    Checks if a Telegram user ID is authorized to use the bot.
    
    Security Policy: FAIL CLOSED.
    - If ALLOWED_USER_IDS is missing, empty, invalid, or contains no valid IDs,
      access is DENIED to all users.
    - If user_id is None, access is DENIED.
    - Only users explicitly present in settings.allowed_user_ids are granted access.
    """
    if not settings.is_private_mode_enabled:
        logger.warning("Authorization rejected: Bot is locked because no valid ALLOWED_USER_IDS are configured (fail-closed policy).")
        return False
    
    if user_id is None:
        logger.warning("Authorization rejected: Update does not contain a valid user ID.")
        return False
        
    authorized = user_id in settings.allowed_user_ids
    if not authorized:
        logger.info("Unauthorized access attempt blocked.")
    return authorized
