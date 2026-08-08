from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable

from app.core.humanizer import Humanizer

logger = logging.getLogger("pixel_automation.playback")


class PlaybackStopToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def stop(self) -> None:
        self._event.set()

    def is_stopped(self) -> bool:
        return self._event.is_set()

    def wait(self, seconds: float) -> bool:
        return self._event.wait(max(0.0, seconds))


def _mouse_button(name: str):
    normalized = str(name).replace("Button.", "").lower()
    if normalized in {"right", "middle"}:
        return normalized
    return "left"


def _keyboard_key(name: str) -> str:
    normalized = str(name).replace("Key.", "").lower()
    aliases = {
        "cmd": "command",
        "command": "command",
        "ctrl": "ctrl",
        "control": "ctrl",
        "option": "option",
        "alt": "option",
        "esc": "esc",
        "escape": "esc",
        "space": "space",
        "shift": "shift",
        "enter": "enter",
        "return": "enter",
        "tab": "tab",
        "backspace": "backspace",
        "delete": "delete",
        "page_up": "pageup",
        "page_down": "pagedown",
        "pageup": "pageup",
        "pagedown": "pagedown",
    }
    return aliases.get(normalized, normalized)


MOUSE_POSITION_EVENT_TYPES = {
    "mouse_move",
    "mouse_press",
    "mouse_release",
    "mouse_scroll",
}

MIN_PLAYBACK_SPEED = 0.05
MAX_PLAYBACK_SPEED = 20.0
HUMAN_TIMING_EVENT_TYPES = {
    "mouse_press",
    "mouse_release",
    "key_press",
    "key_release",
}


def find_recording_mouse_origin(events: list[dict[str, Any]]) -> tuple[int, int] | None:
    for event in events:
        if event.get("type") in MOUSE_POSITION_EVENT_TYPES and "x" in event and "y" in event:
            return int(event["x"]), int(event["y"])
    return None


def relative_mouse_event(
    event: dict[str, Any],
    recorded_origin: tuple[int, int] | None,
    playback_origin: tuple[int, int] | None,
) -> dict[str, Any]:
    if (
        recorded_origin is None
        or playback_origin is None
        or event.get("type") not in MOUSE_POSITION_EVENT_TYPES
        or "x" not in event
        or "y" not in event
    ):
        return event
    adjusted = dict(event)
    adjusted["x"] = int(playback_origin[0]) + int(event["x"]) - int(recorded_origin[0])
    adjusted["y"] = int(playback_origin[1]) + int(event["y"]) - int(recorded_origin[1])
    return adjusted


