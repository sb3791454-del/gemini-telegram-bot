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

-- 2. Conversation Memories
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

-- 3. Assistant Settings
CREATE TABLE IF NOT EXISTS assistant_settings (
    telegram_user_id INTEGER PRIMARY KEY,
    settings_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (telegram_user_id) REFERENCES user_profiles(telegram_user_id) ON DELETE CASCADE
);
