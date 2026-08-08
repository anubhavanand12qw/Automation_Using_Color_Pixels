from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = PROJECT_ROOT / "app"
RECORDINGS_DIR = PROJECT_ROOT / "recordings"
RULES_DIR = PROJECT_ROOT / "rules"
LOGS_DIR = PROJECT_ROOT / "logs"
CONFIG_DIR = PROJECT_ROOT / "config"
RULES_FILE = RULES_DIR / "rules.json"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = LOGS_DIR / "app.log"


def ensure_project_dirs() -> None:
    for path in (RECORDINGS_DIR, RULES_DIR, LOGS_DIR, CONFIG_DIR):
        path.mkdir(parents=True, exist_ok=True)

