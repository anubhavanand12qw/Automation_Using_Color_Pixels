from app.core.recorder import trim_trailing_key_hotkey


def test_trim_trailing_stop_recording_hotkey_events() -> None:
    events = [
        {"type": "mouse_move", "x": 10, "y": 20},
        {"type": "key_press", "key": "shift"},
        {"type": "key_press", "key": "s"},
        {"type": "key_release", "key": "s"},
        {"type": "key_release", "key": "shift"},
    ]

    assert trim_trailing_key_hotkey(events, {"shift", "s"}) == [
        {"type": "mouse_move", "x": 10, "y": 20}
    ]


def test_trim_trailing_stop_recording_hotkey_keeps_other_keys() -> None:
    events = [
        {"type": "key_press", "key": "a"},
        {"type": "key_release", "key": "a"},
    ]

    assert trim_trailing_key_hotkey(events, {"shift", "s"}) == events
