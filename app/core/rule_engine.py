from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from app.core.color_matcher import condition_passes
from app.core.models import AutomationRule, PixelCondition

logger = logging.getLogger("pixel_automation.rule_engine")


PixelSampler = Callable[[int, int], tuple[int, int, int]]
CursorPositionProvider = Callable[[], tuple[int, int]]


def evaluate_rule_conditions(
    rule: AutomationRule,
    sample_pixel: PixelSampler,
    get_cursor_position: CursorPositionProvider | None = None,
) -> bool:
    """Evaluate rule conditions left-to-right.

    The JSON shape intentionally leaves room for nested condition groups later.
    Version 1 supports condition/operator/condition in sequence.
    """

    if not rule.conditions:
        return False

    result: bool | None = None
    pending_operator = "AND"

    for item in rule.conditions:
        if "operator" in item:
            operator = str(item["operator"]).upper()
            if operator not in {"AND", "OR"}:
                raise ValueError(f"Unsupported logical operator: {operator}")
            pending_operator = operator
            continue

        condition = PixelCondition.from_dict(item)
        sample_x, sample_y = condition.x, condition.y
        if condition.use_cursor_position:
            if get_cursor_position is None:
                raise ValueError("Cursor-position condition requires a cursor position provider.")
            cursor_x, cursor_y = get_cursor_position()
            sample_x = cursor_x + condition.x
            sample_y = cursor_y + condition.y
        try:
            actual_rgb = sample_pixel(sample_x, sample_y)
        except ValueError:
            if condition.use_cursor_position:
                condition_result = False
            else:
                raise
        else:
            condition_result = condition_passes(condition, actual_rgb)

        if result is None:
            result = condition_result
        elif pending_operator == "AND":
            result = result and condition_result
        elif pending_operator == "OR":
            result = result or condition_result
        else:
            raise ValueError(f"Unsupported logical operator: {pending_operator}")
        pending_operator = "AND"

    return bool(result)


def rule_uses_cursor_position(rule: AutomationRule) -> bool:
    for item in rule.conditions:
        if "operator" in item:
            continue
        if PixelCondition.from_dict(item).use_cursor_position:
            return True
    return False


@dataclass
class RuleRuntimeState:
    last_triggered_at: float = 0.0
    last_condition_result: bool = False
    triggered_once: bool = False

    def should_trigger(self, rule: AutomationRule, condition_result: bool, now: float | None = None) -> bool:
        current_time = time.monotonic() if now is None else now
        if not condition_result:
            self.last_condition_result = False
            return False

        if rule.trigger_mode == "once" and self.triggered_once:
            self.last_condition_result = True
            return False

        if rule.trigger_mode == "edge" and self.last_condition_result:
            return False

        elapsed = current_time - self.last_triggered_at
        if elapsed < max(0.0, rule.cooldown_seconds):
            self.last_condition_result = True
            return False

        self.last_triggered_at = current_time
        self.last_condition_result = True
        self.triggered_once = True
        return True
