CREATE TABLE IF NOT EXISTS schema_version(version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO schema_version VALUES(1);
CREATE TABLE IF NOT EXISTS messages (
 id INTEGER PRIMARY KEY, account_id TEXT NOT NULL, group_id TEXT NOT NULL,
 message_id TEXT NOT NULL, source TEXT NOT NULL, sent_at TEXT NOT NULL,
 payload TEXT NOT NULL, text TEXT NOT NULL, fingerprint TEXT,
 state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt REAL NOT NULL DEFAULT 0, error TEXT, extracted TEXT,
 event_id TEXT, received_at TEXT NOT NULL, recalled INTEGER NOT NULL DEFAULT 0,
 UNIQUE(account_id,group_id,message_id));
CREATE INDEX IF NOT EXISTS queue_index ON messages(state,next_attempt);
CREATE TABLE IF NOT EXISTS events (
 id TEXT PRIMARY KEY, group_id TEXT NOT NULL, account_id TEXT NOT NULL,
 data TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 locked TEXT NOT NULL DEFAULT '[]', confirmed INTEGER NOT NULL DEFAULT 0,
 ignored INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_active_scope ON events(group_id,account_id,updated_at DESC) WHERE ignored=0;
CREATE TABLE IF NOT EXISTS versions (
 id INTEGER PRIMARY KEY, event_id TEXT NOT NULL, version INTEGER NOT NULL,
 data TEXT NOT NULL, reason TEXT NOT NULL, message_id INTEGER, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS messages_event_id ON messages(event_id);
CREATE INDEX IF NOT EXISTS versions_event_version ON versions(event_id,version);
CREATE TABLE IF NOT EXISTS runtime(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS budget(day TEXT PRIMARY KEY,calls INTEGER NOT NULL);
