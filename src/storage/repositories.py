from alerts.models import AlertDefinition
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

    async def add_memory(
        self,
        telegram_user_id: int,
        content: str,
        memory_type: Optional[str] = None
    ) -> Optional[int]:
        """
        Adds a new memory item for the user.
        Rejects empty or duplicate content and enforces user-level limit.
        Returns the inserted memory ID on success, or None on failure.
        """
        if not self.db.is_available:
            return None

        cleaned = content.strip()
        if not cleaned:
            return None

        current_count = await self.count_memories(telegram_user_id)
        if current_count >= MAX_MEMORIES_PER_USER:
            logger.warning(f"User {telegram_user_id} reached maximum memory limit ({MAX_MEMORIES_PER_USER}).")
            return None

        duplicate = await self.find_duplicate_memory(telegram_user_id, cleaned)
        if duplicate:
            return duplicate["id"]

        inferred_type = memory_type if memory_type else infer_memory_type(cleaned)
        now = _get_utc_now_iso()

        sql = """
        INSERT INTO conversation_memories (telegram_user_id, memory_type, content, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """
        success = await self.db.execute(sql, telegram_user_id, inferred_type, cleaned, now, now)
        if success:
            fetch_sql = "SELECT id FROM conversation_memories WHERE telegram_user_id = ? AND content = ? ORDER BY id DESC LIMIT 1"
            row = await self.db.fetch_one(fetch_sql, telegram_user_id, cleaned)
            if row and "id" in row:
                return int(row["id"])
            return 1
        return None

    async def delete_memory(self, telegram_user_id: int, memory_id: int) -> bool:
        """Deletes a specific memory item belonging to the specified user."""
        if not self.db.is_available:
            return False

        existing = await self.get_memory_by_id(telegram_user_id, memory_id)
        if not existing:
            return False

        sql = "DELETE FROM conversation_memories WHERE id = ? AND telegram_user_id = ?"
        return await self.db.execute(sql, memory_id, telegram_user_id)

    async def delete_all_memories(self, telegram_user_id: int) -> bool:
        """Deletes all memory items for the user."""
        if not self.db.is_available:
            return False
        sql = "DELETE FROM conversation_memories WHERE telegram_user_id = ?"
        return await self.db.execute(sql, telegram_user_id)

class SettingsRepository:
    """Manages persistent key-value configuration and session tracking in D1."""
    def __init__(self, db: D1Database):
        self.db = db

    async def get_settings(self, telegram_user_id: int) -> Dict[str, Any]:
        """Fetches all settings for the user as a Python dictionary."""
        if not self.db.is_available:
            return {}
        sql = "SELECT settings_json FROM assistant_settings WHERE telegram_user_id = ?"
        row = await self.db.fetch_one(sql, telegram_user_id)
        if row and "settings_json" in row:
            try:
                return json.loads(row["settings_json"])
            except Exception as e:
                logger.error(f"Failed to parse settings JSON for user {telegram_user_id}: {e}")
                return {}
        return {}

    async def get_setting(self, telegram_user_id: int, key: str, default: Any = None) -> Any:
        """Retrieves a specific setting value for the user."""
        settings = await self.get_settings(telegram_user_id)
        return settings.get(key, default)

    async def set_setting(self, telegram_user_id: int, key: str, value: Any) -> bool:
        """Sets or updates a specific setting key-value pair for the user."""
        if not self.db.is_available:
            return False

        current = await self.get_settings(telegram_user_id)
        current[key] = value
        now = _get_utc_now_iso()
        settings_str = json.dumps(current)

        sql = """
        INSERT INTO assistant_settings (telegram_user_id, settings_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_user_id) DO UPDATE SET
            settings_json = excluded.settings_json,
            updated_at = excluded.updated_at
        """
        return await self.db.execute(sql, telegram_user_id, settings_str, now)

