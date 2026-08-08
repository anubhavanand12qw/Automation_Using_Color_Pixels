from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

from app.core.hotkey_listener import SPECIAL_KEY_ALIASES, SPECIAL_KEYS, ParsedHotkey, parse_hotkey
from app.core.humanizer import Humanizer
from app.core.models import ActionConfig
from app.core.mouse_activity import MouseActivity, MouseActivityNotifier
from app.core.playback import PlaybackEngine, PlaybackStopToken, configure_pyautogui_fast
from app.storage.recording_store import RecordingStore

logger = logging.getLogger("pixel_automation.action_executor")


@dataclass(frozen=True)
class KeyboardActionInput:
    kind: Literal["hotkey", "special_key", "text"]
    value: str
    parsed_hotkey: ParsedHotkey | None = None


def classify_keyboard_action(value: str) -> KeyboardActionInput:
    text = value.strip()
    if not text:
        raise ValueError("Keyboard action cannot be empty.")

    if "+" in text:
        return KeyboardActionInput("hotkey", text, parse_hotkey(text))

    normalized = SPECIAL_KEY_ALIASES.get(text.lower(), text.lower())
    is_function_key = normalized.startswith("f") and normalized[1:].isdigit()
    if normalized in SPECIAL_KEYS or is_function_key:
        return KeyboardActionInput("special_key", normalized)

    return KeyboardActionInput("text", text)


