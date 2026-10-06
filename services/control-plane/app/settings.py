"""Runtime settings that can be changed from the UI (stored in SQLite)."""
from .config import DEFAULT_LLM_MODE, LLM_BASE_URL, LLM_MODEL
from .util import ApiError

LLM_MODES = ("real", "mock")


def get(conn, key: str, default: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def put(conn, key: str, value: str) -> None:
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, value))


def llm_mode(conn) -> str:
    mode = get(conn, "llm_mode", DEFAULT_LLM_MODE)
    return mode if mode in LLM_MODES else "real"


def set_llm_mode(conn, mode: str) -> None:
    if mode not in LLM_MODES:
        raise ApiError(400, f"mode must be one of {list(LLM_MODES)}")
    put(conn, "llm_mode", mode)


def llm_options() -> list[dict]:
    provider = ("Local model via Ollama" if "ollama" in LLM_BASE_URL else
                "Scripted mock LLM" if "mock-llm" in LLM_BASE_URL else "Hosted OpenAI-compatible API")
    return [
        {"id": "real", "label": "Real LLM", "model": LLM_MODEL, "provider": provider},
        {"id": "mock", "label": "Mock LLM", "model": "scripted-mock",
         "provider": "Scripted responses for the demo scenarios, instant"},
    ]
