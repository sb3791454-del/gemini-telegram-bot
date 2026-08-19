-- Sultan Assistant Database Schema (Cloudflare D1)

-- 1. User Profiles
CREATE TABLE IF NOT EXISTS user_profiles (\n    telegram_user_id INTEGER PRIMARY KEY,\n    first_seen_at TEXT NOT NULL,\n    last_seen_at TEXT NOT NULL,\n    display_name TEXT,\n    username TEXT,\n    preferences_json TEXT NOT NULL DEFAULT '{}'\n);

-- 2. Long-Term Conversation Memories (Phase 3)
CREATE TABLE IF NOT EXISTS conversation_memories (\n    id INTEGER PRIMARY KEY AUTOINCREMENT,\n    telegram_user_id INTEGER NOT NULL,\n    memory_type TEXT NOT NULL,\n    content TEXT NOT NULL,\n    created_at TEXT NOT NULL,\n    updated_at TEXT NOT NULL,\n    FOREIGN KEY (telegram_user_id) REFERENCES user_profiles(telegram_user_id) ON DELETE CASCADE\n);

CREATE INDEX IF NOT EXISTS idx_memories_user_id ON conversation_memories(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_memories_type ON conversation_memories(memory_type);

-- 3. Assistant Settings (Persistent User Settings & Active Session Pointer)
CREATE TABLE IF NOT EXISTS assistant_settings (\n    telegram_user_id INTEGER PRIMARY KEY,\n    settings_json TEXT NOT NULL DEFAULT '{}',\n    updated_at TEXT NOT NULL,\n    FOREIGN KEY (telegram_user_id) REFERENCES user_profiles(telegram_user_id) ON DELETE CASCADE\n);

-- 4. Conversation Sessions (Phase 4: Session History)
CREATE TABLE IF NOT EXISTS conversation_sessions (\n    id INTEGER PRIMARY KEY AUTOINCREMENT,\n    telegram_user_id INTEGER NOT NULL,\n    created_at TEXT NOT NULL,\n    updated_at TEXT NOT NULL,\n    FOREIGN KEY (telegram_user_id) REFERENCES user_profiles(telegram_user_id) ON DELETE CASCADE\n);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON conversation_sessions(telegram_user_id);

-- 5. Conversation Messages (Phase 4: Recent Turns)
CREATE TABLE IF NOT EXISTS conversation_messages (\n    id INTEGER PRIMARY KEY AUTOINCREMENT,\n    session_id INTEGER NOT NULL,\n    telegram_user_id INTEGER NOT NULL,\n    role TEXT NOT NULL,\n    content TEXT NOT NULL,\n    created_at TEXT NOT NULL,\n    FOREIGN KEY (session_id) REFERENCES conversation_sessions(id) ON DELETE CASCADE,\n    FOREIGN KEY (telegram_user_id) REFERENCES user_profiles(telegram_user_id) ON DELETE CASCADE\n);

CREATE INDEX IF NOT EXISTS idx_messages_session ON conversation_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_user ON conversation_messages(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON conversation_messages(created_at);

-- 6. User Watchlist (Phase 8)
CREATE TABLE IF NOT EXISTS user_watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    added_at TEXT NOT NULL,
    notes TEXT,
    UNIQUE(telegram_user_id, symbol),
    FOREIGN KEY (telegram_user_id) REFERENCES user_profiles(telegram_user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_watchlist_user ON user_watchlist(telegram_user_id);
