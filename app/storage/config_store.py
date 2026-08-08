from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from app.utils.paths import CONFIG_FILE, ensure_project_dirs


DEFAULT_CONFIG: dict[str, Any] = {
    "capture_hotkey": "shift+c",
    "offset_reference_hotkey": "shift+o",
    "offset_target_hotkey": "shift+l",
    "start_automation_hotkey": "shift+delete",
    "start_recording_hotkey": "shift+r",
    "stop_recording_hotkey": "shift+s",
    "emergency_stop_hotkey": "shift+esc",
    "default_polling_interval_ms": 100,
    "default_cooldown_seconds": 2.0,
}


class ConfigStore:
    def __init__(self, path: Path = CONFIG_FILE) -> None:
        self.path = path
        ensure_project_dirs()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            self.save(DEFAULT_CONFIG)
            return dict(DEFAULT_CONFIG)
        try:
            with self.path.open("r", encoding="utf-8") as file:
                data = json.load(file)
            return {**DEFAULT_CONFIG, **data}
        except Exception:
            return dict(DEFAULT_CONFIG)

    def save(self, config: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as tmp:
            json.dump({**DEFAULT_CONFIG, **config}, tmp, indent=2)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.path)