class ConversationRepository:
    """Manages conversation sessions and recent turn history in D1."""
    def __init__(self, db: D1Database, settings_repo: Optional[SettingsRepository] = None):
        self.db = db
        self.settings_repo = settings_repo

    async def get_or_create_active_session(self, telegram_user_id: int) -> Optional[int]:
        """Retrieves the current active session ID or creates a new one."""
        if not self.db.is_available:
            return None

        if self.settings_repo:
            active_id = await self.settings_repo.get_setting(telegram_user_id, "active_session_id")
            if active_id:
                sql_check = "SELECT id FROM conversation_sessions WHERE id = ? AND telegram_user_id = ?"
                existing = await self.db.fetch_one(sql_check, active_id, telegram_user_id)
                if existing:
                    return int(active_id)

        return await self.create_new_session(telegram_user_id)

    async def create_new_session(self, telegram_user_id: int) -> Optional[int]:
        """Creates a brand new conversation session for the user."""
        if not self.db.is_available:
            return None

        now = _get_utc_now_iso()
        sql = "INSERT INTO conversation_sessions (telegram_user_id, created_at, updated_at) VALUES (?, ?, ?)"
        success = await self.db.execute(sql, telegram_user_id, now, now)
        if success:
            fetch_sql = "SELECT id FROM conversation_sessions WHERE telegram_user_id = ? ORDER BY id DESC LIMIT 1"
            row = await self.db.fetch_one(fetch_sql, telegram_user_id)
            if row and "id" in row:
                session_id = int(row["id"])
                if self.settings_repo:
                    await self.settings_repo.set_setting(telegram_user_id, "active_session_id", session_id)
                return session_id
        return None

    async def get_recent_messages(
        self,
        telegram_user_id: int,
        session_id: int,
        limit: int = CONVERSATION_HISTORY_LIMIT
    ) -> List[Dict[str, Any]]:
        """Retrieves the most recent messages for a session in chronological order."""
        if not self.db.is_available:
            return []

        sql = """
        SELECT role, content, created_at
        FROM conversation_messages
        WHERE session_id = ? AND telegram_user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """
        rows = await self.db.fetch_all(sql, session_id, telegram_user_id, limit)
        return list(reversed(rows))

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

    async def get_total_message_count(self, telegram_user_id: int) -> int:
        """Returns total messages count for user across all sessions."""
        if not self.db.is_available or not telegram_user_id:
            return 0
        sql = "SELECT COUNT(*) as count FROM conversation_messages WHERE telegram_user_id = ?"
        row = await self.db.fetch_one(sql, telegram_user_id)
        if row and "count" in row:
            return int(row["count"])
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


