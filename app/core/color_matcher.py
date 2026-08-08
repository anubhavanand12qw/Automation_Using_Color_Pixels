from __future__ import annotations

from app.core.models import PixelCondition


RGB = tuple[int, int, int]


def normalize_rgb(rgb: list[int] | tuple[int, int, int]) -> RGB:
    if len(rgb) != 3:
        raise ValueError("RGB value must contain exactly three channels.")
    channels = tuple(int(c) for c in rgb)
    if any(c < 0 or c > 255 for c in channels):
        raise ValueError("RGB channels must be between 0 and 255.")
    return channels  # type: ignore[return-value]


def color_matches(expected: RGB, actual: RGB, tolerance: int) -> bool:
    tolerance = max(0, int(tolerance))
    return all(abs(int(a) - int(e)) <= tolerance for e, a in zip(expected, actual))


def condition_passes(condition: PixelCondition, actual_rgb: RGB) -> bool:
    expected = normalize_rgb(condition.rgb)
    actual = normalize_rgb(actual_rgb)
    matched = color_matches(expected, actual, condition.tolerance)
    if condition.match_type == "unmatch":
        return not matched
    return matched

