from app.core.humanizer import Humanizer


def test_humanizer_delay_bounds() -> None:
    humanizer = Humanizer(delay_jitter_ratio=0.2, min_delay=0.01, max_delay=0.2)
    for _ in range(50):
        delay = humanizer.vary_delay(0.1)
        assert 0.01 <= delay <= 0.2


def test_key_interval_bounds() -> None:
    humanizer = Humanizer()
    for _ in range(50):
        interval = humanizer.key_interval(0.01, 0.02)
        assert 0.01 <= interval <= 0.02


def test_click_press_duration_bounds() -> None:
    humanizer = Humanizer()
    for _ in range(50):
        duration = humanizer.click_press_duration()
        assert 0.035 <= duration <= 0.09
