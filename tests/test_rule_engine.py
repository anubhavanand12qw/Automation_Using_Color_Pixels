from app.core.models import AutomationRule, PixelCondition
from app.core.rule_engine import RuleRuntimeState, evaluate_rule_conditions, rule_uses_cursor_position


def _rule(*items: dict) -> AutomationRule:
    rule = AutomationRule()
    rule.conditions = list(items)
    return rule


def test_rule_and_evaluation() -> None:
    c1 = PixelCondition(x=1, y=1, rgb=(10, 10, 10), tolerance=0).to_dict()
    c2 = PixelCondition(x=2, y=2, rgb=(20, 20, 20), tolerance=0).to_dict()
    rule = _rule(c1, {"operator": "AND"}, c2)

    def sample(x: int, y: int):
        return {(1, 1): (10, 10, 10), (2, 2): (20, 20, 20)}[(x, y)]

    assert evaluate_rule_conditions(rule, sample)


def test_rule_or_left_to_right_evaluation() -> None:
    c1 = PixelCondition(x=1, y=1, rgb=(1, 1, 1), tolerance=0).to_dict()
    c2 = PixelCondition(x=2, y=2, rgb=(2, 2, 2), tolerance=0).to_dict()
    c3 = PixelCondition(x=3, y=3, rgb=(3, 3, 3), tolerance=0).to_dict()
    rule = _rule(c1, {"operator": "OR"}, c2, {"operator": "AND"}, c3)

    def sample(x: int, y: int):
        return {
            (1, 1): (9, 9, 9),
            (2, 2): (2, 2, 2),
            (3, 3): (3, 3, 3),
        }[(x, y)]

    assert evaluate_rule_conditions(rule, sample)


def test_cursor_position_condition_samples_current_cursor_with_offset() -> None:
    condition = PixelCondition(
        x=10,
        y=-5,
        rgb=(12, 34, 56),
        tolerance=0,
        use_cursor_position=True,
    ).to_dict()
    rule = _rule(condition)
    sampled_points: list[tuple[int, int]] = []

    def sample(x: int, y: int):
        sampled_points.append((x, y))
        return (12, 34, 56)

    assert evaluate_rule_conditions(rule, sample, lambda: (40, 50))
    assert sampled_points == [(50, 45)]


def test_cursor_position_condition_out_of_bounds_is_false() -> None:
    condition = PixelCondition(
        x=10,
        y=0,
        rgb=(12, 34, 56),
        tolerance=0,
        use_cursor_position=True,
    ).to_dict()
    rule = _rule(condition)

    def sample(_x: int, _y: int):
        raise ValueError("outside screen")

    assert not evaluate_rule_conditions(rule, sample, lambda: (99, 10))


def test_cursor_position_condition_requires_provider() -> None:
    condition = PixelCondition(
        rgb=(1, 1, 1),
        tolerance=0,
        use_cursor_position=True,
    ).to_dict()
    rule = _rule(condition)

    try:
        evaluate_rule_conditions(rule, lambda _x, _y: (1, 1, 1))
    except ValueError as exc:
        assert "cursor position provider" in str(exc)
    else:
        assert False, "Expected cursor-position condition to require a provider"


def test_rule_uses_cursor_position_detects_pointer_condition() -> None:
    fixed = PixelCondition(use_cursor_position=False).to_dict()
    pointer = PixelCondition(use_cursor_position=True).to_dict()

    assert not rule_uses_cursor_position(_rule(fixed))
    assert rule_uses_cursor_position(_rule(fixed, {"operator": "AND"}, pointer))


def test_cooldown_blocks_repeated_trigger() -> None:
    rule = AutomationRule(cooldown_seconds=2.0, trigger_mode="repeat")
    state = RuleRuntimeState()
    assert state.should_trigger(rule, True, now=10.0)
    assert not state.should_trigger(rule, True, now=11.0)
    assert state.should_trigger(rule, True, now=12.1)


def test_edge_trigger_requires_false_then_true() -> None:
    rule = AutomationRule(cooldown_seconds=0.0, trigger_mode="edge")
    state = RuleRuntimeState()
    assert state.should_trigger(rule, True, now=1.0)
    assert not state.should_trigger(rule, True, now=2.0)
    assert not state.should_trigger(rule, False, now=3.0)
    assert state.should_trigger(rule, True, now=4.0)


def test_once_trigger_only_fires_once() -> None:
    rule = AutomationRule(cooldown_seconds=0.0, trigger_mode="once")
    state = RuleRuntimeState()
    assert state.should_trigger(rule, True, now=1.0)
    assert not state.should_trigger(rule, True, now=2.0)
