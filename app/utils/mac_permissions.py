from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionStatus:
    name: str
    granted: bool | None
    reason: str


def is_macos() -> bool:
    return platform.system() == "Darwin"


def check_accessibility_permission() -> PermissionStatus:
    if not is_macos():
        return PermissionStatus("Accessibility", None, "Only required on macOS.")
    try:
        from ApplicationServices import AXIsProcessTrusted  # type: ignore

        granted = bool(AXIsProcessTrusted())
        return PermissionStatus(
            "Accessibility",
            granted,
            "Needed to control mouse and keyboard events.",
        )
    except Exception as exc:
        return PermissionStatus(
            "Accessibility",
            None,
            f"Unable to query automatically: {exc}",
        )


def check_screen_recording_permission() -> PermissionStatus:
    if not is_macos():
        return PermissionStatus("Screen Recording", None, "Only required on macOS.")
    try:
        from PIL import ImageGrab

        image = ImageGrab.grab(bbox=(0, 0, 1, 1), all_screens=True)
        granted = image.size == (1, 1)
        return PermissionStatus(
            "Screen Recording",
            granted,
            "Needed to read pixel colors from the screen.",
        )
    except Exception as exc:
        return PermissionStatus(
            "Screen Recording",
            False,
            f"Screenshot probe failed: {exc}",
        )


def check_input_monitoring_permission() -> PermissionStatus:
    if not is_macos():
        return PermissionStatus("Input Monitoring", None, "Only required on macOS.")
    return PermissionStatus(
        "Input Monitoring",
        None,
        "macOS does not expose a reliable public preflight check. Needed for global hotkeys and recording input.",
    )


def check_all_permissions() -> list[PermissionStatus]:
    return [
        check_accessibility_permission(),
        check_screen_recording_permission(),
        check_input_monitoring_permission(),
    ]


def open_privacy_settings() -> None:
    if not is_macos():
        return
    subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy"])

