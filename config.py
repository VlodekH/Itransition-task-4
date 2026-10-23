"""Local configuration; secrets are read from the environment or task-04/.env."""
import os
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent
env_file = TASK_DIR / ".env"
if env_file.is_file():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

DATA_DIR = TASK_DIR / "data"
RESULTS_DIR = TASK_DIR / "results"
DB_PATH = Path(os.environ.get("TASK4_STORE_DB_PATH", "").strip() or RESULTS_DIR / "stores.sqlite")
