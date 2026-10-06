import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
SEED_DIR = Path(os.environ.get("SEED_DIR", "/seed"))
DB_PATH = DATA_DIR / "controlplane.db"
DEMO_SERVICE_URL = os.environ.get("DEMO_SERVICE_URL", "http://demo-service:8000").rstrip("/")
MAX_TASK_ATTEMPTS = int(os.environ.get("MAX_TASK_ATTEMPTS", "2"))
TASK_LEASE_SECONDS = int(os.environ.get("TASK_LEASE_SECONDS", "1200"))

# Which LLM the agent uses for new tasks until someone switches it in the UI: "real" or "mock".
DEFAULT_LLM_MODE = os.environ.get("DEFAULT_LLM_MODE", "real")
LLM_MODEL = os.environ.get("LLM_MODEL", "unknown")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
