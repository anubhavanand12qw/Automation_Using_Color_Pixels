from app.core.models import ScreenResolution
from app.storage.recording_store import RecordingStore, safe_filename


def test_safe_filename() -> None:
    assert safe_filename("Login Sequence!") == "Login_Sequence"
    assert safe_filename("  ") == "recording"


def test_recording_save_load_and_list(tmp_path) -> None:
    store = RecordingStore(tmp_path)
    events = [{"type": "key_press", "key": "a", "delay_before": 0.1}]
    filename = store.save_recording("login sequence", events, ScreenResolution(1440, 900, 2.0)).name
    loaded = store.load_recording(filename)
    assert loaded["name"] == "login sequence"
    assert loaded["events"] == events
    listed = store.list_recordings()
    assert len(listed) == 1
    assert listed[0]["file"] == filename


def test_recording_delete(tmp_path) -> None:
    store = RecordingStore(tmp_path)
    filename = store.save_recording("delete me", [], ScreenResolution(1440, 900, 2.0)).name
    deleted_path = store.delete_recording(filename)
    assert deleted_path.name == filename
    assert not deleted_path.exists()
    assert store.list_recordings() == []


def test_recording_delete_missing_raises(tmp_path) -> None:
    store = RecordingStore(tmp_path)
    try:
        store.delete_recording("missing.json")
    except FileNotFoundError as exc:
        assert "missing.json" in str(exc)
    else:
        assert False, "Expected missing recording delete to raise"
