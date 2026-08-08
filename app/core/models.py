from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.core.playback import MAX_PLAYBACK_SPEED, MIN_PLAYBACK_SPEED


MatchType = Literal["match", "unmatch"]
ActionType = Literal["recording", "hotkey", "mouse_left_click", "mouse_right_click"]
TriggerMode = Literal["repeat", "once", "edge"]
LogicalOperator = Literal["AND", "OR"]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@dataclass
class ScreenResolution:
    width: int
    height: int
    scale_factor: float = 1.0
    display_count: int = 1
    primary_display: str = "Primary"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ScreenResolution":
        data = data or {}
        return cls(
            width=int(data.get("width", 0)),
            height=int(data.get("height", 0)),
            scale_factor=float(data.get("scale_factor", 1.0)),
            display_count=int(data.get("display_count", 1)),
            primary_display=str(data.get("primary_display", "Primary")),
        )


@dataclass
class PixelCondition:
    condition_id: str = field(default_factory=lambda: new_id("cond"))
    x: int = 0
    y: int = 0
    rgb: tuple[int, int, int] = (0, 0, 0)
    match_type: MatchType = "match"
    tolerance: int = 10
    use_cursor_position: bool = False
    captured_at: str | None = None
    screen_resolution: ScreenResolution | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["rgb"] = list(self.rgb)
        data["screen_resolution"] = (
            self.screen_resolution.to_dict() if self.screen_resolution else None
        )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PixelCondition":
        rgb = data.get("rgb", [0, 0, 0])
        return cls(
            condition_id=str(data.get("condition_id") or new_id("cond")),
            x=int(data.get("x", 0)),
            y=int(data.get("y", 0)),
            rgb=(int(rgb[0]), int(rgb[1]), int(rgb[2])),
            match_type="unmatch" if data.get("match_type") == "unmatch" else "match",
            tolerance=int(data.get("tolerance", 10)),
            use_cursor_position=bool(data.get("use_cursor_position", False)),
            captured_at=data.get("captured_at"),
            screen_resolution=ScreenResolution.from_dict(data["screen_resolution"])
            if data.get("screen_resolution")
            else None,
        )


@dataclass
class ConditionExpressionItem:
    condition: PixelCondition | None = None
    operator: LogicalOperator | None = None

    def to_json_item(self) -> dict[str, Any]:
        if self.operator:
            return {"operator": self.operator}
        if self.condition:
            return self.condition.to_dict()
        raise ValueError("Expression item must contain a condition or operator.")


@dataclass
class ActionConfig:
    action_type: ActionType = "hotkey"
    recording_file: str = ""
    hotkey: str = "shift+4"
    recording_relative_to_pointer: bool = False
    playback_speed: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ActionConfig":
        data = data or {}
        action_type = str(data.get("action_type", "hotkey"))
        if action_type not in {
            "recording",
            "hotkey",
            "mouse_left_click",
            "mouse_right_click",
        }:
            action_type = "recording" if action_type == "recorded_sequence" else "hotkey"
        return cls(
            action_type=action_type,  # type: ignore[arg-type]
            recording_file=str(data.get("recording_file", "")),
            hotkey=str(data.get("hotkey", "shift+4")),
            recording_relative_to_pointer=bool(data.get("recording_relative_to_pointer", False)),
            playback_speed=max(
                MIN_PLAYBACK_SPEED,
                min(MAX_PLAYBACK_SPEED, float(data.get("playback_speed", 1.0))),
            ),
        )


@dataclass
class AutomationRule:
    rule_id: str = field(default_factory=lambda: new_id("rule"))
    rule_name: str = "New Rule"
    conditions: list[dict[str, Any]] = field(default_factory=list)
    action: ActionConfig = field(default_factory=ActionConfig)
    human_like: bool = True
    click_randomness_px: int = 0
    polling_interval_ms: int = 100
    cooldown_seconds: float = 2.0
    trigger_mode: TriggerMode = "repeat"
    enabled: bool = True
    status: str = "Idle"

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "conditions": self.conditions,
            "action": self.action.to_dict(),
            "human_like": self.human_like,
            "click_randomness_px": self.click_randomness_px,
            "polling_interval_ms": self.polling_interval_ms,
            "cooldown_seconds": self.cooldown_seconds,
            "trigger_mode": self.trigger_mode,
            "enabled": self.enabled,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AutomationRule":
        return cls(
            rule_id=str(data.get("rule_id") or new_id("rule")),
            rule_name=str(data.get("rule_name", "New Rule")),
            conditions=list(data.get("conditions", [])),
            action=ActionConfig.from_dict(data.get("action")),
            human_like=bool(data.get("human_like", True)),
            click_randomness_px=int(data.get("click_randomness_px", 0)),
            polling_interval_ms=int(data.get("polling_interval_ms", 100)),
            cooldown_seconds=float(data.get("cooldown_seconds", 2.0)),
            trigger_mode=data.get("trigger_mode", "repeat")
            if data.get("trigger_mode") in {"repeat", "once", "edge"}
            else "repeat",
            enabled=bool(data.get("enabled", True)),
            status=str(data.get("status", "Idle")),
        )

    def add_condition(self, condition: PixelCondition, operator: LogicalOperator | None = None) -> None:
        if self.conditions and operator:
            self.conditions.append({"operator": operator})
        self.conditions.append(condition.to_dict())
