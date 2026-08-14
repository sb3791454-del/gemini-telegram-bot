"""Application settings and environment variable extraction."""

from typing import Set, Optional

# Default constants
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"
TELEGRAM_SAFE_CHUNK_LIMIT = 4000
MAX_HTTP_TIMEOUT_SECONDS = 25

class Settings:
    """Encapsulates runtime environment configuration."""
    def __init__(self, env):
        self.telegram_bot_token: Optional[str] = getattr(env, "TELEGRAM_BOT_TOKEN", None)
        self.gemini_api_key: Optional[str] = getattr(env, "GEMINI_API_KEY", None)
        self.gemini_model: str = getattr(env, "GEMINI_MODEL", None) or DEFAULT_GEMINI_MODEL
        self.webhook_secret: Optional[str] = getattr(env, "WEBHOOK_SECRET", None)
        self.setup_secret: Optional[str] = getattr(env, "SETUP_SECRET", None)
        
        # Parse ALLOWED_USER_IDS (comma-separated list of numeric Telegram IDs)
        raw_allowed = getattr(env, "ALLOWED_USER_IDS", None)
        self.allowed_user_ids: Set[int] = self._parse_user_ids(raw_allowed)

    @staticmethod
    def _parse_user_ids(raw_value: Optional[str]) -> Set[int]:
        if not raw_value:
            return set()
        user_ids = set()
        for item in str(raw_value).split(","):
            cleaned = item.strip()
            if cleaned.isdigit():
                user_ids.add(int(cleaned))
        return user_ids

    @property
    def is_private_mode_enabled(self) -> bool:
        """Returns True if user authorization whitelist is actively enforcing access."""
        return len(self.allowed_user_ids) > 0
