import sqlite3
import threading
from contextlib import contextmanager

from .config import DATA_DIR, DB_PATH

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    key TEXT PRIMARY KEY,
    num INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'Medium',
    status TEXT NOT NULL DEFAULT 'Open',
    reporter TEXT NOT NULL DEFAULT 'demo-user',
    resolution TEXT,
    scenario_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_key TEXT NOT NULL REFERENCES tickets(key),
    author TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS log_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    service TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    scenario_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON log_lines(ts);
CREATE TABLE IF NOT EXISTS pulls (
    id TEXT PRIMARY KEY,
    num INTEGER NOT NULL,
    case_id INTEGER,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    edits_json TEXT NOT NULL,
    diff TEXT NOT NULL,
    files_changed_json TEXT NOT NULL,
    test_output TEXT NOT NULL,
    tests_passed INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open',
    created_at TEXT NOT NULL
);
"""


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def connect():
    """Serialized connection: the demo has tiny load, so one writer at a time is fine."""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def rows(cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]
