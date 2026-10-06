import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
SEED_DIR = Path(os.environ.get("SEED_DIR", "/seed"))
DB_PATH = DATA_DIR / "demo.db"
REPO_DIR = SEED_DIR / "demo-repo"
TEST_TIMEOUT_SECONDS = int(os.environ.get("TEST_TIMEOUT_SECONDS", "60"))
