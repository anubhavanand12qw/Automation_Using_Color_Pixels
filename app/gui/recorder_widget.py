from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from app.core.recorder import InputRecorder


class RecorderWidget(QWidget):
    recording_start_requested = Signal()
    recording_saved = Signal(str)
    status_message = Signal(str)

    def __init__(self, recorder: InputRecorder) -> None:
        super().__init__()
        self.recorder = recorder
        layout = QVBoxLayout(self)
        group = QGroupBox("Recorder")
        group_layout = QVBoxLayout(group)
        row = QHBoxLayout()
        self.name_edit = QLineEdit("automation_sequence")
        self.start_btn = QPushButton("Start Recording (Shift+R)")
        self.stop_btn = QPushButton("Stop Recording (Shift+S)")
        self.count_label = QLabel("Events: 0")
        row.addWidget(QLabel("Name"))
        row.addWidget(self.name_edit, 1)
        row.addWidget(self.start_btn)
        row.addWidget(self.stop_btn)
        row.addWidget(self.count_label)
        group_layout.addLayout(row)
        layout.addWidget(group)
        self.stop_btn.setEnabled(False)

        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._refresh_count)
        self.start_btn.clicked.connect(self.start_recording)
        self.stop_btn.clicked.connect(self.stop_recording)

    def start_recording(self) -> None:
        if self.recorder.is_recording:
            self.status_message.emit("Recording is already active")
            return
        try:
            self.recording_start_requested.emit()
            self.recorder.start(self.name_edit.text())
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.timer.start()
            self.status_message.emit("Recording started")
        except Exception as exc:
            self.status_message.emit(f"Recording failed to start: {exc}")

    def _start(self) -> None:
        self.start_recording()

    def stop_recording(self, trim_stop_hotkey: bool = False) -> None:
        if not self.recorder.is_recording:
            self.status_message.emit("No active recording to stop")
            return
        try:
            filename = self.recorder.stop_and_save(trim_stop_hotkey=trim_stop_hotkey)
            self.recording_saved.emit(filename)
            self.status_message.emit(f"Recording saved: {filename}")
        except Exception as exc:
            self.status_message.emit(f"Recording failed to save: {exc}")
        finally:
            self.timer.stop()
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self._refresh_count()

    def _stop(self) -> None:
        self.stop_recording()

    def _refresh_count(self) -> None:
        self.count_label.setText(f"Events: {self.recorder.event_count}")
