"""Repository abstractions for User Profile, Memory, and Assistant Settings."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from storage.database import D1Database

logger = logging.getLogger("worker.storage.repositories")

MAX_MEMORIES_PER_USER = 100

def _get_utc_now_iso() -> str:
    """Returns current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()

def infer_memory_type(content: str) -> str:
    """Classifies memory text into standard categories: goal, preference, instruction, or fact."""
    lower = content.lower()
    if any(k in lower for k in ["want to", "goal", "aim to", "aspire", "hope to", "plan to", "wish to", "dream", "چاہتا ہوں", "ارادہ", "مقصد"]):
        return "goal"
    if any(k in lower for k in ["prefer", "like", "favorite", "dislike", "hate", "love", "پسند", "ناپسند"]):
        return "preference"
    if any(k in lower for k in ["always", "never", "must", "instruct", "rule", "guideline", "جب بھی", "ہمیشہ", "کبھی نہیں"]):
        return "instruction"
    return "fact"

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
    """Manages long-term conversation memories and knowledge items."""
    def __init__(self, db: D1Database):
        self.db = db

    async def count_memories(self, telegram_user_id: int) -> int:
        """Returns the total number of stored memory entries for a specific user."""
        sql = "SELECT COUNT(*) as count FROM conversation_memories WHERE telegram_user_id = ?"
        row = await self.db.fetch_one(sql, telegram_user_id)
        if row and "count" in row:
            return int(row["count"])
        return 0

    async def get_all_memories(self, telegram_user_id: int, limit: int = MAX_MEMORIES_PER_USER) -> List[Dict[str, Any]]:
        """Retrieves all memories belonging strictly to the specified Telegram user."""
        sql = """
        SELECT id, telegram_user_id, memory_type, content, created_at, updated_at
        FROM conversation_memories
        WHERE telegram_user_id = ?
        ORDER BY id ASC
        LIMIT ?
        """
        return await self.db.fetch_all(sql, telegram_user_id, limit)

    async def get_memory_by_id(self, telegram_user_id: int, memory_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a single memory item strictly scoped by user ID and memory ID."""
        sql = """
        SELECT id, telegram_user_id, memory_type, content, created_at, updated_at
        FROM conversation_memories
        WHERE id = ? AND telegram_user_id = ?
        """
        return await self.db.fetch_one(sql, memory_id, telegram_user_id)

    async def find_duplicate_memory(self, telegram_user_id: int, content: str) -> Optional[Dict[str, Any]]:
        """Checks if exact matching memory content already exists for this user."""
        sql = """
        SELECT id, memory_type, content
        FROM conversation_memories
        WHERE telegram_user_id = ? AND LOWER(TRIM(content)) = LOWER(TRIM(?))
        LIMIT 1
        """
        return await self.db.fetch_one(sql, telegram_user_id, content)

    async def add_memory(self, telegram_user_id: int, memory_type: str, content: str) -> Dict[str, Any]:
        """
        Stores a new discrete memory item after validating limits and duplicates.
        Returns result dict with status and metadata.
        """
        cleaned_content = content.strip()
        if not cleaned_content:
            return {"success": False, "reason": "empty_content"}

        # 1. Enforce memory capacity limit (100 max per user)
        current_count = await self.count_memories(telegram_user_id)
        if current_count >= MAX_MEMORIES_PER_USER:
            return {"success": False, "reason": "limit_reached", "limit": MAX_MEMORIES_PER_USER}

        # 2. Check for exact duplicate content
        existing_dup = await self.find_duplicate_memory(telegram_user_id, cleaned_content)
        if existing_dup:
            return {"success": False, "reason": "duplicate", "existing": existing_dup}

        now = _get_utc_now_iso()
        sql = """
        INSERT INTO conversation_memories (telegram_user_id, memory_type, content, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """
        executed = await self.db.execute(sql, telegram_user_id, memory_type, cleaned_content, now, now)
        if executed:
            return {"success": True, "memory_type": memory_type, "content": cleaned_content}
        return {"success": False, "reason": "db_error"}

    async def delete_memory(self, telegram_user_id: int, memory_id: int) -> bool:
        """Deletes a single memory item strictly scoped by user ID."""
        sql = "DELETE FROM conversation_memories WHERE id = ? AND telegram_user_id = ?"
        return await self.db.execute(sql, memory_id, telegram_user_id)

    async def delete_all_memories(self, telegram_user_id: int) -> bool:
        """Deletes all memories belonging strictly to the specified Telegram user."""
        sql = "DELETE FROM conversation_memories WHERE telegram_user_id = ?"
        return await self.db.execute(sql, telegram_user_id)

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