class AlertRepository:
    """Manages persistent user alerts and trigger audit logs in Cloudflare D1."""

    def __init__(self, db: D1Database):
        self.db = db

    def _row_to_alert_def(self, row: Dict[str, Any]) -> AlertDefinition:
        """Helper to convert D1 row dict to AlertDefinition dataclass."""
        return AlertDefinition(
            id=int(row.get("id", 0)),
            telegram_user_id=int(row.get("telegram_user_id", 0)),
            symbol=str(row.get("symbol", "")),
            alert_type=str(row.get("alert_type", "")),
            timeframe=str(row.get("timeframe", "1h")),
            target_value=float(row["target_value"]) if row.get("target_value") is not None else None,
            direction=str(row["direction"]) if row.get("direction") is not None else None,
            status=str(row.get("status", "ARMED")),
            cooldown_minutes=int(row.get("cooldown_minutes", 60)),
            is_recurring=int(row.get("is_recurring", 0)),
            user_capital=float(row["user_capital"]) if row.get("user_capital") is not None else None,
            user_risk_pct=float(row["user_risk_pct"]) if row.get("user_risk_pct") is not None else None,
            last_evaluated_at=row.get("last_evaluated_at"),
            last_triggered_at=row.get("last_triggered_at"),
            last_state_payload=row.get("last_state_payload"),
            notes=row.get("notes"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    async def create_alert(
        self,
        user_id: int,
        symbol: str,
        alert_type: str,
        target_value: Optional[float] = None,
        direction: Optional[str] = None,
        timeframe: str = "1h",
        cooldown_minutes: int = 60,
        is_recurring: int = 0,
        user_capital: Optional[float] = None,
        user_risk_pct: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> Optional[int]:
        """Creates a new persistent alert in D1 and returns its auto-incremented ID."""
        if not self.db.is_available or not user_id:
            return None

        clean_sym = symbol.strip().upper()
        now_iso = _get_utc_now_iso()
        sql = """
        INSERT INTO user_alerts (
            telegram_user_id, symbol, alert_type, timeframe, target_value, direction,
            status, cooldown_minutes, is_recurring, user_capital, user_risk_pct,
            notes, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'ARMED', ?, ?, ?, ?, ?, ?, ?)
        """
        success = await self.db.execute(
            sql,
            user_id,
            clean_sym,
            alert_type.upper(),
            timeframe.lower(),
            target_value,
            direction.upper() if direction else None,
            cooldown_minutes,
            is_recurring,
            user_capital,
            user_risk_pct,
            notes or "",
            now_iso,
            now_iso
        )
        if success:
            fetch_sql = "SELECT id FROM user_alerts WHERE telegram_user_id = ? AND symbol = ? AND created_at = ? ORDER BY id DESC LIMIT 1"
            row = await self.db.fetch_one(fetch_sql, user_id, clean_sym, now_iso)
            if row and "id" in row:
                return int(row["id"])
            return 1
        return None

    async def get_alert_by_id(self, alert_id: int, user_id: Optional[int] = None) -> Optional[AlertDefinition]:
        """Fetches a specific alert by ID, optionally validating owner user ID."""
        if not self.db.is_available or not alert_id:
            return None

        if user_id is not None:
            sql = "SELECT * FROM user_alerts WHERE id = ? AND telegram_user_id = ?"
            row = await self.db.fetch_one(sql, alert_id, user_id)
        else:
            sql = "SELECT * FROM user_alerts WHERE id = ?"
            row = await self.db.fetch_one(sql, alert_id)

        if row:
            return self._row_to_alert_def(row)
        return None

    async def get_user_alerts(self, user_id: int, limit: int = 20) -> List[AlertDefinition]:
        """Retrieves all alert rules configured by a specific user."""
        if not self.db.is_available or not user_id:
            return []

        sql = "SELECT * FROM user_alerts WHERE telegram_user_id = ? ORDER BY id DESC LIMIT ?"
        rows = await self.db.fetch_all(sql, user_id, limit)
        return [self._row_to_alert_def(r) for r in rows]

    async def get_all_active_alerts(self, limit: int = 100) -> List[AlertDefinition]:
        """Retrieves all ARMED and COOLDOWN alerts across all users for scheduled tick evaluation."""
        if not self.db.is_available:
            return []

        sql = "SELECT * FROM user_alerts WHERE status IN ('ARMED', 'COOLDOWN') ORDER BY id ASC LIMIT ?"
        rows = await self.db.fetch_all(sql, limit)
        return [self._row_to_alert_def(r) for r in rows]

    async def update_alert_status(
        self,
        alert_id: int,
        status: str,
        last_triggered_at: Optional[str] = None,
        last_state_payload: Optional[str] = None
    ) -> bool:
        """Updates alert status, trigger timestamp, and market state payload."""
        if not self.db.is_available or not alert_id:
            return False

        now_iso = _get_utc_now_iso()
        if last_triggered_at:
            sql = """
            UPDATE user_alerts
            SET status = ?, last_evaluated_at = ?, last_triggered_at = ?, last_state_payload = ?, updated_at = ?
            WHERE id = ?
            """
            return await self.db.execute(sql, status, now_iso, last_triggered_at, last_state_payload, now_iso, alert_id)
        else:
            sql = """
            UPDATE user_alerts
            SET status = ?, last_evaluated_at = ?, last_state_payload = COALESCE(?, last_state_payload), updated_at = ?
            WHERE id = ?
            """
            return await self.db.execute(sql, status, now_iso, last_state_payload, now_iso, alert_id)

    async def pause_alert(self, alert_id: int, user_id: int) -> bool:
        """Pauses monitoring for a user's alert."""
        if not self.db.is_available or not user_id or not alert_id:
            return False

        now_iso = _get_utc_now_iso()
        sql = "UPDATE user_alerts SET status = 'PAUSED', updated_at = ? WHERE id = ? AND telegram_user_id = ?"
        return await self.db.execute(sql, now_iso, alert_id, user_id)

    async def resume_alert(self, alert_id: int, user_id: int) -> bool:
        """Resumes monitoring for a paused alert."""
        if not self.db.is_available or not user_id or not alert_id:
            return False

        now_iso = _get_utc_now_iso()
        sql = "UPDATE user_alerts SET status = 'ARMED', updated_at = ? WHERE id = ? AND telegram_user_id = ?"
        return await self.db.execute(sql, now_iso, alert_id, user_id)

    async def delete_alert(self, alert_id: int, user_id: int) -> bool:
        """Deletes an alert rule owned by the user."""
        if not self.db.is_available or not user_id or not alert_id:
            return False

        sql = "DELETE FROM user_alerts WHERE id = ? AND telegram_user_id = ?"
        return await self.db.execute(sql, alert_id, user_id)

    async def record_trigger_history(
        self,
        alert_id: int,
        telegram_user_id: int,
        symbol: str,
        trigger_price: float,
        trigger_reason: str,
        setup_state: Optional[str] = None,
        hard_sl_price: Optional[float] = None,
        tp1_price: Optional[float] = None,
        notification_status: str = "DELIVERED"
    ) -> bool:
        """Records an immutable push notification attempt in the trigger history."""
        if not self.db.is_available:
            return False

        now_iso = _get_utc_now_iso()
        sql = """
        INSERT INTO alert_trigger_history (
            alert_id, telegram_user_id, symbol, trigger_price, trigger_reason,
            setup_state, hard_sl_price, tp1_price, notification_status, delivered_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        return await self.db.execute(
            sql,
            alert_id,
            telegram_user_id,
            symbol,
            trigger_price,
            trigger_reason,
            setup_state,
            hard_sl_price,
            tp1_price,
            notification_status,
            now_iso
        )

    async def get_alert_count(self, user_id: int) -> int:
        """Returns total active and configured alerts for a user."""
        if not self.db.is_available or not user_id:
            return 0
        sql = "SELECT COUNT(*) as count FROM user_alerts WHERE telegram_user_id = ? AND status != 'DISABLED'"
        row = await self.db.fetch_one(sql, user_id)
        if row and "count" in row:
            return int(row["count"])
        return 0
