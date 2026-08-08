from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.models import PixelCondition, ScreenResolution

logger = logging.getLogger("pixel_automation.screen")


@dataclass(frozen=True)
class CapturedPixel:
    x: int
    y: int
    rgb: tuple[int, int, int]
    screen_resolution: ScreenResolution
    captured_at: str

    def to_condition(self, condition_id: str | None = None) -> PixelCondition:
        return PixelCondition(
            condition_id=condition_id or PixelCondition().condition_id,
            x=self.x,
            y=self.y,
            rgb=self.rgb,
            captured_at=self.captured_at,
            screen_resolution=self.screen_resolution,
        )


class ScreenCapture:
    """Retina-aware single-pixel capture.

    GUI and pynput/pyautogui cursor positions are treated as logical points.
    mss often reports physical pixels on Retina displays, so the class computes
    a scale factor from screenshot dimensions divided by logical desktop size.
    """

    def __init__(self) -> None:
        self._thread_local = threading.local()
        self._screen_info_cache: ScreenResolution | None = None
        self._screen_info_cached_at = 0.0
        self._screen_info_lock = threading.RLock()
        self._screen_info_ttl_seconds = 2.0

    def _mss(self) -> Any:
        import mss

        ctx = getattr(self._thread_local, "mss_ctx", None)
        if ctx is None:
            ctx = mss.mss()
            self._thread_local.mss_ctx = ctx
        return ctx

    def _logical_size(self) -> tuple[int, int]:
        try:
            import pyautogui

            size = pyautogui.size()
            return int(size.width), int(size.height)
        except Exception:
            try:
                from AppKit import NSScreen  # type: ignore

                frame = NSScreen.mainScreen().frame()
                return int(frame.size.width), int(frame.size.height)
            except Exception:
                return (0, 0)

    def _physical_primary_size(self) -> tuple[int, int, int]:
        try:
            monitors = self._mss().monitors
            monitor = monitors[1] if len(monitors) > 1 else monitors[0]
            return int(monitor["width"]), int(monitor["height"]), max(1, len(monitors) - 1)
        except Exception:
            width, height = self._logical_size()
            return width, height, 1

    def get_screen_info(self, refresh: bool = False) -> ScreenResolution:
        now = time.monotonic()
        with self._screen_info_lock:
            if (
                not refresh
                and self._screen_info_cache is not None
                and now - self._screen_info_cached_at <= self._screen_info_ttl_seconds
            ):
                return self._screen_info_cache

        logical_w, logical_h = self._logical_size()
        physical_w, physical_h, display_count = self._physical_primary_size()
        scale_w = physical_w / logical_w if logical_w else 1.0
        scale_h = physical_h / logical_h if logical_h else 1.0
        scale = round(max(scale_w, scale_h), 2)
        info = ScreenResolution(
            width=logical_w or physical_w,
            height=logical_h or physical_h,
            scale_factor=scale,
            display_count=display_count,
            primary_display=f"{physical_w}x{physical_h} physical",
        )
        with self._screen_info_lock:
            self._screen_info_cache = info
            self._screen_info_cached_at = now
        return info

    def get_cursor_position(self) -> tuple[int, int]:
        try:
            import pyautogui

            pos = pyautogui.position()
            return int(pos.x), int(pos.y)
        except Exception:
            from pynput.mouse import Controller

            x, y = Controller().position
            return int(x), int(y)

    def _validate_logical_point(self, x: int, y: int, info: ScreenResolution) -> None:
        if x < 0 or y < 0 or x >= info.width or y >= info.height:
            raise ValueError(
                f"Pixel ({x}, {y}) is outside current screen bounds {info.width}x{info.height}."
            )

    def sample_pixel(self, x: int, y: int) -> tuple[int, int, int]:
        info = self.get_screen_info()
        self._validate_logical_point(x, y, info)

        try:
            mss_ctx = self._mss()
            monitor = mss_ctx.monitors[1] if len(mss_ctx.monitors) > 1 else mss_ctx.monitors[0]
            physical_x = int(monitor["left"] + round(x * info.scale_factor))
            physical_y = int(monitor["top"] + round(y * info.scale_factor))
            shot = mss_ctx.grab(
                {"left": physical_x, "top": physical_y, "width": 1, "height": 1}
            )
            r, g, b = shot.pixel(0, 0)[:3]
            return int(r), int(g), int(b)
        except Exception as exc:
            logger.debug("mss single-pixel capture failed, falling back to PIL: %s", exc)

        from PIL import ImageGrab

        scale = info.scale_factor
        physical_x = int(round(x * scale))
        physical_y = int(round(y * scale))
        image = ImageGrab.grab(
            bbox=(physical_x, physical_y, physical_x + 1, physical_y + 1),
            all_screens=True,
        )
        r, g, b = image.getpixel((0, 0))[:3]
        return int(r), int(g), int(b)

    def capture_cursor_pixel(self) -> CapturedPixel:
        x, y = self.get_cursor_position()
        rgb = self.sample_pixel(x, y)
        info = self.get_screen_info()
        captured = CapturedPixel(
            x=x,
            y=y,
            rgb=rgb,
            screen_resolution=info,
            captured_at=datetime.now().isoformat(timespec="seconds"),
        )
        logger.info("Captured pixel x=%s y=%s rgb=%s scale=%s", x, y, rgb, info.scale_factor)
        return captured