class PlaybackEngine:
    def __init__(
        self,
        humanizer: Humanizer | None = None,
        mouse_operation_lock: threading.RLock | None = None,
        on_mouse_activity: Callable[[tuple[int, int] | None], None] | None = None,
    ) -> None:
        self.humanizer = humanizer or Humanizer()
        self.mouse_operation_lock = mouse_operation_lock or threading.RLock()
        self.on_mouse_activity = on_mouse_activity
        self.mouse_activity_yield_seconds = 0.0
        self._pressed_keys: list[Any] = []
        self._pressed_mouse_buttons: list[Any] = []
        self._active_click_positions: dict[str, tuple[int, int]] = {}
        self._priority_mouse_request = threading.Event()

    @contextmanager
    def priority_mouse_operation(self):
        while self._pressed_mouse_buttons:
            time.sleep(0.001)
        self._priority_mouse_request.set()
        self.mouse_operation_lock.acquire()
        try:
            yield
        finally:
            self.mouse_operation_lock.release()
            self._priority_mouse_request.clear()

    def play_events(
        self,
        events: list[dict[str, Any]],
        human_like: bool,
        click_randomness_px: int = 0,
        relative_origin: tuple[int, int] | None = None,
        playback_speed: float = 1.0,
        stop_token: PlaybackStopToken | None = None,
    ) -> None:
        import pyautogui

        stop_token = stop_token or PlaybackStopToken()
        speed = normalize_playback_speed(playback_speed)
        recorded_origin = find_recording_mouse_origin(events) if relative_origin else None
        configure_pyautogui_fast(pyautogui)
        logger.info(
            "Playback started with %s events human_like=%s relative_origin=%s speed=%sx",
            len(events),
            human_like,
            relative_origin,
            speed,
        )

        try:
            index = 0
            while index < len(events):
                event = relative_mouse_event(events[index], recorded_origin, relative_origin)
                if stop_token.is_stopped():
                    break
                event_type = event.get("type")

                delay = self._event_delay(event, speed, human_like)
                if stop_token.wait(delay):
                    break

                if event_type == "mouse_move":
                    self._move_mouse(pyautogui, event, human_like, stop_token)
                elif event_type == "mouse_press":
                    button = _mouse_button(str(event.get("button", "left")))
                    click_x, click_y = self._click_position(
                        pyautogui,
                        event,
                        button,
                        pressed=True,
                    )
                    self._wait_for_priority(stop_token)
                    with self.mouse_operation_lock:
                        pyautogui.mouseDown(
                            x=click_x,
                            y=click_y,
                            button=button,
                    )
                    self._notify_mouse_activity((click_x, click_y))
                    self._pressed_mouse_buttons.append(button)
                elif event_type == "mouse_release":
                    button = _mouse_button(str(event.get("button", "left")))
                    click_x, click_y = self._click_position(
                        pyautogui,
                        event,
                        button,
                        pressed=False,
                    )
                    self._wait_for_priority(stop_token)
                    with self.mouse_operation_lock:
                        pyautogui.mouseUp(
                            x=click_x,
                            y=click_y,
                            button=button,
                        )
                    self._notify_mouse_activity((click_x, click_y))
                    if button in self._pressed_mouse_buttons:
                        self._pressed_mouse_buttons.remove(button)
                elif event_type == "mouse_scroll":
                    self._wait_for_priority(stop_token)
                    with self.mouse_operation_lock:
                        pyautogui.scroll(int(event.get("dy", 0)))
                    if "x" in event and "y" in event:
                        self._notify_mouse_activity((int(event["x"]), int(event["y"])))
                elif event_type == "key_press":
                    key = _keyboard_key(str(event.get("key", "")))
                    pyautogui.keyDown(key)
                    self._pressed_keys.append(key)
                elif event_type == "key_release":
                    key = _keyboard_key(str(event.get("key", "")))
                    pyautogui.keyUp(key)
                    if key in self._pressed_keys:
                        self._pressed_keys.remove(key)
                else:
                    logger.warning("Unknown playback event type: %s", event_type)
                index += 1
        finally:
            self.release_all()
            logger.info("Playback complete")

    def _event_delay(self, event: dict[str, Any], speed: float, human_like: bool) -> float:
        delay = scale_duration(float(event.get("delay_before", 0.0)), speed)
        if not human_like or event.get("type") not in HUMAN_TIMING_EVENT_TYPES:
            return delay
        if delay > 0:
            return self.humanizer.vary_delay(delay)
        if event.get("type") == "mouse_release":
            return self.humanizer.click_press_duration()
        if event.get("type") == "mouse_press":
            return self.humanizer.key_interval(0.01, 0.04)
        return self.humanizer.key_interval(0.02, 0.08)

    def _move_mouse(
        self,
        pyautogui,
        event: dict[str, Any],
        human_like: bool,
        stop_token: PlaybackStopToken,
        duration: float | None = None,
    ) -> None:
        target = (int(event.get("x", 0)), int(event.get("y", 0)))
        self._wait_for_priority(stop_token)
        with self.mouse_operation_lock:
            pyautogui.moveTo(*target, duration=0)
        self._notify_mouse_activity(target)

    def _wait_for_priority(self, stop_token: PlaybackStopToken) -> None:
        while self._priority_mouse_request.is_set() and not stop_token.is_stopped():
            if stop_token.wait(0.001):
                break

    def _notify_mouse_activity(self, position: tuple[int, int] | None = None) -> None:
        if self.on_mouse_activity is not None:
            self.on_mouse_activity(position)
        if self.mouse_activity_yield_seconds > 0:
            time.sleep(self.mouse_activity_yield_seconds)

    def _click_position(
        self,
        pyautogui,
        event: dict[str, Any],
        button: str,
        pressed: bool,
    ) -> tuple[int, int]:
        current = pyautogui.position()
        base_x = int(event.get("x", current.x))
        base_y = int(event.get("y", current.y))
        if not pressed:
            self._active_click_positions.pop(button, None)
        return base_x, base_y

    def release_all(self, keyboard=None, mouse=None) -> None:
        import pyautogui

        configure_pyautogui_fast(pyautogui)
        try:
            for key in reversed(self._pressed_keys):
                try:
                    pyautogui.keyUp(key)
                except Exception:
                    logger.debug("Failed to release key during cleanup", exc_info=True)
            self._pressed_keys.clear()
        finally:
            for button in reversed(self._pressed_mouse_buttons):
                try:
                    pyautogui.mouseUp(button=button)
                except Exception:
                    logger.debug("Failed to release mouse button during cleanup", exc_info=True)
            self._pressed_mouse_buttons.clear()
            self._active_click_positions.clear()


def normalize_playback_speed(speed: float) -> float:
    return max(MIN_PLAYBACK_SPEED, min(MAX_PLAYBACK_SPEED, float(speed or 1.0)))


def scale_duration(duration: float, speed: float) -> float:
    return max(0.0, float(duration) / normalize_playback_speed(speed))


def configure_pyautogui_fast(pyautogui) -> None:
    pyautogui.PAUSE = 0
    for name in ("DARWIN_CATCH_UP_TIME", "MINIMUM_DURATION", "MINIMUM_SLEEP"):
        if hasattr(pyautogui, name):
            try:
                setattr(pyautogui, name, 0)
            except Exception:
                logger.debug("Could not set pyautogui.%s", name, exc_info=True)
