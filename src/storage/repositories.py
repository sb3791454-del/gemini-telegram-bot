"""Repository abstractions for User Profile, Memory, and Assistant Settings."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from storage.database import D1Database

logger = logging.getLogger("worker.storage.repositories")

def _get_utc_now_iso() -> str:
    """Returns current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()

class UserRepository:
    """Manages user profile records in D1."""
    def __init__(self, db: D1Database):
        self.db = db

    async def get_user_profile(self, telegram_user_id: int) -> Optional[Dict[str, Any]]:
        """Fetches a user profile by Telegram numeric ID."""
        sql = "SELECT * FROM user_profiles WHERE telegram_user_id = ?"
        return await self.db.fetch_one(sql, telegram_user_id)

    async def upsert_user_profile(
        self,
        telegram_user_id: int,
        display_name: Optional[str] = None,
        username: Optional[str] = None,
        preferences: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Inserts a new user profile or updates last_seen_at and metadata for existing user.
        Preserves first_seen_at across updates.
        """
        now = _get_utc_now_iso()
        prefs_json = json.dumps(preferences) if preferences is not None else None

        existing = await self.get_user_profile(telegram_user_id)
        if existing:
            if prefs_json is not None:
                sql = """
                UPDATE user_profiles
                SET last_seen_at = ?, display_name = COALESCE(?, display_name),
                    username = COALESCE(?, username), preferences_json = ?
                WHERE telegram_user_id = ?
                """
                return await self.db.execute(sql, now, display_name, username, prefs_json, telegram_user_id)
            else:
                sql = """
                UPDATE user_profiles
                SET last_seen_at = ?, display_name = COALESCE(?, display_name),
                    username = COALESCE(?, username)
                WHERE telegram_user_id = ?
                """
                return await self.db.execute(sql, now, display_name, username, telegram_user_id)
        else:
            init_prefs = prefs_json if prefs_json is not None else "{}"
            sql = """
            INSERT INTO user_profiles (telegram_user_id, first_seen_at, last_seen_at, display_name, username, preferences_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """
            return await self.db.execute(sql, telegram_user_id, now, now, display_name, username, init_prefs)

class MemoryRepository:
    """Manages conversation memory and semantic knowledge items."""
    def __init__(self, db: D1Database):
        self.db = db

    async def add_memory(self, telegram_user_id: int, memory_type: str, content: str) -> bool:
        """Stores a new discrete memory item."""
        now = _get_utc_now_iso()
        sql = """
        INSERT INTO conversation_memories (telegram_user_id, memory_type, content, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """
        return await self.db.execute(sql, telegram_user_id, memory_type, content, now, now)

    async def count_memories(self, telegram_user_id: int) -> int:
        """Returns the total number of stored memory entries for a user."""
        sql = "SELECT COUNT(*) as count FROM conversation_memories WHERE telegram_user_id = ?"
        row = await self.db.fetch_one(sql, telegram_user_id)
        if row and "count" in row:
            return int(row["count"])
        return 0

    async def get_memories(self, telegram_user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieves recent memories for a user."""
        sql = "SELECT * FROM conversation_memories WHERE telegram_user_id = ? ORDER BY created_at DESC LIMIT ?"
        return await self.db.fetch_all(sql, telegram_user_id, limit)

class SettingsRepository:
    """Manages user-specific assistant settings."""
    def __init__(self, db: D1Database):
        self.db = db

    async def get_settings(self, telegram_user_id: int) -> Dict[str, Any]:
        """Retrieves user settings dict."""
        sql = "SELECT settings_json FROM assistant_settings WHERE telegram_user_id = ?"
        row = await self.db.fetch_one(sql, telegram_user_id)
        if row and "settings_json" in row:
            try:
                return json.loads(row["settings_json"])
            except Exception:
                pass
        return {}

    async def update_settings(self, telegram_user_id: int, settings: Dict[str, Any]) -> bool:
        """Upserts user settings."""
        now = _get_utc_now_iso()
        settings_str = json.dumps(settings)
        sql = """
        INSERT INTO assistant_settings (telegram_user_id, settings_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_user_id) DO UPDATE SET settings_json = ?, updated_at = ?
        """
        return await self.db.execute(sql, telegram_user_id, settings_str, now, settings_str, now)
