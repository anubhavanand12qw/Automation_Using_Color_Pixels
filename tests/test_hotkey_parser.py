import pytest

from app.core.hotkey_listener import parse_hotkey, to_pynput_hotkey
from app.core.action_executor import classify_keyboard_action


def test_parse_common_hotkey_aliases() -> None:
    parsed = parse_hotkey("command + option + a")
    assert parsed.modifiers == ("cmd", "alt")
    assert parsed.key == "a"
    assert parsed.normalized() == "cmd+alt+a"


def test_parse_shift_number() -> None:
    parsed = parse_hotkey("shift+4")
    assert parsed.modifiers == ("shift",)
    assert parsed.key == "4"


def test_to_pynput_hotkey() -> None:
    assert to_pynput_hotkey("ctrl+option+a") == "<ctrl>+<alt>+a"


def test_parse_special_key_hotkey() -> None:
    parsed = parse_hotkey("cmd+enter")
    assert parsed.modifiers == ("cmd",)
    assert parsed.key == "enter"


def test_classify_text_action() -> None:
    action = classify_keyboard_action("Anubhav")
    assert action.kind == "text"
    assert action.value == "Anubhav"


def test_classify_single_character_as_text() -> None:
    action = classify_keyboard_action("a")
    assert action.kind == "text"
    assert action.value == "a"


def test_classify_special_key_action() -> None:
    action = classify_keyboard_action("return")
    assert action.kind == "special_key"
    assert action.value == "enter"


def test_classify_hotkey_action() -> None:
    action = classify_keyboard_action("shift+4")
    assert action.kind == "hotkey"
    assert action.parsed_hotkey is not None
    assert action.parsed_hotkey.normalized() == "shift+4"


def test_invalid_hotkey_multiple_keys() -> None:
    with pytest.raises(ValueError):
        parse_hotkey("cmd+c+v")


def test_invalid_hotkey_without_main_key() -> None:
    with pytest.raises(ValueError):
        parse_hotkey("cmd+shift")
