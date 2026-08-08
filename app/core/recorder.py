from __future__ import annotations

import logging
import platform
import threading
import time
from typing import Any

from app.core.models import ScreenResolution
from app.core.screen_capture import ScreenCapture
from app.storage.recording_store import RecordingStore

logger = logging.getLogger("pixel_automation.recorder")

STOP_RECORDING_HOTKEY_KEYS = {"shift", "s"}


MAC_KEYCODE_MAP = {
    0: "a",
    1: "s",
    2: "d",
    3: "f",
    4: "h",
    5: "g",
    6: "z",
    7: "x",
    8: "c",
    9: "v",
    11: "b",
    12: "q",
    13: "w",
    14: "e",
    15: "r",
    16: "y",
    17: "t",
    18: "1",
    19: "2",
    20: "3",
    21: "4",
    22: "6",
    23: "5",
    24: "=",
    25: "9",
    26: "7",
    27: "-",
    28: "8",
    29: "0",
    30: "]",
    31: "o",
    32: "u",
    33: "[",
    34: "i",
    35: "p",
    36: "enter",
    37: "l",
    38: "j",
    39: "'",
    40: "k",
    41: ";",
    42: "\\",
    43: ",",
    44: "/",
    45: "n",
    46: "m",
    47: ".",
    48: "tab",
    49: "space",
    50: "`",
    51: "backspace",
    53: "esc",
    55: "cmd",
    56: "shift",
    57: "caps_lock",
    58: "alt",
    59: "ctrl",
    60: "shift",
    61: "alt",
    62: "ctrl",
    63: "fn",
    96: "f5",
    97: "f6",
    98: "f7",
    99: "f3",
    100: "f8",
    101: "f9",
    103: "f11",
    109: "f10",
    111: "f12",
    115: "home",
    116: "page_up",
    117: "delete",
    119: "end",
    121: "page_down",
    122: "f1",
    123: "left",
    124: "right",
    125: "down",
    126: "up",
}


def serialize_key(key: Any) -> str:
    text = str(key)
    if text.startswith("Key."):
        return text.replace("Key.", "", 1)
    if hasattr(key, "char") and key.char is not None:
        return str(key.char)
    return text.strip("'")


def serialize_button(button: Any) -> str:
    return str(button).replace("Button.", "")


