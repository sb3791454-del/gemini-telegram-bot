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

-- 7. User Alerts (Phase 9: Deterministic Market Monitoring)
CREATE TABLE IF NOT EXISTS user_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    timeframe TEXT NOT NULL DEFAULT '1h',
    target_value REAL,
    direction TEXT,
    status TEXT NOT NULL DEFAULT 'ARMED',
    cooldown_minutes INTEGER NOT NULL DEFAULT 60,
    is_recurring INTEGER NOT NULL DEFAULT 0,
    user_capital REAL,
    user_risk_pct REAL,
    last_evaluated_at TEXT,
    last_triggered_at TEXT,
    last_state_payload TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (telegram_user_id) REFERENCES user_profiles(telegram_user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alerts_user ON user_alerts(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_alerts_status_symbol ON user_alerts(status, symbol);
CREATE INDEX IF NOT EXISTS idx_alerts_active ON user_alerts(status) WHERE status IN ('ARMED', 'COOLDOWN');

-- 8. Alert Trigger History (Phase 9: Audit Trail)
CREATE TABLE IF NOT EXISTS alert_trigger_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL,
    telegram_user_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    trigger_price REAL NOT NULL,
    trigger_reason TEXT NOT NULL,
    setup_state TEXT,
    hard_sl_price REAL,
    tp1_price REAL,
    notification_status TEXT NOT NULL,
    delivered_at TEXT NOT NULL,
    FOREIGN KEY (alert_id) REFERENCES user_alerts(id) ON DELETE CASCADE,
    FOREIGN KEY (telegram_user_id) REFERENCES user_profiles(telegram_user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alert_history_user ON alert_trigger_history(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_alert_history_alert ON alert_trigger_history(alert_id);
CREATE INDEX IF NOT EXISTS idx_alert_history_created ON alert_trigger_history(delivered_at);
