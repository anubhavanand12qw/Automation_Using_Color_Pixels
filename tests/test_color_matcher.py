from app.core.color_matcher import color_matches, condition_passes, normalize_rgb
from app.core.models import PixelCondition


def test_rgb_tolerance_matching() -> None:
    assert color_matches((100, 120, 140), (108, 115, 150), 10)
    assert not color_matches((100, 120, 140), (111, 115, 150), 10)


def test_match_color_condition() -> None:
    condition = PixelCondition(rgb=(255, 120, 80), match_type="match", tolerance=5)
    assert condition_passes(condition, (252, 125, 84))
    assert not condition_passes(condition, (252, 126, 84))


def test_unmatch_color_condition() -> None:
    condition = PixelCondition(rgb=(20, 30, 40), match_type="unmatch", tolerance=2)
    assert condition_passes(condition, (20, 33, 40))
    assert not condition_passes(condition, (21, 29, 42))


def test_invalid_rgb_rejected() -> None:
    try:
        normalize_rgb((256, 0, 0))
    except ValueError:
        assert True
    else:
        assert False, "Expected invalid channel to raise"

