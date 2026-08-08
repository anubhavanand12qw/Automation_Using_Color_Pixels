from __future__ import annotations

import copy
import logging
import queue
import threading

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.core.hotkey_listener import AppHotkeyListener
from app.core.models import AutomationRule, PixelCondition, new_id
from app.core.recorder import InputRecorder
from app.core.scheduler import AutomationScheduler
from app.core.screen_capture import CapturedPixel, ScreenCapture
from app.gui.recorder_widget import RecorderWidget
from app.gui.rule_editor import RuleEditor
from app.gui.settings_widget import SettingsWidget
from app.storage.recording_store import RecordingStore
from app.storage.rule_store import RuleStore
from app.utils.logger import setup_logging
from app.utils.paths import ensure_project_dirs


class MainWindow(QMainWindow):
    capture_hotkey_pressed = Signal()
    offset_reference_hotkey_pressed = Signal()
    offset_target_hotkey_pressed = Signal()
    start_automation_hotkey_pressed = Signal()
    recording_hotkey_pressed = Signal()
    recording_stop_hotkey_pressed = Signal()
    emergency_hotkey_pressed = Signal()
    capture_result = Signal(object)
    capture_error = Signal(str)
    offset_capture_result = Signal(object)
    offset_capture_error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        ensure_project_dirs()
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.logger = setup_logging(self.log_queue)
        self.logger.info("App start")

        self.rule_store = RuleStore()
        self.recording_store = RecordingStore()
        self.screen_capture = ScreenCapture()
        self.recorder = InputRecorder(self.recording_store, self.screen_capture)
        self.scheduler = AutomationScheduler(self.screen_capture)
        self.rules: list[AutomationRule] = self.rule_store.load_rules()
        self._offset_reference: tuple[str, str, int, int] | None = None

        self.setWindowTitle("Pixel Automation App")
        self.resize(1280, 820)
        self._build_ui()
        self._wire_events()
        self._start_hotkeys()
        self.refresh_recordings()
        self.refresh_rule_list()

        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._drain_runtime_events)
        self.timer.start()

    def _build_ui(self) -> None:
        self.toolbar = QToolBar("Automation")
        self.addToolBar(self.toolbar)
        self.start_btn = QPushButton("Start Automation")
        self.stop_btn = QPushButton("Stop Automation")
        self.pause_btn = QPushButton("Pause")
        self.resume_btn = QPushButton("Resume")
        self.toolbar.addWidget(self.start_btn)
        self.toolbar.addWidget(self.stop_btn)
        self.toolbar.addWidget(self.pause_btn)
        self.toolbar.addWidget(self.resume_btn)
        self.stop_btn.setEnabled(False)
        self.resume_btn.setEnabled(False)

        central = QWidget()
        main_layout = QVBoxLayout(central)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Rules"))
        self.rule_list = QListWidget()
        left_layout.addWidget(self.rule_list, 1)
        row = QHBoxLayout()
        self.add_rule_btn = QPushButton("Add Rule")
        self.duplicate_rule_btn = QPushButton("Duplicate")
        self.delete_rule_btn = QPushButton("Delete")
        row.addWidget(self.add_rule_btn)
        row.addWidget(self.duplicate_rule_btn)
        row.addWidget(self.delete_rule_btn)
        left_layout.addLayout(row)
        splitter.addWidget(left)

        self.tabs = QTabWidget()
        self.rule_editor = RuleEditor()
        self.recorder_widget = RecorderWidget(self.recorder)
        self.settings_widget = SettingsWidget(self.screen_capture)
        self.tabs.addTab(self.rule_editor, "Rule Editor")
        self.tabs.addTab(self.recorder_widget, "Recorder")
        self.tabs.addTab(self.settings_widget, "Settings")
        splitter.addWidget(self.tabs)
        splitter.setSizes([340, 940])
        main_layout.addWidget(splitter, 1)

        self.status_log = QTextEdit()
        self.status_log.setReadOnly(True)
        self.status_log.setMaximumHeight(180)
        main_layout.addWidget(QLabel("Status Logs"))
        main_layout.addWidget(self.status_log)
        self.setCentralWidget(central)

        self.setStyleSheet(
            """
            QMainWindow { background: #f6f7f9; }
            QGroupBox { font-weight: 600; border: 1px solid #d5d9e0; border-radius: 6px; margin-top: 10px; padding: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            QPushButton { padding: 6px 10px; }
            QListWidget { border: 1px solid #d5d9e0; border-radius: 6px; background: white; }
            QTextEdit { border: 1px solid #d5d9e0; border-radius: 6px; background: #111827; color: #e5e7eb; }
            """
        )

    def _wire_events(self) -> None:
        self.add_rule_btn.clicked.connect(self.add_rule)
        self.duplicate_rule_btn.clicked.connect(self.duplicate_selected_rule)
        self.delete_rule_btn.clicked.connect(self.delete_selected_rule)
        self.rule_list.currentItemChanged.connect(self._on_rule_selected)
        self.rule_editor.rule_changed.connect(self._on_rule_changed)
        self.rule_editor.capture_requested.connect(self.capture_selected_condition)
        self.rule_editor.offset_reference_requested.connect(self.capture_offset_reference)
        self.rule_editor.offset_target_requested.connect(self.capture_offset_target)
        self.rule_editor.recordings_refresh_requested.connect(self.refresh_recordings)
        self.rule_editor.recording_delete_requested.connect(self.delete_recording)
        self.recorder_widget.recording_saved.connect(lambda _file: self.refresh_recordings())
        self.recorder_widget.status_message.connect(self.append_status)
        self.recorder_widget.recording_start_requested.connect(self._prepare_for_recording)

        self.start_btn.clicked.connect(self.start_automation)
        self.stop_btn.clicked.connect(self.stop_automation)
        self.pause_btn.clicked.connect(self.pause_automation)
        self.resume_btn.clicked.connect(self.resume_automation)

        self.capture_hotkey_pressed.connect(self.capture_selected_condition)
        self.offset_reference_hotkey_pressed.connect(self.capture_offset_reference)
        self.offset_target_hotkey_pressed.connect(self.capture_offset_target)
        self.start_automation_hotkey_pressed.connect(self._start_automation_from_hotkey)
        self.recording_hotkey_pressed.connect(self._start_recording_from_hotkey)
        self.recording_stop_hotkey_pressed.connect(self._stop_recording_from_hotkey)
        self.emergency_hotkey_pressed.connect(self.emergency_stop)
        self.capture_result.connect(self._apply_capture_result)
        self.capture_error.connect(lambda message: self.append_status(f"Capture failed: {message}"))
        self.offset_capture_result.connect(self._apply_offset_capture_result)
        self.offset_capture_error.connect(lambda message: self.append_status(f"Offset capture failed: {message}"))

    def _start_hotkeys(self) -> None:
        try:
            self.hotkey_listener = AppHotkeyListener(
                on_capture=lambda: self.capture_hotkey_pressed.emit(),
                on_offset_reference=lambda: self.offset_reference_hotkey_pressed.emit(),
                on_offset_target=lambda: self.offset_target_hotkey_pressed.emit(),
                on_start_automation=lambda: self.start_automation_hotkey_pressed.emit(),
                on_start_recording=lambda: self.recording_hotkey_pressed.emit(),
                on_stop_recording=lambda: self.recording_stop_hotkey_pressed.emit(),
                on_emergency_stop=lambda: self.emergency_hotkey_pressed.emit(),
            )
            self.hotkey_listener.start()
        except Exception as exc:
            self.hotkey_listener = None
            self.append_status(f"Global hotkeys unavailable: {exc}")

    def refresh_rule_list(self, selected_rule_id: str | None = None) -> None:
        selected_rule_id = selected_rule_id or self._selected_rule_id()
        self.rule_list.blockSignals(True)
        self.rule_list.clear()
        for rule in self.rules:
            item = QListWidgetItem(self._rule_label(rule))
            item.setData(Qt.UserRole, rule.rule_id)
            self.rule_list.addItem(item)
            if rule.rule_id == selected_rule_id:
                self.rule_list.setCurrentItem(item)
        self.rule_list.blockSignals(False)
        if self.rule_list.currentRow() < 0 and self.rule_list.count() > 0:
            self.rule_list.setCurrentRow(0)
        self._on_rule_selected(self.rule_list.currentItem(), None)

    def refresh_recordings(self) -> None:
        recordings = self.recording_store.list_recordings()
        self.rule_editor.set_recordings(recordings)
        self.append_status(f"Recordings refreshed: {len(recordings)} found")

    def delete_recording(self, filename: str) -> None:
        if not filename:
            self.append_status("No recording selected to delete.")
            return
        answer = QMessageBox.question(
            self,
            "Delete Recording",
            f"Delete recording file '{filename}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            path = self.recording_store.delete_recording(filename)
        except FileNotFoundError as exc:
            self.append_status(str(exc))
            path = self.recording_store.recording_path(filename)
        except Exception as exc:
            self.logger.exception("Failed to delete recording %s", filename)
            self.append_status(f"Failed to delete recording: {exc}")
            return

        cleared = 0
        for rule in self.rules:
            if rule.action.recording_file == filename:
                rule.action.recording_file = ""
                cleared += 1
        if cleared:
            self.rule_store.save_rules(self.rules)

        self.refresh_recordings()
        self.rule_editor.load_rule(self._selected_rule())
        self.append_status(f"Deleted recording: {path.name}. Cleared {cleared} rule reference(s).")

    def _prepare_for_recording(self) -> None:
        if self.scheduler.is_running:
            self.scheduler.stop()
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.resume_btn.setEnabled(False)
            self.append_status("Automation stopped before recording to avoid capturing app playback.")

    def _start_recording_from_hotkey(self) -> None:
        self.tabs.setCurrentWidget(self.recorder_widget)
        self.append_status("Shift+R pressed. Starting recording...")
        QTimer.singleShot(250, self.recorder_widget.start_recording)

    def _stop_recording_from_hotkey(self) -> None:
        if not self.recorder.is_recording:
            self.append_status("Shift+S pressed, but no recording is active.")
            return
        self.tabs.setCurrentWidget(self.recorder_widget)
        self.append_status("Shift+S pressed. Stopping recording...")
        QTimer.singleShot(
            150,
            lambda: self.recorder_widget.stop_recording(trim_stop_hotkey=True),
        )

    def _start_automation_from_hotkey(self) -> None:
        if self.scheduler.is_running:
            self.append_status("Shift+Delete pressed, but automation is already running.")
            return
        self.append_status("Shift+Delete pressed. Starting automation...")
        self.start_automation()

    def add_rule(self) -> None:
        rule = AutomationRule(rule_name=f"Rule {len(self.rules) + 1}")
        rule.add_condition(PixelCondition())
        self.rules.append(rule)
        self.rule_store.save_rules(self.rules)
        self.refresh_rule_list(rule.rule_id)
        self.append_status(f"Rule created: {rule.rule_name}")

    def duplicate_selected_rule(self) -> None:
        rule = self._selected_rule()
        if not rule:
            return
        new_rule = AutomationRule.from_dict(copy.deepcopy(rule.to_dict()))
        new_rule.rule_id = new_id("rule")
        new_rule.rule_name = f"{rule.rule_name} Copy"
        self.rules.append(new_rule)
        self.rule_store.save_rules(self.rules)
        self.refresh_rule_list(new_rule.rule_id)
        self.append_status(f"Rule duplicated: {new_rule.rule_name}")

    def delete_selected_rule(self) -> None:
        rule = self._selected_rule()
        if not rule:
            return
        answer = QMessageBox.question(
            self,
            "Delete Rule",
            f"Delete rule '{rule.rule_name}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.rules = [item for item in self.rules if item.rule_id != rule.rule_id]
        self.rule_store.save_rules(self.rules)
        self.refresh_rule_list()
        self.append_status(f"Rule deleted: {rule.rule_name}")

    def capture_selected_condition(self) -> None:
        if self.rule_editor.rule is None or not self.rule_editor.selected_condition_id():
            self.append_status("Select a condition row before pressing Shift+C.")
            return
        self.append_status("Capturing cursor position and pixel color...")
        thread = threading.Thread(target=self._capture_worker, name="PixelCapture", daemon=True)
        thread.start()

    def capture_offset_reference(self) -> None:
        rule = self.rule_editor.rule
        condition_id = self.rule_editor.selected_condition_id()
        if rule is None or not condition_id:
            self.append_status("Select a pointer condition row before pressing Shift+O.")
            return
        if not self.rule_editor.selected_uses_pointer():
            self.append_status("Shift+O offset capture only works when Use Pointer is checked.")
            return
        try:
            x, y = self.screen_capture.get_cursor_position()
        except Exception as exc:
            logging.getLogger("pixel_automation").exception("Offset reference capture failed")
            self.append_status(f"Offset reference capture failed: {exc}")
            return
        self._offset_reference = (rule.rule_id, condition_id, x, y)
        self.append_status(
            f"Offset reference captured at X={x} Y={y}. Move to the offset pixel, then press Shift+L."
        )

    def capture_offset_target(self) -> None:
        rule = self.rule_editor.rule
        condition_id = self.rule_editor.selected_condition_id()
        if rule is None or not condition_id:
            self.append_status("Select the same pointer condition row before pressing Shift+L.")
            return
        if not self.rule_editor.selected_uses_pointer():
            self.append_status("Shift+L offset capture only works when Use Pointer is checked.")
            return
        if self._offset_reference is None:
            self.append_status("Press Shift+O first to capture the offset reference point.")
            return

        ref_rule_id, ref_condition_id, ref_x, ref_y = self._offset_reference
        if ref_rule_id != rule.rule_id or ref_condition_id != condition_id:
            self.append_status(
                "Offset reference belongs to a different selected condition. Press Shift+O again for this row."
            )
            return

        self.append_status("Capturing offset target position and pixel color...")
        thread = threading.Thread(
            target=self._offset_capture_worker,
            args=(ref_rule_id, ref_condition_id, ref_x, ref_y),
            name="PixelOffsetCapture",
            daemon=True,
        )
        thread.start()

    def _capture_worker(self) -> None:
        try:
            capture = self.screen_capture.capture_cursor_pixel()
            self.capture_result.emit(capture)
        except Exception as exc:
            logging.getLogger("pixel_automation").exception("Pixel capture failed")
            self.capture_error.emit(str(exc))

    def _offset_capture_worker(
        self,
        rule_id: str,
        condition_id: str,
        reference_x: int,
        reference_y: int,
    ) -> None:
        try:
            capture = self.screen_capture.capture_cursor_pixel()
            self.offset_capture_result.emit((rule_id, condition_id, reference_x, reference_y, capture))
        except Exception as exc:
            logging.getLogger("pixel_automation").exception("Offset target capture failed")
            self.offset_capture_error.emit(str(exc))

    def _apply_capture_result(self, capture: CapturedPixel) -> None:
        if self.rule_editor.apply_capture(capture):
            self.append_status(
                f"Captured X={capture.x} Y={capture.y} RGB={capture.rgb} scale={capture.screen_resolution.scale_factor}x"
            )
        else:
            self.append_status("Capture ignored because no condition is selected.")

    def _apply_offset_capture_result(self, payload: object) -> None:
        rule_id, condition_id, reference_x, reference_y, capture = payload
        rule = self.rule_editor.rule
        if rule is None or rule.rule_id != rule_id or self.rule_editor.selected_condition_id() != condition_id:
            self.append_status("Offset capture ignored because the selected condition changed.")
            return
        if not self.rule_editor.selected_uses_pointer():
            self.append_status("Offset capture ignored because Use Pointer is no longer checked.")
            return
        if self.rule_editor.apply_offset_capture(reference_x, reference_y, capture):
            self._offset_reference = None
            self.append_status(
                f"Captured offset X={capture.x - reference_x} Y={capture.y - reference_y} RGB={capture.rgb} from target X={capture.x} Y={capture.y}"
            )
        else:
            self.append_status("Offset capture ignored because no pointer condition is selected.")

    def start_automation(self) -> None:
        if not self.rules:
            self.append_status("Create at least one rule before starting automation.")
            return
        self.refresh_recordings()
        missing = self._missing_recordings()
        if missing:
            for rule_name, filename, path in missing:
                self.append_status(
                    f"{rule_name}: Recording file is missing: {filename}. Checked: {path}"
                )
            self.append_status("Automation not started. Re-record or pick an existing recording.")
            return
        self.rule_store.save_rules(self.rules)
        self.scheduler.start(self.rules)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.pause_btn.setEnabled(True)
        self.resume_btn.setEnabled(False)

    def stop_automation(self) -> None:
        self.scheduler.stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.resume_btn.setEnabled(False)
        self.append_status("Automation stopped")

    def pause_automation(self) -> None:
        self.scheduler.pause()
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(True)

    def resume_automation(self) -> None:
        self.scheduler.resume()
        self.pause_btn.setEnabled(True)
        self.resume_btn.setEnabled(False)

    def emergency_stop(self) -> None:
        self.scheduler.emergency_stop()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.resume_btn.setEnabled(False)
        self.append_status("Emergency stop activated by Shift+Esc")

    def append_status(self, message: str) -> None:
        self.status_log.append(message)
        self.status_log.verticalScrollBar().setValue(self.status_log.verticalScrollBar().maximum())

    def _drain_runtime_events(self) -> None:
        while True:
            try:
                self.append_status(self.log_queue.get_nowait())
            except queue.Empty:
                break
        for event in self.scheduler.drain_events():
            self.append_status(event.message)

    def _on_rule_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self._offset_reference = None
        rule_id = current.data(Qt.UserRole) if current else None
        self.rule_editor.load_rule(self._rule_by_id(rule_id))

    def _on_rule_changed(self, changed_rule: AutomationRule) -> None:
        for index, rule in enumerate(self.rules):
            if rule.rule_id == changed_rule.rule_id:
                self.rules[index] = changed_rule
                break
        self.rule_store.save_rules(self.rules)
        current = self.rule_list.currentItem()
        if current and current.data(Qt.UserRole) == changed_rule.rule_id:
            current.setText(self._rule_label(changed_rule))

    def _selected_rule_id(self) -> str | None:
        item = self.rule_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _selected_rule(self) -> AutomationRule | None:
        return self._rule_by_id(self._selected_rule_id())

    def _rule_by_id(self, rule_id: str | None) -> AutomationRule | None:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        return None

    def _missing_recordings(self) -> list[tuple[str, str, str]]:
        missing: list[tuple[str, str, str]] = []
        for rule in self.rules:
            if not rule.enabled or rule.action.action_type != "recording":
                continue
            filename = rule.action.recording_file
            path = self.recording_store.recording_path(filename)
            if not self.recording_store.recording_exists(filename):
                missing.append((rule.rule_name, filename or "(none selected)", str(path)))
        return missing

    def _rule_label(self, rule: AutomationRule) -> str:
        state = "Active" if rule.enabled else "Disabled"
        return f"{rule.rule_name}  |  {state}  |  {rule.trigger_mode}"

    def closeEvent(self, event) -> None:  # noqa: N802
        self.scheduler.stop()
        if self.recorder.is_recording:
            self.recorder.cancel()
        if self.hotkey_listener is not None:
            self.hotkey_listener.stop()
        super().closeEvent(event)


def run_app() -> int:
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    return app.exec()
