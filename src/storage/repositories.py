"""Repository layer for user profiles, persistent memory, and conversation history in Cloudflare D1."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from storage.database import D1Database

logger = logging.getLogger("worker.storage.repositories")


def infer_memory_type(content: str) -> str:
    """Infers memory classification (goal, preference, instruction, fact) based on keywords."""
    c = content.lower()
    if any(k in c for k in ("want", "goal", "target", "aim", "plan", "wish", "مقصد", "ہدف", "خواہش", "ارادہ")):
        return "goal"
    if any(k in c for k in ("prefer", "like", "love", "favorite", "style", "پسند", "ترجیح", "شوق")):
        return "preference"
    if any(k in c for k in ("always", "never", "rule", "instruction", "must", "ہمیشہ", "کبھی نہیں", "اصول", "لازمی")):
        return "instruction"
    return "fact"


class UserRepository:
    """Manages user profiles, first seen, and last seen timestamps in D1."""
    def __init__(self, db: D1Database):
        self.db = db

    async def upsert_user_profile(
        self,
        telegram_user_id: int,
        display_name: str = "",
        username: str = "",
    ) -> bool:
        if not self.db.is_available or not telegram_user_id:
            return False
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        query = """
        INSERT INTO user_profiles (telegram_user_id, first_seen_at, last_seen_at, display_name, username)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(telegram_user_id) DO UPDATE SET
            last_seen_at = excluded.last_seen_at,
            display_name = COALESCE(NULLIF(excluded.display_name, ''), user_profiles.display_name),
            username = COALESCE(NULLIF(excluded.username, ''), user_profiles.username);
        """
        return await self.db.execute(query, telegram_user_id, now_iso, now_iso, display_name, username)

    async def get_user_profile(self, telegram_user_id: int) -> Optional[Dict[str, Any]]:
        if not self.db.is_available or not telegram_user_id:
            return None
        query = "SELECT * FROM user_profiles WHERE telegram_user_id = ?;"
        return await self.db.fetch_one(query, telegram_user_id)


class MemoryRepository:
    """Manages explicit long-term user memories (goals, preferences, instructions, facts) in D1."""
    MAX_MEMORIES_PER_USER = 100

    def __init__(self, db: D1Database):
        self.db = db

    async def add_memory(
        self,
        telegram_user_id: int,
        content: str,
        memory_type: str = "fact"
    ) -> Optional[int]:
        if not self.db.is_available or not telegram_user_id or not content.strip():
            return None

        # Check limit
        count = await self.get_memory_count(telegram_user_id)
        if count >= self.MAX_MEMORIES_PER_USER:
            logger.warning(f"User {telegram_user_id} reached maximum memory limit ({self.MAX_MEMORIES_PER_USER}).")
            return None

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        query = """
        INSERT INTO conversation_memories (telegram_user_id, memory_type, content, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?);
        """
        success = await self.db.execute(query, telegram_user_id, memory_type, content.strip(), now_iso, now_iso)
        if success:
            last_row = await self.db.fetch_one(
                "SELECT id FROM conversation_memories WHERE telegram_user_id = ? ORDER BY id DESC LIMIT 1;",
                telegram_user_id
            )
            return last_row.get("id") if last_row else None
        return None

    async def get_all_memories(self, telegram_user_id: int) -> List[Dict[str, Any]]:
        if not self.db.is_available or not telegram_user_id:
            return []
        query = "SELECT id, memory_type, content, created_at FROM conversation_memories WHERE telegram_user_id = ? ORDER BY id ASC;"
        return await self.db.fetch_all(query, telegram_user_id)

    async def delete_memory(self, telegram_user_id: int, memory_id: int) -> bool:
        if not self.db.is_available or not telegram_user_id or not memory_id:
            return False
        query = "DELETE FROM conversation_memories WHERE id = ? AND telegram_user_id = ?;"
        return await self.db.execute(query, memory_id, telegram_user_id)

    async def clear_all_memories(self, telegram_user_id: int) -> bool:
        if not self.db.is_available or not telegram_user_id:
            return False
        query = "DELETE FROM conversation_memories WHERE telegram_user_id = ?;"
        return await self.db.execute(query, telegram_user_id)

    async def get_memory_count(self, telegram_user_id: int) -> int:
        if not self.db.is_available or not telegram_user_id:
            return 0
        query = "SELECT COUNT(*) as count FROM conversation_memories WHERE telegram_user_id = ?;"
        row = await self.db.fetch_one(query, telegram_user_id)
        if row:
            return int(row.get("count", 0))
        return 0


class SettingsRepository:
    """Manages persistent assistant settings and active session tracking pointer in D1."""
    def __init__(self, db: D1Database):
        self.db = db

    async def get_settings(self, telegram_user_id: int) -> Dict[str, Any]:
        if not self.db.is_available or not telegram_user_id:
            return {}
        query = "SELECT settings_json FROM assistant_settings WHERE telegram_user_id = ?;"
        row = await self.db.fetch_one(query, telegram_user_id)
        if row and row.get("settings_json"):
            try:
                return json.loads(row["settings_json"])
            except Exception:
                return {}
        return {}

    async def update_settings(self, telegram_user_id: int, new_settings: Dict[str, Any]) -> bool:
        if not self.db.is_available or not telegram_user_id:
            return False
        current = await self.get_settings(telegram_user_id)
        current.update(new_settings)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        query = """
        INSERT INTO assistant_settings (telegram_user_id, settings_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_user_id) DO UPDATE SET
            settings_json = excluded.settings_json,
            updated_at = excluded.updated_at;
        """
        return await self.db.execute(query, telegram_user_id, json.dumps(current), now_iso)


class ConversationRepository:
    """Manages active and historical conversation sessions and message turns in D1."""
    def __init__(self, db: D1Database, settings_repo: Optional[SettingsRepository] = None):
        self.db = db
        self.settings_repo = settings_repo or SettingsRepository(db)

    async def get_or_create_active_session(self, telegram_user_id: int) -> Optional[Dict[str, Any]]:
        if not self.db.is_available or not telegram_user_id:
            return None

        # Check settings for active_session_id
        settings = await self.settings_repo.get_settings(telegram_user_id)
        active_id = settings.get("active_session_id")

        if active_id:
            session = await self.db.fetch_one(
                "SELECT * FROM conversation_sessions WHERE id = ? AND telegram_user_id = ?;",
                active_id, telegram_user_id
            )
            if session:
                return session

        # Create new session if none active
        return await self.create_new_session(telegram_user_id)

    async def create_new_session(self, telegram_user_id: int) -> Optional[Dict[str, Any]]:
        if not self.db.is_available or not telegram_user_id:
            return None

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        query = "INSERT INTO conversation_sessions (telegram_user_id, created_at, updated_at) VALUES (?, ?, ?);"
        success = await self.db.execute(query, telegram_user_id, now_iso, now_iso)
        if not success:
            return None

        session = await self.db.fetch_one(
            "SELECT * FROM conversation_sessions WHERE telegram_user_id = ? ORDER BY id DESC LIMIT 1;",
            telegram_user_id
        )
        if session:
            await self.settings_repo.update_settings(telegram_user_id, {"active_session_id": session["id"]})
        return session

    async def add_message(self, telegram_user_id: int, session_id: int, role: str, content: str) -> bool:
        if not self.db.is_available or not telegram_user_id or not session_id or not content.strip():
            return False

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        query = """
        INSERT INTO conversation_messages (session_id, telegram_user_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?);
        """
        success = await self.db.execute(query, session_id, telegram_user_id, role.lower(), content.strip(), now_iso)
        if success:
            # Touch session updated_at
            await self.db.execute(
                "UPDATE conversation_sessions SET updated_at = ? WHERE id = ? AND telegram_user_id = ?;",
                now_iso, session_id, telegram_user_id
            )
        return success

    async def get_recent_messages(self, telegram_user_id: int, session_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        if not self.db.is_available or not telegram_user_id or not session_id:
            return []

        query = """
        SELECT id, role, content, created_at
        FROM conversation_messages
        WHERE session_id = ? AND telegram_user_id = ?
        ORDER BY id DESC
        LIMIT ?;
        """
        rows = await self.db.fetch_all(query, session_id, telegram_user_id, limit)
        # Return in chronological order
        return list(reversed(rows)) if rows else []

    async def get_total_message_count(self, telegram_user_id: int) -> int:
        if not self.db.is_available or not telegram_user_id:
            return 0
        query = "SELECT COUNT(*) as count FROM conversation_messages WHERE telegram_user_id = ?;"
        row = await self.db.fetch_one(query, telegram_user_id)
        if row:
            return int(row.get("count", 0))
        return 0


class WatchlistRepository:
    """Manages persistent tracked cryptocurrency watchlist in Cloudflare D1."""
    def __init__(self, db: D1Database):
        self.db = db

    async def add_to_watchlist(self, user_id: int, symbol: str, notes: Optional[str] = None) -> bool:
        """Adds a symbol to the user's watchlist."""
        if not self.db.is_available or not user_id:
            return False
        clean_sym = symbol.strip().upper()
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        query = """
        INSERT INTO user_watchlist (telegram_user_id, symbol, added_at, notes)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(telegram_user_id, symbol) DO UPDATE SET
            added_at = excluded.added_at,
            notes = COALESCE(excluded.notes, user_watchlist.notes);
        """
        return await self.db.execute(query, user_id, clean_sym, now_iso, notes or "")

    async def remove_from_watchlist(self, user_id: int, symbol: str) -> bool:
        """Removes a symbol from the user's watchlist."""
        if not self.db.is_available or not user_id:
            return False
        clean_sym = symbol.strip().upper()
        query = "DELETE FROM user_watchlist WHERE telegram_user_id = ? AND symbol = ?;"
        return await self.db.execute(query, user_id, clean_sym)

    async def get_watchlist(self, user_id: int) -> List[Dict[str, Any]]:
        """Returns list of tracked symbols for the user."""
        if not self.db.is_available or not user_id:
            return []
        query = "SELECT symbol, added_at, notes FROM user_watchlist WHERE telegram_user_id = ? ORDER BY added_at ASC;"
        return await self.db.fetch_all(query, user_id)

    async def get_watchlist_count(self, user_id: int) -> int:
        if not self.db.is_available or not user_id:
            return 0
        query = "SELECT COUNT(*) as count FROM user_watchlist WHERE telegram_user_id = ?;"
        row = await self.db.fetch_one(query, user_id)
        if row:
            return int(row.get("count", 0))
        return 0
