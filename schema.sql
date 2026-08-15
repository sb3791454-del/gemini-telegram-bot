-- Sultan Assistant Database Schema (Cloudflare D1)

-- 1. User Profiles
CREATE TABLE IF NOT EXISTS user_profiles (
    telegram_user_id INTEGER PRIMARY KEY,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    display_name TEXT,
    username TEXT,
    preferences_json TEXT NOT NULL DEFAULT '{}'
);

-- 2. Long-Term Conversation Memories (Phase 3)
CREATE TABLE IF NOT EXISTS conversation_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    memory_type TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (telegram_user_id) REFERENCES user_profiles(telegram_user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memories_user_id ON conversation_memories(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_memories_type ON conversation_memories(memory_type);

-- 3. Assistant Settings (Persistent User Settings & Active Session Pointer)
CREATE TABLE IF NOT EXISTS assistant_settings (
    telegram_user_id INTEGER PRIMARY KEY,
    settings_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (telegram_user_id) REFERENCES user_profiles(telegram_user_id) ON DELETE CASCADE
);

-- 4. Conversation Sessions (Phase 4: Session History)
CREATE TABLE IF NOT EXISTS conversation_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (telegram_user_id) REFERENCES user_profiles(telegram_user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON conversation_sessions(telegram_user_id);

-- 5. Conversation Messages (Phase 4: Recent Turns)
CREATE TABLE IF NOT EXISTS conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    telegram_user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES conversation_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (telegram_user_id) REFERENCES user_profiles(telegram_user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON conversation_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_user ON conversation_messages(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON conversation_messages(created_at);
