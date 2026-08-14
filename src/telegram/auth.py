"""User authorization and access control."""

import logging
from config.settings import Settings

logger = logging.getLogger("worker.auth")

def is_user_authorized(user_id: int | None, settings: Settings) -> bool:
    """
    Checks if a Telegram user ID is authorized to use the bot.
    
    If ALLOWED_USER_IDS is configured (non-empty), user_id must be in the whitelist.
    If ALLOWED_USER_IDS is not configured (empty), open access is allowed for backward compatibility.
    """
    if not settings.is_private_mode_enabled:
        return True
    
    if user_id is None:
        logger.warning("Authorization rejected: update does not contain a valid user ID.")
        return False
        
    authorized = user_id in settings.allowed_user_ids
    if not authorized:
        logger.info("Unauthorized access attempt blocked.")
    return authorized