class ActionExecutor:
    def __init__(
        self,
        recording_store: RecordingStore | None = None,
        automation_lock: threading.RLock | None = None,
    ) -> None:
        self.recording_store = recording_store or RecordingStore()
        self.recording_lock = automation_lock or threading.RLock()
        self.mouse_operation_lock = threading.RLock()
        self.mouse_activity = MouseActivityNotifier()
        self.stop_token = PlaybackStopToken()
        self.playback_engine = PlaybackEngine(
            mouse_operation_lock=self.mouse_operation_lock,
            on_mouse_activity=self.mouse_activity.notify,
        )
        self.humanizer = Humanizer()

    @property
    def mouse_activity_version(self) -> int:
        return self.mouse_activity.version

    def wait_for_mouse_activity(
        self,
        last_seen_version: int,
        timeout: float,
        stop_event: threading.Event,
    ) -> None:
        self.mouse_activity.wait_for_change(last_seen_version, timeout, stop_event)

    def mouse_activity_events_since(self, last_seen_version: int) -> list[MouseActivity]:
        return self.mouse_activity.events_since(last_seen_version)

    def latest_mouse_activity_since(self, last_seen_version: int) -> MouseActivity | None:
        return self.mouse_activity.latest_event_since(last_seen_version)

    def set_fast_pointer_watch_enabled(self, enabled: bool) -> None:
        self.playback_engine.mouse_activity_yield_seconds = 0.0015 if enabled else 0.0

    def execute(
        self,
        action: ActionConfig,
        human_like: bool,
        click_randomness_px: int = 0,
        trigger_position: tuple[int, int] | None = None,
    ) -> None:
        if self.stop_token.is_stopped():
            return

        logger.info("Action execution start type=%s", action.action_type)
        if action.action_type == "recording":
            with self.recording_lock:
                if self.stop_token.is_stopped():
                    return
                self._execute_recording(
                    action.recording_file,
                    human_like,
                    click_randomness_px,
                    trigger_position if action.recording_relative_to_pointer else None,
                    action.playback_speed,
                )
        elif action.action_type == "hotkey":
            self._execute_keyboard_action(action.hotkey, human_like)
        elif action.action_type == "mouse_left_click":
            self._execute_mouse_click("left", human_like, click_randomness_px, trigger_position)
        elif action.action_type == "mouse_right_click":
            self._execute_mouse_click("right", human_like, click_randomness_px, trigger_position)
        else:
            raise ValueError(f"Unsupported action type: {action.action_type}")
        logger.info("Action execution complete type=%s", action.action_type)

    def _execute_recording(
        self,
        recording_file: str,
        human_like: bool,
        click_randomness_px: int,
        relative_origin: tuple[int, int] | None,
        playback_speed: float,
    ) -> None:
        if not recording_file:
            raise ValueError("No recording selected.")
        data = self.recording_store.load_recording(recording_file)
        self.playback_engine.play_events(
            data.get("events", []),
            human_like=human_like,
            click_randomness_px=click_randomness_px,
            relative_origin=relative_origin,
            playback_speed=playback_speed,
            stop_token=self.stop_token,
        )

    def _execute_keyboard_action(self, value: str, human_like: bool) -> None:
        action = classify_keyboard_action(value)
        if action.kind == "hotkey":
            self._execute_hotkey(action.parsed_hotkey, human_like)
        elif action.kind == "special_key":
            self._press_single_key(action.value, human_like)
        else:
            self._type_text(action.value, human_like)

    def _execute_hotkey(self, parsed: ParsedHotkey | None, human_like: bool) -> None:
        import pyautogui

        if parsed is None:
            raise ValueError("Parsed hotkey is required.")

        configure_pyautogui_fast(pyautogui)
        pressed: list[Any] = []
        modifier_map = {
            "shift": "shift",
            "cmd": "command",
            "ctrl": "ctrl",
            "alt": "option",
            "fn": "fn",
        }
        try:
            for modifier in parsed.modifiers:
                key = modifier_map.get(modifier)
                if key is None:
                    continue
                pyautogui.keyDown(key)
                pressed.append(key)
                if human_like:
                    self.stop_token.wait(self.humanizer.key_interval())

            main_key = _key_from_name(parsed.key)
            pyautogui.keyDown(main_key)
            pressed.append(main_key)
            self.stop_token.wait(
                self.humanizer.key_interval(0.03, 0.09) if human_like else 0.03
            )
        finally:
            for key in reversed(pressed):
                try:
                    pyautogui.keyUp(key)
                except Exception:
                    logger.debug("Failed to release key %s", key, exc_info=True)
                if human_like:
                    self.stop_token.wait(self.humanizer.key_interval(0.02, 0.08))

    def _press_single_key(self, key_name: str, human_like: bool) -> None:
        import pyautogui

        configure_pyautogui_fast(pyautogui)
        key = _key_from_name(key_name)
        try:
            if human_like:
                self.stop_token.wait(self.humanizer.key_interval(0.03, 0.11))
            pyautogui.keyDown(key)
            self.stop_token.wait(
                self.humanizer.key_interval(0.03, 0.09) if human_like else 0.03
            )
        finally:
            pyautogui.keyUp(key)

    def _type_text(self, text: str, human_like: bool) -> None:
        import pyautogui

        configure_pyautogui_fast(pyautogui)
        for character in text:
            if self.stop_token.is_stopped():
                return
            try:
                if human_like:
                    self.stop_token.wait(self.humanizer.key_interval(0.035, 0.14))
                pyautogui.write(character, interval=0)
                self.stop_token.wait(
                    self.humanizer.key_interval(0.025, 0.08) if human_like else 0.015
                )
            except Exception:
                logger.exception("Failed while typing text action")
                raise

    def _execute_mouse_click(
        self,
        button: str,
        human_like: bool,
        click_randomness_px: int,
        target_position: tuple[int, int] | None = None,
    ) -> None:
        if target_position is None:
            import pyautogui

            configure_pyautogui_fast(pyautogui)
            current = pyautogui.position()
            x, y = int(current.x), int(current.y)
        else:
            x, y = int(target_position[0]), int(target_position[1])
        press_duration = self.humanizer.click_press_duration() if human_like else 0.001
        if human_like:
            self.stop_token.wait(self.humanizer.key_interval(0.01, 0.04))

        with self.playback_engine.priority_mouse_operation():
            if not self._post_native_click(x, y, button, press_duration):
                import pyautogui

                configure_pyautogui_fast(pyautogui)
                pyautogui.moveTo(x, y, duration=0)
                pyautogui.mouseDown(x=x, y=y, button=button)
                self.stop_token.wait(press_duration)
                pyautogui.mouseUp(x=x, y=y, button=button)

    def _post_native_click(self, x: int, y: int, button: str, press_duration: float) -> bool:
        if sys.platform != "darwin":
            return False
        try:
            from Quartz import (  # type: ignore
                CGEventCreateMouseEvent,
                CGEventPost,
                kCGEventLeftMouseDown,
                kCGEventLeftMouseUp,
                kCGEventRightMouseDown,
                kCGEventRightMouseUp,
                kCGHIDEventTap,
                kCGMouseButtonLeft,
                kCGMouseButtonRight,
            )
        except Exception:
            return False

        if button == "right":
            mouse_button = kCGMouseButtonRight
            down_event = kCGEventRightMouseDown
            up_event = kCGEventRightMouseUp
        else:
            mouse_button = kCGMouseButtonLeft
            down_event = kCGEventLeftMouseDown
            up_event = kCGEventLeftMouseUp

        try:
            point = (int(x), int(y))
            CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(None, down_event, point, mouse_button))
            time.sleep(max(0.0, float(press_duration)))
            CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(None, up_event, point, mouse_button))
            return True
        except Exception:
            logger.debug("Native Quartz click failed; falling back to pyautogui", exc_info=True)
            return False

    def emergency_stop(self) -> None:
        self.stop_token.stop()
        try:
            self.playback_engine.release_all()
        except Exception:
            logger.exception("Emergency cleanup failed while releasing input state")
        logger.warning("Emergency stop requested; playback token stopped and keys released")

    def reset_stop_token(self) -> None:
        self.stop_token = PlaybackStopToken()


def _key_from_name(name: str) -> str:
    normalized = SPECIAL_KEY_ALIASES.get(str(name).lower(), str(name).lower())
    key_aliases = {
        "cmd": "command",
        "command": "command",
        "ctrl": "ctrl",
        "control": "ctrl",
        "option": "option",
        "alt": "option",
        "return": "enter",
        "escape": "esc",
        "page_up": "pageup",
        "page_down": "pagedown",
        "pageup": "pageup",
        "pagedown": "pagedown",
        "up": "up",
        "down": "down",
        "left": "left",
        "right": "right",
        "backspace": "backspace",
        "delete": "delete",
        "space": "space",
        "tab": "tab",
        "esc": "esc",
    }
    key_name = key_aliases.get(normalized, normalized)
    pyautogui_special_keys = {
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
        "pageup",
        "pagedown",
    }
    if len(key_name) == 1 or key_name in pyautogui_special_keys or key_name.startswith("f"):
        return key_name
    raise ValueError(f"Unsupported key: {name}")
