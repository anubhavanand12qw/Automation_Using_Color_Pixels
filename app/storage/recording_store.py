from __future__ import annotations

import json
import logging
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.models import ScreenResolution, new_id
from app.utils.paths import RECORDINGS_DIR, ensure_project_dirs

logger = logging.getLogger("pixel_automation.recording_store")


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip()).strip("_")
    return cleaned or "recording"


class RecordingStore:
    def __init__(self, directory: Path = RECORDINGS_DIR) -> None:
        self.directory = directory
        ensure_project_dirs()

    def list_recordings(self) -> list[dict[str, Any]]:
        self.directory.mkdir(parents=True, exist_ok=True)
        recordings: list[dict[str, Any]] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                data = self.load_recording(path.name)
                recordings.append(
                    {
                        "file": path.name,
                        "name": data.get("name", path.stem),
                        "created_at": data.get("created_at", ""),
                        "event_count": len(data.get("events", [])),
                    }
                )
            except Exception as exc:
                logger.warning("Skipping invalid recording %s: %s", path.name, exc)
        return recordings

    def load_recording(self, filename: str) -> dict[str, Any]:
        path = self._resolve(filename)
        if not path.exists():
            raise FileNotFoundError(f"Recording file not found: {filename} at {path}")
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data.get("events"), list):
            raise ValueError(f"Recording file has no events list: {filename}")
        return data

    def recording_path(self, filename: str) -> Path:
        return self._resolve(filename)

    def recording_exists(self, filename: str) -> bool:
        return bool(filename) and self._resolve(filename).exists()

    def delete_recording(self, filename: str) -> Path:
        path = self._resolve(filename)
        if not path.exists():
            raise FileNotFoundError(f"Recording file not found: {filename} at {path}")
        path.unlink()
        logger.info("Deleted recording %s", path.name)
        return path

    def save_recording(
        self,
        name: str,
        events: list[dict[str, Any]],
        screen_resolution: ScreenResolution,
    ) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
        base = safe_filename(name)
        filename = f"{base}_{timestamp}.json"
        path = self.directory / filename
        counter = 1
        while path.exists():
            path = self.directory / f"{base}_{timestamp}_{counter}.json"
            counter += 1

        payload = {
            "recording_id": new_id("rec"),
            "name": name.strip() or base,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "screen_resolution": screen_resolution.to_dict(),
            "events": events,
        }
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.directory, delete=False
        ) as tmp:
            json.dump(payload, tmp, indent=2)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)
        if not path.exists():
            raise FileNotFoundError(f"Recording save failed; file was not created at {path}")
        logger.info("Saved recording %s with %s events", path.name, len(events))
        return path

    def _resolve(self, filename: str) -> Path:
        path = self.directory / Path(filename).name
        return path
