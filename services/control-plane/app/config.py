import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
SEED_DIR = Path(os.environ.get("SEED_DIR", "/seed"))
DB_PATH = DATA_DIR / "controlplane.db"
DEMO_SERVICE_URL = os.environ.get("DEMO_SERVICE_URL", "http://demo-service:8000").rstrip("/")
MAX_TASK_ATTEMPTS = int(os.environ.get("MAX_TASK_ATTEMPTS", "2"))
TASK_LEASE_SECONDS = int(os.environ.get("TASK_LEASE_SECONDS", "1200"))
