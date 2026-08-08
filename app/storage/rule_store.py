from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from app.core.models import AutomationRule
from app.utils.paths import RULES_FILE, ensure_project_dirs

logger = logging.getLogger("pixel_automation.rule_store")


class RuleStore:
    def __init__(self, path: Path = RULES_FILE) -> None:
        self.path = path
        ensure_project_dirs()

    def load_rules(self) -> list[AutomationRule]:
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
            rules_data = payload.get("rules", payload if isinstance(payload, list) else [])
            rules = [AutomationRule.from_dict(item) for item in rules_data]
            logger.info("Loaded %s rules", len(rules))
            return rules
        except Exception:
            logger.exception("Failed to load rules from %s", self.path)
            return []

    def save_rules(self, rules: list[AutomationRule]) -> None:
        ensure_project_dirs()
        payload = {
            "version": 1,
            "rules": [rule.to_dict() for rule in rules],
        }
        self._atomic_write(payload)
        logger.info("Saved %s rules", len(rules))

    def _atomic_write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as tmp:
            json.dump(payload, tmp, indent=2)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.path)

