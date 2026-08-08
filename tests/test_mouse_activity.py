import threading

from app.core.mouse_activity import MouseActivityNotifier
from app.core.playback import PlaybackEngine, PlaybackStopToken


def test_mouse_activity_keeps_position_events_for_multiple_readers() -> None:
    notifier = MouseActivityNotifier(max_events=10)
    start_version = notifier.version

    notifier.notify((10, 20))
    notifier.notify((30, 40))

    reader_one = notifier.events_since(start_version)
    reader_two = notifier.events_since(start_version)

    assert [event.position for event in reader_one] == [(10, 20), (30, 40)]
    assert [event.position for event in reader_two] == [(10, 20), (30, 40)]
    assert notifier.latest_event_since(start_version).position == (30, 40)


def test_wait_for_mouse_activity_change_returns_on_new_event() -> None:
    notifier = MouseActivityNotifier()
    stop_event = threading.Event()
    start_version = notifier.version
    notifier.notify((1, 2))

    notifier.wait_for_change(start_version, timeout=0.5, stop_event=stop_event)

    assert notifier.events_since(start_version)[0].position == (1, 2)


def test_playback_move_notifies_exact_position() -> None:
    positions: list[tuple[int, int] | None] = []
    engine = PlaybackEngine(on_mouse_activity=positions.append)

    class FakePyAutoGui:
        @staticmethod
        def moveTo(x, y, duration=0):
            return None

    engine._move_mouse(
        FakePyAutoGui,
        {"x": 77, "y": 88},
        human_like=False,
        stop_token=PlaybackStopToken(),
    )

    assert positions == [(77, 88)]
