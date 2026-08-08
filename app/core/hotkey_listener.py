from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("pixel_automation.hotkeys")

MODIFIER_ALIASES = {
    "cmd": "cmd",
    "command": "cmd",
    "meta": "cmd",
    "ctrl": "ctrl",
    "control": "ctrl",
    "shift": "shift",
    "option": "alt",
    "alt": "alt",
    "fn": "fn",
}

PYNPUT_MODIFIER_NAMES = {
    "cmd": "cmd",
    "ctrl": "ctrl",
    "shift": "shift",
    "alt": "alt",
}

SPECIAL_KEY_ALIASES = {
    "return": "enter",
    "escape": "esc",
}

SPECIAL_KEYS = {
    "enter",
    "esc",
    "space",
    "tab",
    "backspace",
    "delete",
    "up",
    "down",
    "left",
    "right",
    "home",
    "end",
    "page_up",
    "page_down",
}


@dataclass(frozen=True)
class ParsedHotkey:
    modifiers: tuple[str, ...]
    key: str

    def normalized(self) -> str:
        return "+".join([*self.modifiers, self.key])


def parse_hotkey(value: str) -> ParsedHotkey:
    if not value or not value.strip():
        raise ValueError("Hotkey cannot be empty.")
    raw_parts = [part.strip().lower() for part in value.replace(" ", "").split("+") if part.strip()]
    if not raw_parts:
        raise ValueError("Hotkey cannot be empty.")

    modifiers: list[str] = []
    key: str | None = None
    for part in raw_parts:
        normalized_modifier = MODIFIER_ALIASES.get(part)
        if normalized_modifier:
            if normalized_modifier not in modifiers:
                modifiers.append(normalized_modifier)
            continue
        part = SPECIAL_KEY_ALIASES.get(part, part)
        if key is not None:
            raise ValueError(f"Hotkey must contain only one non-modifier key: {value}")
        key = part

    if key is None:
        raise ValueError("Hotkey must include a non-modifier key.")
    is_function_key = key.startswith("f") and key[1:].isdigit()
    is_special_key = key in SPECIAL_KEYS
    if len(key) != 1 and not is_function_key and not is_special_key:
        raise ValueError(f"Unsupported key '{key}'. Use a single character or function key.")
    return ParsedHotkey(tuple(modifiers), key)


def to_pynput_hotkey(value: str) -> str:
    parsed = parse_hotkey(value)
    parts = [f"<{PYNPUT_MODIFIER_NAMES[m]}>" for m in parsed.modifiers if m in PYNPUT_MODIFIER_NAMES]
    parts.append(parsed.key)
    return "+".join(parts)


class AppHotkeyListener:
    def __init__(
        self,
        on_capture: Callable[[], None],
        on_offset_reference: Callable[[], None],
        on_offset_target: Callable[[], None],
        on_start_automation: Callable[[], None],
        on_start_recording: Callable[[], None],
        on_stop_recording: Callable[[], None],
        on_emergency_stop: Callable[[], None],
    ) -> None:
        self.on_capture = on_capture
        self.on_offset_reference = on_offset_reference
        self.on_offset_target = on_offset_target
        self.on_start_automation = on_start_automation
        self.on_start_recording = on_start_recording
        self.on_stop_recording = on_stop_recording
        self.on_emergency_stop = on_emergency_stop
        self._listener = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._listener is not None:
                return
            try:
                from pynput.keyboard import GlobalHotKeys

                self._listener = GlobalHotKeys(
                    {
                        "<shift>+c": self.on_capture,
                        "<shift>+o": self.on_offset_reference,
                        "<shift>+l": self.on_offset_target,
                        "<shift>+<delete>": self.on_start_automation,
                        "<shift>+<backspace>": self.on_start_automation,
                        "<shift>+r": self.on_start_recording,
                        "<shift>+s": self.on_stop_recording,
                        "<shift>+<esc>": self.on_emergency_stop,
                    }
                )
                self._listener.start()
                logger.info(
                    "Global hotkeys registered: Shift+C capture, Shift+O offset reference, Shift+L offset target, Shift+Delete start automation, Shift+R start recording, Shift+S stop recording, Shift+Esc emergency stop"
                )
            except Exception:
                logger.exception("Failed to start global hotkey listener")
                raise

    def stop(self) -> None:
        with self._lock:
            if self._listener is None:
                return
            try:
                self._listener.stop()
            finally:
                self._listener = None
                logger.info("Global hotkey listener stopped")
