import json
import sqlite3
import threading
from contextlib import contextmanager

from .config import DATA_DIR, DB_PATH
from .util import now_iso

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_key TEXT NOT NULL,
    ticket_title TEXT NOT NULL,          -- display cache only; Jira owns ticket content
    scenario_id TEXT,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    type TEXT NOT NULL,                  -- INVESTIGATE | DEVELOP
    status TEXT NOT NULL,                -- PENDING | CLAIMED | DONE | FAILED | CANCELLED
    attempts INTEGER NOT NULL DEFAULT 0,
    claimed_by TEXT,
    lease_expires_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS investigations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    version INTEGER NOT NULL,
    summary TEXT NOT NULL,
    root_cause TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    proposed_fix TEXT NOT NULL,
    files_to_change_json TEXT NOT NULL,
    confidence TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    investigation_id INTEGER,
    decision TEXT NOT NULL,              -- approve | request_changes | reject
    comment TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS case_prs (
    case_id INTEGER NOT NULL REFERENCES cases(id),
    pr_id TEXT NOT NULL,
    summary TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (case_id, pr_id)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES cases(id),
    task_id INTEGER,
    kind TEXT NOT NULL,                  -- state_change | llm_message | tool_call | tool_result | error | info
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_case ON events(case_id, id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, created_at);
"""


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def connect():
    """One connection at a time. Load is tiny and this keeps task claiming trivially atomic."""
    with _lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def rows(cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]


def add_event(conn, case_id: int, kind: str, payload: dict, task_id: int | None = None) -> None:
    conn.execute("INSERT INTO events (case_id, task_id, kind, payload_json, created_at) VALUES (?,?,?,?,?)",
                 (case_id, task_id, kind, json.dumps(payload), now_iso()))