class InputRecorder:
    def __init__(
        self,
        recording_store: RecordingStore | None = None,
        screen_capture: ScreenCapture | None = None,
    ) -> None:
        self.recording_store = recording_store or RecordingStore()
        self.screen_capture = screen_capture or ScreenCapture()
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._mouse_listener = None
        self._keyboard_listener = None
        self._backend = ""
        self._started_at = 0.0
        self._last_event_at = 0.0
        self._recording = False
        self._name = "recording"

        self._quartz_thread: threading.Thread | None = None
        self._quartz_run_loop = None
        self._quartz_tap = None
        self._quartz_source = None
        self._quartz_callback = None
        self._quartz_ready = threading.Event()
        self._quartz_error: Exception | None = None

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def event_count(self) -> int:
        with self._lock:
            return len(self._events)

    def start(self, name: str) -> None:
        if self._recording:
            raise RuntimeError("Recording is already active.")

        self._name = name.strip() or "recording"
        with self._lock:
            self._events = []
        now = time.monotonic()
        self._started_at = now
        self._last_event_at = now
        self._recording = True

        try:
            if platform.system() == "Darwin":
                self._start_quartz_recording()
            else:
                self._start_pynput_recording()
        except Exception:
            self._recording = False
            self._stop_backend()
            raise

    def stop_and_save(self, trim_stop_hotkey: bool = False) -> str:
        if not self._recording:
            raise RuntimeError("No active recording.")
        self._recording = False
        self._stop_backend()

        with self._lock:
            events = list(self._events)
        if trim_stop_hotkey:
            events = trim_trailing_key_hotkey(events, STOP_RECORDING_HOTKEY_KEYS)
        screen_info: ScreenResolution = self.screen_capture.get_screen_info()
        path = self.recording_store.save_recording(self._name, events, screen_info)
        logger.info("Recording stopped and saved: %s", path.name)
        return path.name

    def cancel(self) -> None:
        self._recording = False
        self._stop_backend()
        with self._lock:
            self._events = []
        logger.info("Recording canceled")

    def _start_pynput_recording(self) -> None:
        from pynput import keyboard, mouse

        self._backend = "pynput"
        self._mouse_listener = mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._mouse_listener.start()
        self._keyboard_listener.start()
        logger.info("Recording started with pynput backend: %s", self._name)

    def _start_quartz_recording(self) -> None:
        self._backend = "quartz"
        self._quartz_ready.clear()
        self._quartz_error = None
        self._quartz_thread = threading.Thread(
            target=self._quartz_run,
            name="QuartzInputRecorder",
            daemon=True,
        )
        self._quartz_thread.start()
        if not self._quartz_ready.wait(timeout=2.0):
            raise RuntimeError("Quartz recorder did not start. Check Input Monitoring permission.")
        if self._quartz_error is not None:
            raise RuntimeError(f"Quartz recorder failed: {self._quartz_error}") from self._quartz_error
        logger.info("Recording started with Quartz backend: %s", self._name)

    def _quartz_run(self) -> None:
        try:
            import Quartz

            event_types = [
                Quartz.kCGEventMouseMoved,
                Quartz.kCGEventLeftMouseDown,
                Quartz.kCGEventLeftMouseUp,
                Quartz.kCGEventRightMouseDown,
                Quartz.kCGEventRightMouseUp,
                Quartz.kCGEventOtherMouseDown,
                Quartz.kCGEventOtherMouseUp,
                Quartz.kCGEventScrollWheel,
                Quartz.kCGEventKeyDown,
                Quartz.kCGEventKeyUp,
            ]
            mask = 0
            for event_type in event_types:
                mask |= Quartz.CGEventMaskBit(event_type)

            self._quartz_callback = self._quartz_event_callback
            tap = Quartz.CGEventTapCreate(
                Quartz.kCGSessionEventTap,
                Quartz.kCGHeadInsertEventTap,
                Quartz.kCGEventTapOptionListenOnly,
                mask,
                self._quartz_callback,
                None,
            )
            if tap is None:
                raise RuntimeError(
                    "macOS refused to create the input event tap. Grant Input Monitoring and Accessibility permissions."
                )

            self._quartz_tap = tap
            self._quartz_run_loop = Quartz.CFRunLoopGetCurrent()
            self._quartz_source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
            Quartz.CFRunLoopAddSource(
                self._quartz_run_loop,
                self._quartz_source,
                Quartz.kCFRunLoopCommonModes,
            )
            Quartz.CGEventTapEnable(tap, True)
            self._quartz_ready.set()
            Quartz.CFRunLoopRun()
        except Exception as exc:
            self._quartz_error = exc
            self._quartz_ready.set()
            logger.exception("Quartz recorder failed")
        finally:
            try:
                if self._quartz_tap is not None:
                    import Quartz

                    Quartz.CGEventTapEnable(self._quartz_tap, False)
            except Exception:
                logger.debug("Failed to disable Quartz recorder tap", exc_info=True)

    def _quartz_event_callback(self, proxy, event_type, event, refcon):
        try:
            import Quartz

            if event_type in {
                Quartz.kCGEventTapDisabledByTimeout,
                Quartz.kCGEventTapDisabledByUserInput,
            }:
                if self._quartz_tap is not None:
                    Quartz.CGEventTapEnable(self._quartz_tap, True)
                return event

            location = Quartz.CGEventGetLocation(event)
            x = int(round(location.x))
            y = int(round(location.y))

            if event_type == Quartz.kCGEventMouseMoved:
                self._on_move(x, y)
            elif event_type in {
                Quartz.kCGEventLeftMouseDown,
                Quartz.kCGEventRightMouseDown,
                Quartz.kCGEventOtherMouseDown,
            }:
                self._append(
                    {
                        "type": "mouse_press",
                        "button": self._quartz_button_name(event_type),
                        "x": x,
                        "y": y,
                    }
                )
            elif event_type in {
                Quartz.kCGEventLeftMouseUp,
                Quartz.kCGEventRightMouseUp,
                Quartz.kCGEventOtherMouseUp,
            }:
                self._append(
                    {
                        "type": "mouse_release",
                        "button": self._quartz_button_name(event_type),
                        "x": x,
                        "y": y,
                    }
                )
            elif event_type == Quartz.kCGEventScrollWheel:
                dy = int(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGScrollWheelEventDeltaAxis1))
                dx = int(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGScrollWheelEventDeltaAxis2))
                self._on_scroll(x, y, dx, dy)
            elif event_type in {Quartz.kCGEventKeyDown, Quartz.kCGEventKeyUp}:
                keycode = int(Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode))
                key = MAC_KEYCODE_MAP.get(keycode, f"keycode_{keycode}")
                self._append(
                    {
                        "type": "key_press" if event_type == Quartz.kCGEventKeyDown else "key_release",
                        "key": key,
                    }
                )
        except Exception:
            logger.exception("Failed to record Quartz input event")
        return event

    @staticmethod
    def _quartz_button_name(event_type: int) -> str:
        try:
            import Quartz

            if event_type in {Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp}:
                return "right"
            if event_type in {Quartz.kCGEventOtherMouseDown, Quartz.kCGEventOtherMouseUp}:
                return "middle"
        except Exception:
            pass
        return "left"

    def _stop_backend(self) -> None:
        if self._backend == "quartz":
            try:
                if self._quartz_tap is not None:
                    import Quartz

                    Quartz.CGEventTapEnable(self._quartz_tap, False)
                if self._quartz_run_loop is not None:
                    import Quartz

                    Quartz.CFRunLoopStop(self._quartz_run_loop)
            finally:
                if self._quartz_thread is not None:
                    self._quartz_thread.join(timeout=1.5)
                self._quartz_thread = None
                self._quartz_run_loop = None
                self._quartz_tap = None
                self._quartz_source = None
                self._quartz_callback = None
        else:
            for listener in (self._mouse_listener, self._keyboard_listener):
                if listener is not None:
                    listener.stop()
            self._mouse_listener = None
            self._keyboard_listener = None
        self._backend = ""

    def _delay(self) -> float:
        now = time.monotonic()
        delay = now - self._last_event_at
        self._last_event_at = now
        return round(delay, 4)

    def _append(self, event: dict[str, Any]) -> None:
        if not self._recording:
            return
        event["delay_before"] = self._delay()
        with self._lock:
            self._events.append(event)

    def _on_move(self, x: int, y: int) -> None:
        self._append({"type": "mouse_move", "x": int(x), "y": int(y)})

    def _on_click(self, x: int, y: int, button: Any, pressed: bool) -> None:
        self._append(
            {
                "type": "mouse_press" if pressed else "mouse_release",
                "button": serialize_button(button),
                "x": int(x),
                "y": int(y),
            }
        )

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self._append(
            {
                "type": "mouse_scroll",
                "x": int(x),
                "y": int(y),
                "dx": int(dx),
                "dy": int(dy),
            }
        )

    def _on_key_press(self, key: Any) -> None:
        self._append({"type": "key_press", "key": serialize_key(key)})

    def _on_key_release(self, key: Any) -> None:
        self._append({"type": "key_release", "key": serialize_key(key)})


def trim_trailing_key_hotkey(
    events: list[dict[str, Any]],
    hotkey_keys: set[str],
    max_events: int = 8,
) -> list[dict[str, Any]]:
    """Remove trailing key events generated by the recorder stop shortcut."""

    trimmed = list(events)
    removed = 0
    while trimmed and removed < max_events:
        event = trimmed[-1]
        if event.get("type") not in {"key_press", "key_release"}:
            break
        key = str(event.get("key", "")).lower()
        if key not in hotkey_keys:
            break
        trimmed.pop()
        removed += 1
    return trimmed
