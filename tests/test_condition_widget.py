import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.core.models import PixelCondition, ScreenResolution
from app.core.screen_capture import CapturedPixel
from app.gui.condition_widget import ConditionTableWidget


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_pointer_offset_capture_sets_offsets_and_rgb() -> None:
    _app()
    table = ConditionTableWidget()
    condition = PixelCondition(use_cursor_position=True).to_dict()
    table.load_conditions([condition])
    table.selectRow(0)

    capture = CapturedPixel(
        x=112,
        y=93,
        rgb=(10, 20, 30),
        screen_resolution=ScreenResolution(width=300, height=200, scale_factor=2.0),
        captured_at="2026-05-26T10:00:00",
    )

    assert table.selected_uses_pointer()
    assert table.apply_offset_capture_to_selected(100, 100, capture)

    saved = table.to_expression()[0]
    assert saved["x"] == 12
    assert saved["y"] == -7
    assert saved["rgb"] == [10, 20, 30]


def test_offset_capture_requires_pointer_condition() -> None:
    _app()
    table = ConditionTableWidget()
    condition = PixelCondition(use_cursor_position=False).to_dict()
    table.load_conditions([condition])
    table.selectRow(0)

    capture = CapturedPixel(
        x=112,
        y=93,
        rgb=(10, 20, 30),
        screen_resolution=ScreenResolution(width=300, height=200),
        captured_at="2026-05-26T10:00:00",
    )

    assert not table.selected_uses_pointer()
    assert not table.apply_offset_capture_to_selected(100, 100, capture)
