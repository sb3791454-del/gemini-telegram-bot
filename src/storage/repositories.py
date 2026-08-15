"""Repository abstractions for User Profile, Memory, Settings, and Conversation History."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from config.settings import CONVERSATION_HISTORY_LIMIT
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

class ConversationRepository:
    """Manages active conversation sessions and recent message history in D1."""
    def __init__(self, db: D1Database, settings_repo: Optional[SettingsRepository] = None):
        self.db = db
        self.settings_repo = settings_repo or SettingsRepository(db)

    async def get_or_create_active_session(self, telegram_user_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieves the user's active session, or creates a new one if none exists.
        Verifies session ownership strictly.
        """
        if not self.db.is_available:
            return None

        # 1. Check assistant_settings for active_session_id
        settings = await self.settings_repo.get_settings(telegram_user_id)
        active_session_id = settings.get("active_session_id")
        
        if active_session_id is not None:
            sql = "SELECT id, telegram_user_id, created_at, updated_at FROM conversation_sessions WHERE id = ? AND telegram_user_id = ?"
            session = await self.db.fetch_one(sql, active_session_id, telegram_user_id)
            if session:
                return session

        # 2. Check the most recent session in conversation_sessions
        sql_recent = "SELECT id, telegram_user_id, created_at, updated_at FROM conversation_sessions WHERE telegram_user_id = ? ORDER BY id DESC LIMIT 1"
        recent_session = await self.db.fetch_one(sql_recent, telegram_user_id)
        if recent_session:
            settings["active_session_id"] = recent_session["id"]
            await self.settings_repo.update_settings(telegram_user_id, settings)
            return recent_session

        # 3. Create a fresh session if none exists
        return await self.create_new_session(telegram_user_id)

    async def create_new_session(self, telegram_user_id: int) -> Optional[Dict[str, Any]]:
        """
        Creates a fresh conversation session for the user and points active_session_id to it.
        Preserves existing user settings.
        """
        if not self.db.is_available:
            return None

        now = _get_utc_now_iso()
        sql = "INSERT INTO conversation_sessions (telegram_user_id, created_at, updated_at) VALUES (?, ?, ?)"
        success = await self.db.execute(sql, telegram_user_id, now, now)
        if not success:
            return None

        sql_fetch = "SELECT id, telegram_user_id, created_at, updated_at FROM conversation_sessions WHERE telegram_user_id = ? ORDER BY id DESC LIMIT 1"
        new_session = await self.db.fetch_one(sql_fetch, telegram_user_id)
        if new_session:
            settings = await self.settings_repo.get_settings(telegram_user_id)
            settings["active_session_id"] = new_session["id"]
            await self.settings_repo.update_settings(telegram_user_id, settings)
            return new_session

        return None

    async def get_recent_messages(
        self,
        telegram_user_id: int,
        session_id: int,
        limit: int = CONVERSATION_HISTORY_LIMIT
    ) -> List[Dict[str, Any]]:
        """
        Retrieves recent messages from the session ordered chronologically (oldest to newest).
        Enforces strict user isolation.
        """
        if not self.db.is_available:
            return []

        sql = """
        SELECT id, session_id, telegram_user_id, role, content, created_at
        FROM conversation_messages
        WHERE session_id = ? AND telegram_user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """
        rows = await self.db.fetch_all(sql, session_id, telegram_user_id, limit)
        if rows:
            return list(reversed(rows))
        return []

    async def add_message(
        self,
        telegram_user_id: int,
        session_id: int,
        role: str,
        content: str
    ) -> bool:
        """
        Appends a message to the active session and advances the session updated_at timestamp.
        Enforces strict session ownership.
        """
        if not self.db.is_available:
            return False

        if role not in ("user", "assistant"):
            logger.warning(f"Invalid message role '{role}' rejected.")
            return False

        cleaned_content = content.strip()
        if not cleaned_content:
            return False

        # Verify that session_id belongs to telegram_user_id
        sql_verify = "SELECT id FROM conversation_sessions WHERE id = ? AND telegram_user_id = ?"
        session = await self.db.fetch_one(sql_verify, session_id, telegram_user_id)
        if not session:
            logger.error(f"Cannot add message: session {session_id} does not belong to user {telegram_user_id}")
            return False

        now = _get_utc_now_iso()
        sql_insert = """
        INSERT INTO conversation_messages (session_id, telegram_user_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?)
        """
        inserted = await self.db.execute(sql_insert, session_id, telegram_user_id, role, cleaned_content, now)
        
        if inserted:
            sql_update_sess = "UPDATE conversation_sessions SET updated_at = ? WHERE id = ? AND telegram_user_id = ?"
            await self.db.execute(sql_update_sess, now, session_id, telegram_user_id)
            return True

        return False

    async def clear_session(self, telegram_user_id: int, session_id: int) -> bool:
        """Deletes messages in the given session for the user."""
        if not self.db.is_available:
            return False
        sql = "DELETE FROM conversation_messages WHERE session_id = ? AND telegram_user_id = ?"
        return await self.db.execute(sql, session_id, telegram_user_id)
