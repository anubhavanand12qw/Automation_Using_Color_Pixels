from app.core.playback import (
    PlaybackEngine,
    PlaybackStopToken,
    find_recording_mouse_origin,
    normalize_playback_speed,
    relative_mouse_event,
    scale_duration,
)


def test_find_recording_mouse_origin_uses_first_mouse_position_event() -> None:
    events = [
        {"type": "key_press", "key": "a"},
        {"type": "mouse_press", "x": 100, "y": 200, "button": "left"},
        {"type": "mouse_release", "x": 110, "y": 220, "button": "left"},
    ]
    assert find_recording_mouse_origin(events) == (100, 200)


def test_relative_mouse_event_maps_from_recorded_origin_to_playback_origin() -> None:
    event = {"type": "mouse_release", "x": 125, "y": 230, "button": "left"}
    adjusted = relative_mouse_event(event, (100, 200), (500, 700))
    assert adjusted["x"] == 525
    assert adjusted["y"] == 730
    assert event["x"] == 125
    assert event["y"] == 230


def test_relative_mouse_event_leaves_keyboard_event_unchanged() -> None:
    event = {"type": "key_press", "key": "shift"}
    assert relative_mouse_event(event, (100, 200), (500, 700)) is event


def test_playback_speed_scales_duration() -> None:
    assert scale_duration(1.0, 2.0) == 0.5
    assert scale_duration(1.0, 0.5) == 2.0


def test_playback_speed_is_clamped() -> None:
    assert normalize_playback_speed(0.01) == 0.05
    assert normalize_playback_speed(99) == 20.0


def test_human_like_mouse_move_stays_exact(monkeypatch) -> None:
    engine = PlaybackEngine()
    moves: list[tuple[int, int, float]] = []

    class FakePyAutoGui:
        @staticmethod
        def moveTo(x, y, duration=0):
            moves.append((x, y, duration))

    engine._move_mouse(
        FakePyAutoGui,
        {"type": "mouse_move", "x": 30, "y": 40},
        human_like=True,
        stop_token=PlaybackStopToken(),
    )

    assert moves == [(30, 40, 0)]


def test_human_like_delay_jitter_only_for_input_events(monkeypatch) -> None:
    engine = PlaybackEngine()
    monkeypatch.setattr(engine.humanizer, "vary_delay", lambda value: value + 1.0)
    monkeypatch.setattr(engine.humanizer, "click_press_duration", lambda: 0.04)
    monkeypatch.setattr(engine.humanizer, "key_interval", lambda low=0.04, high=0.12: 0.03)

    assert engine._event_delay({"type": "mouse_move", "delay_before": 0.2}, 1.0, True) == 0.2
    assert engine._event_delay({"type": "mouse_press", "delay_before": 0.2}, 1.0, True) == 1.2
    assert engine._event_delay({"type": "key_release", "delay_before": 0.2}, 1.0, True) == 1.2
    assert engine._event_delay({"type": "mouse_release", "delay_before": 0.0}, 1.0, True) == 0.04
    assert engine._event_delay({"type": "key_press", "delay_before": 0.0}, 1.0, True) == 0.03
