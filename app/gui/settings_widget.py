from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.screen_capture import ScreenCapture
from app.utils.mac_permissions import check_all_permissions, open_privacy_settings


class SettingsWidget(QWidget):
    def __init__(self, screen_capture: ScreenCapture) -> None:
        super().__init__()
        self.screen_capture = screen_capture
        layout = QVBoxLayout(self)
        self.screen_group = QGroupBox("Screen")
        self.screen_form = QFormLayout(self.screen_group)
        self.resolution_label = QLabel()
        self.scale_label = QLabel()
        self.display_count_label = QLabel()
        self.primary_label = QLabel()
        self.screen_form.addRow("Screen Resolution", self.resolution_label)
        self.screen_form.addRow("Scale Factor", self.scale_label)
        self.screen_form.addRow("Display Count", self.display_count_label)
        self.screen_form.addRow("Primary Display", self.primary_label)
        layout.addWidget(self.screen_group)

        self.permission_group = QGroupBox("macOS Permissions")
        self.permission_layout = QVBoxLayout(self.permission_group)
        self.open_settings_btn = QPushButton("Open Privacy & Security Settings")
        self.refresh_btn = QPushButton("Refresh Settings")
        self.permission_layout.addWidget(self.refresh_btn)
        self.permission_layout.addWidget(self.open_settings_btn)
        layout.addWidget(self.permission_group)
        layout.addStretch(1)

        self.refresh_btn.clicked.connect(self.refresh)
        self.open_settings_btn.clicked.connect(open_privacy_settings)
        self.refresh()

    def refresh(self) -> None:
        info = self.screen_capture.get_screen_info()
        self.resolution_label.setText(f"{info.width} x {info.height}")
        self.scale_label.setText(f"{info.scale_factor}x")
        self.display_count_label.setText(str(info.display_count))
        self.primary_label.setText(info.primary_display)

        while self.permission_layout.count() > 2:
            item = self.permission_layout.takeAt(2)
            if item.widget():
                item.widget().deleteLater()
        for status in check_all_permissions():
            value = "Unknown" if status.granted is None else ("Granted" if status.granted else "Missing")
            label = QLabel(f"{status.name}: {value} - {status.reason}")
            label.setWordWrap(True)
            self.permission_layout.addWidget(label)

