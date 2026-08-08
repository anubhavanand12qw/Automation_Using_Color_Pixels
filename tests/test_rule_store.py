from app.core.models import ActionConfig, AutomationRule, PixelCondition
from app.storage.rule_store import RuleStore


def test_rule_save_load(tmp_path) -> None:
    store = RuleStore(tmp_path / "rules.json")
    rule = AutomationRule(
        rule_name="Example",
        cooldown_seconds=3.0,
        click_randomness_px=5,
        action=ActionConfig(
            action_type="recording",
            recording_file="example.json",
            recording_relative_to_pointer=True,
            playback_speed=1.5,
        ),
    )
    rule.add_condition(PixelCondition(x=5, y=6, rgb=(1, 2, 3), use_cursor_position=True))
    store.save_rules([rule])
    loaded = store.load_rules()
    assert len(loaded) == 1
    assert loaded[0].rule_name == "Example"
    assert loaded[0].conditions[0]["rgb"] == [1, 2, 3]
    assert loaded[0].conditions[0]["use_cursor_position"] is True
    assert loaded[0].cooldown_seconds == 3.0
    assert loaded[0].click_randomness_px == 5
    assert loaded[0].action.recording_relative_to_pointer is True
    assert loaded[0].action.playback_speed == 1.5


def test_mouse_click_action_save_load(tmp_path) -> None:
    store = RuleStore(tmp_path / "rules.json")
    rule = AutomationRule(rule_name="Click", action=ActionConfig(action_type="mouse_right_click"))
    store.save_rules([rule])
    loaded = store.load_rules()
    assert loaded[0].action.action_type == "mouse_right_click"
