import time
from types import SimpleNamespace

from app.core.action_executor import ActionExecutor
from app.core.models import ActionConfig


class TrackingLock:
    def __init__(self) -> None:
        self.entries = 0

    def acquire(self) -> bool:
        self.entries += 1
        return True

    def release(self) -> None:
        return None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        return None


def test_recording_action_uses_recording_lock(monkeypatch) -> None:
    lock = TrackingLock()
    executor = ActionExecutor(automation_lock=lock)  # type: ignore[arg-type]

    monkeypatch.setattr(
        executor,
        "_execute_recording",
        lambda *_args, **_kwargs: time.sleep(0.001),
    )

    executor.execute(ActionConfig(action_type="recording", recording_file="demo.json"), human_like=False)

    assert lock.entries == 1


def test_mouse_click_action_does_not_use_recording_lock(monkeypatch) -> None:
    lock = TrackingLock()
    executor = ActionExecutor(automation_lock=lock)  # type: ignore[arg-type]
    clicked: list[str] = []

    monkeypatch.setattr(
        executor,
        "_execute_mouse_click",
        lambda button, *_args, **_kwargs: clicked.append(button),
    )

    executor.execute(ActionConfig(action_type="mouse_left_click"), human_like=False)

    assert clicked == ["left"]
    assert lock.entries == 0


def test_keyboard_action_does_not_use_recording_lock(monkeypatch) -> None:
    lock = TrackingLock()
    executor = ActionExecutor(automation_lock=lock)  # type: ignore[arg-type]
    typed: list[str] = []

    monkeypatch.setattr(
        executor,
        "_execute_keyboard_action",
        lambda value, _human_like: typed.append(value),
    )

    executor.execute(ActionConfig(action_type="hotkey", hotkey="cmd+c"), human_like=False)

    assert typed == ["cmd+c"]
    assert lock.entries == 0


def test_mouse_click_uses_trigger_position_and_mouse_operation_lock(monkeypatch) -> None:
    events: list[tuple[str, int, int, str]] = []

    fake_pyautogui = SimpleNamespace(
        PAUSE=0,
        position=lambda: SimpleNamespace(x=1, y=2),
        moveTo=lambda x, y, duration=0: events.append(("move", x, y, "")),
        mouseDown=lambda x, y, button: events.append(("down", x, y, button)),
        mouseUp=lambda x, y, button: events.append(("up", x, y, button)),
    )
    monkeypatch.setitem(__import__("sys").modules, "pyautogui", fake_pyautogui)

    executor = ActionExecutor()
    mouse_lock = TrackingLock()
    executor.playback_engine.mouse_operation_lock = mouse_lock  # type: ignore[assignment]
    monkeypatch.setattr(executor, "_post_native_click", lambda *_args: False)
    monkeypatch.setattr(executor.stop_token, "wait", lambda _seconds: False)

    executor._execute_mouse_click("left", human_like=False, click_randomness_px=0, target_position=(42, 43))

    assert events == [("move", 42, 43, ""), ("down", 42, 43, "left"), ("up", 42, 43, "left")]
    assert mouse_lock.entries == 1
