from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.models import ActionConfig, AutomationRule
from app.core.screen_capture import CapturedPixel
from app.gui.condition_widget import ConditionTableWidget


class RuleEditor(QWidget):
    rule_changed = Signal(object)
    capture_requested = Signal()
    offset_reference_requested = Signal()
    offset_target_requested = Signal()
    recordings_refresh_requested = Signal()
    recording_delete_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.rule: AutomationRule | None = None
        self._recordings: list[dict] = []
        self._loading = False

        layout = QVBoxLayout(self)
        self.empty_label = QLabel("Select a rule or add a new one.")
        layout.addWidget(self.empty_label)

        self.form_group = QGroupBox("Rule")
        form = QFormLayout(self.form_group)

        self.name_edit = QLineEdit()
        self.enabled_check = QCheckBox("Enabled")
        self.human_like_check = QCheckBox("Enable Human-Like Activity")
        self.click_randomness_spin = QSpinBox()
        self.click_randomness_spin.setRange(0, 50)
        self.click_randomness_spin.setSuffix(" px")
        self.polling_combo = QComboBox()
        self.polling_combo.addItems(["1", "2", "5", "10", "25", "50", "100", "250", "500", "1000"])
        self.cooldown_spin = QDoubleSpinBox()
        self.cooldown_spin.setRange(0, 3600)
        self.cooldown_spin.setDecimals(2)
        self.cooldown_spin.setSingleStep(0.05)
        self.trigger_mode_combo = QComboBox()
        self.trigger_mode_combo.addItems(["repeat", "edge", "once"])

        form.addRow("Name", self.name_edit)
        form.addRow("", self.enabled_check)
        form.addRow("", self.human_like_check)
        form.addRow("Polling interval (ms)", self.polling_combo)
        form.addRow("Cooldown (seconds)", self.cooldown_spin)
        form.addRow("Trigger mode", self.trigger_mode_combo)
        layout.addWidget(self.form_group)

        condition_group = QGroupBox("Conditions")
        condition_layout = QVBoxLayout(condition_group)
        buttons = QHBoxLayout()
        self.add_and_btn = QPushButton("Add AND Condition")
        self.add_or_btn = QPushButton("Add OR Condition")
        self.delete_condition_btn = QPushButton("Delete Condition")
        self.capture_btn = QPushButton("Capture Selected (Shift+C)")
        self.offset_reference_btn = QPushButton("Offset Ref (Shift+O)")
        self.offset_target_btn = QPushButton("Offset Target (Shift+L)")
        buttons.addWidget(self.add_and_btn)
        buttons.addWidget(self.add_or_btn)
        buttons.addWidget(self.delete_condition_btn)
        buttons.addWidget(self.capture_btn)
        buttons.addWidget(self.offset_reference_btn)
        buttons.addWidget(self.offset_target_btn)
        condition_layout.addLayout(buttons)
        self.condition_table = ConditionTableWidget()
        condition_layout.addWidget(self.condition_table)
        layout.addWidget(condition_group, 1)

        action_group = QGroupBox("Action")
        action_form = QFormLayout(action_group)
        self.action_type_combo = QComboBox()
        self.action_type_combo.addItem("Press Key / Hotkey / Type Text", "hotkey")
        self.action_type_combo.addItem("Mouse Left Click", "mouse_left_click")
        self.action_type_combo.addItem("Mouse Right Click", "mouse_right_click")
        self.action_type_combo.addItem("Select Recorded Sequence", "recording")
        self.recording_combo = QComboBox()
        self.refresh_recordings_btn = QPushButton("Refresh Recordings")
        self.delete_recording_btn = QPushButton("Delete Recording")
        self.recording_relative_check = QCheckBox("Play recording relative to current pointer")
        self.playback_speed_combo = QComboBox()
        for label, value in [
            ("0.05x", 0.05),
            ("0.1x", 0.1),
            ("0.2x", 0.2),
            ("0.25x", 0.25),
            ("0.5x", 0.5),
            ("0.75x", 0.75),
            ("1.0x", 1.0),
            ("1.25x", 1.25),
            ("1.5x", 1.5),
            ("2.0x", 2.0),
            ("3.0x", 3.0),
            ("5.0x", 5.0),
            ("10.0x", 10.0),
            ("20.0x", 20.0),
        ]:
            self.playback_speed_combo.addItem(label, value)
        recording_row = QHBoxLayout()
        recording_row.addWidget(self.recording_combo, 1)
        recording_row.addWidget(self.refresh_recordings_btn)
        recording_row.addWidget(self.delete_recording_btn)
        self.hotkey_edit = QLineEdit("shift+4")
        action_form.addRow("Action Type", self.action_type_combo)
        action_form.addRow("Recording", recording_row)
        action_form.addRow("", self.recording_relative_check)
        action_form.addRow("Playback speed", self.playback_speed_combo)
        action_form.addRow("Key / Hotkey / Text", self.hotkey_edit)
        layout.addWidget(action_group)

        for widget in [
            self.name_edit,
            self.enabled_check,
            self.human_like_check,
            self.click_randomness_spin,
            self.polling_combo,
            self.cooldown_spin,
            self.trigger_mode_combo,
            self.action_type_combo,
            self.recording_combo,
            self.recording_relative_check,
            self.playback_speed_combo,
            self.hotkey_edit,
        ]:
            if hasattr(widget, "textChanged"):
                widget.textChanged.connect(self._emit_changed)
            if hasattr(widget, "stateChanged"):
                widget.stateChanged.connect(self._emit_changed)
            if hasattr(widget, "currentIndexChanged"):
                widget.currentIndexChanged.connect(self._emit_changed)
            if hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self._emit_changed)

        self.condition_table.changed.connect(self._emit_changed)
        self.add_and_btn.clicked.connect(lambda: self.condition_table.add_condition("AND"))
        self.add_or_btn.clicked.connect(lambda: self.condition_table.add_condition("OR"))
        self.delete_condition_btn.clicked.connect(self.condition_table.remove_selected_condition)
        self.capture_btn.clicked.connect(self.capture_requested.emit)
        self.offset_reference_btn.clicked.connect(self.offset_reference_requested.emit)
        self.offset_target_btn.clicked.connect(self.offset_target_requested.emit)
        self.refresh_recordings_btn.clicked.connect(self.recordings_refresh_requested.emit)
        self.delete_recording_btn.clicked.connect(self._request_delete_recording)
        self.action_type_combo.currentIndexChanged.connect(self._update_action_visibility)
        self.human_like_check.stateChanged.connect(self._update_human_like_visibility)
        self._set_editor_enabled(False)

    def set_recordings(self, recordings: list[dict]) -> None:
        self._recordings = recordings
        current = self.recording_combo.currentData()
        self.recording_combo.blockSignals(True)
        self.recording_combo.clear()
        for item in recordings:
            label = f"{item['name']} ({item['file']})"
            self.recording_combo.addItem(label, item["file"])
        found_current = False
        if current:
            index = self.recording_combo.findData(current)
            if index >= 0:
                self.recording_combo.setCurrentIndex(index)
                found_current = True
        self.recording_combo.blockSignals(False)
        if current and not found_current and self.rule is not None:
            self.rule.action.recording_file = ""
            self.recording_combo.setCurrentIndex(-1)
            self.rule_changed.emit(self.rule)

    def load_rule(self, rule: AutomationRule | None) -> None:
        self.rule = rule
        self._set_editor_enabled(rule is not None)
        if rule is None:
            self.empty_label.setVisible(True)
            return
        self.empty_label.setVisible(False)
        self._loading = True
        self.blockSignals(True)
        self.name_edit.setText(rule.rule_name)
        self.enabled_check.setChecked(rule.enabled)
        self.human_like_check.setChecked(rule.human_like)
        self.click_randomness_spin.setValue(rule.click_randomness_px)
        self.polling_combo.setCurrentText(str(rule.polling_interval_ms))
        self.cooldown_spin.setValue(rule.cooldown_seconds)
        self.trigger_mode_combo.setCurrentText(rule.trigger_mode)
        action_index = self.action_type_combo.findData(rule.action.action_type)
        self.action_type_combo.setCurrentIndex(action_index if action_index >= 0 else 0)
        self.recording_relative_check.setChecked(rule.action.recording_relative_to_pointer)
        speed_index = self.playback_speed_combo.findData(rule.action.playback_speed)
        if speed_index < 0:
            self.playback_speed_combo.addItem(f"{rule.action.playback_speed:g}x", rule.action.playback_speed)
            speed_index = self.playback_speed_combo.findData(rule.action.playback_speed)
        self.playback_speed_combo.setCurrentIndex(speed_index)
        self.hotkey_edit.setText(rule.action.hotkey)
        self.condition_table.load_conditions(rule.conditions)
        self.blockSignals(False)
        index = self.recording_combo.findData(rule.action.recording_file)
        if index >= 0:
            self.recording_combo.setCurrentIndex(index)
        self._update_action_visibility()
        self._update_human_like_visibility()
        self._loading = False

    def apply_capture(self, capture: CapturedPixel) -> bool:
        if self.rule is None:
            return False
        applied = self.condition_table.apply_capture_to_selected(capture)
        if applied:
            self._emit_changed()
        return applied

    def apply_offset_capture(
        self,
        reference_x: int,
        reference_y: int,
        capture: CapturedPixel,
    ) -> bool:
        if self.rule is None:
            return False
        applied = self.condition_table.apply_offset_capture_to_selected(
            reference_x,
            reference_y,
            capture,
        )
        if applied:
            self._emit_changed()
        return applied

    def selected_condition_id(self) -> str | None:
        return self.condition_table.selected_condition_id()

    def selected_uses_pointer(self) -> bool:
        return self.condition_table.selected_uses_pointer()

    def _emit_changed(self, *_args) -> None:
        if self.rule is None or self._loading:
            return
        self.rule.rule_name = self.name_edit.text().strip() or "Untitled Rule"
        self.rule.enabled = self.enabled_check.isChecked()
        self.rule.human_like = self.human_like_check.isChecked()
        self.rule.click_randomness_px = self.click_randomness_spin.value()
        self.rule.polling_interval_ms = int(self.polling_combo.currentText())
        self.rule.cooldown_seconds = float(self.cooldown_spin.value())
        self.rule.trigger_mode = self.trigger_mode_combo.currentText()
        self.rule.conditions = self.condition_table.to_expression()
        self.rule.action = ActionConfig(
            action_type=self.action_type_combo.currentData(),
            recording_file=self.recording_combo.currentData() or "",
            hotkey=self.hotkey_edit.text().strip(),
            recording_relative_to_pointer=self.recording_relative_check.isChecked(),
            playback_speed=float(self.playback_speed_combo.currentData() or 1.0),
        )
        self.rule_changed.emit(self.rule)
        self._update_action_visibility()
        self._update_human_like_visibility()

    def _update_action_visibility(self) -> None:
        action_type = self.action_type_combo.currentData()
        is_recording = action_type == "recording"
        is_keyboard = action_type == "hotkey"
        self.recording_combo.setEnabled(is_recording)
        self.refresh_recordings_btn.setEnabled(is_recording)
        self.delete_recording_btn.setEnabled(is_recording and self.recording_combo.currentData() is not None)
        self.recording_relative_check.setEnabled(is_recording)
        self.playback_speed_combo.setEnabled(is_recording)
        self.hotkey_edit.setEnabled(is_keyboard)

    def _request_delete_recording(self) -> None:
        filename = self.recording_combo.currentData()
        if filename:
            self.recording_delete_requested.emit(str(filename))

    def _update_human_like_visibility(self) -> None:
        return

    def _set_editor_enabled(self, enabled: bool) -> None:
        for child in self.findChildren(QWidget):
            child.setEnabled(enabled)
        self.empty_label.setEnabled(True)
