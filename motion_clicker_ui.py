from __future__ import annotations

import queue
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from PIL import Image
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.action_executor import ActionExecutor
from app.core.models import ActionConfig
from app.core.screen_capture import ScreenCapture
from app.storage.recording_store import RecordingStore


DetectionType = Literal["pixel", "image"]
ActionType = Literal["none", "mouse_left_click", "mouse_right_click", "hotkey", "recording"]
AnchorMode = Literal["screen_static", "center_relative", "visual_anchor"]
RotationMode = Literal["none", "quarter", "eighth"]
ScaleMode = Literal["exact", "close", "wide"]


@dataclass(frozen=True)
class RectBox:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def is_empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2

    def normalized(self) -> "RectBox":
        x1 = min(self.x, self.right)
        y1 = min(self.y, self.bottom)
        x2 = max(self.x, self.right)
        y2 = max(self.y, self.bottom)
        return RectBox(x1, y1, x2 - x1, y2 - y1)

    def clipped_to(self, bounds: "RectBox") -> "RectBox":
        x1 = max(self.x, bounds.x)
        y1 = max(self.y, bounds.y)
        x2 = min(self.right, bounds.right)
        y2 = min(self.bottom, bounds.bottom)
        return RectBox(x1, y1, max(0, x2 - x1), max(0, y2 - y1))

    def contains_point(self, x: int, y: int) -> bool:
        return self.x <= x < self.right and self.y <= y < self.bottom

    def to_qrect(self) -> QRect:
        return QRect(self.x, self.y, self.width, self.height)

    def describe(self) -> str:
        return f"x={self.x}, y={self.y}, w={self.width}, h={self.height}"


@dataclass
class GeofenceState:
    source_rect: RectBox | None = None
    anchor_mode: AnchorMode = "center_relative"
    offset_x: int = 0
    offset_y: int = 0
    size: tuple[int, int] = (0, 0)
    created_at: str = ""

    def set_rect(
        self,
        rect: RectBox,
        anchor_mode: AnchorMode,
        screen_bounds: RectBox,
        anchor_position: tuple[int, int] | None = None,
    ) -> None:
        rect = rect.normalized().clipped_to(screen_bounds)
        self.source_rect = rect
        self.anchor_mode = anchor_mode
        self.size = (rect.width, rect.height)
        anchor_x, anchor_y = anchor_position or screen_bounds.center
        self.offset_x = rect.x - anchor_x
        self.offset_y = rect.y - anchor_y
        self.created_at = datetime.now().isoformat(timespec="seconds")

    def current_rect(
        self,
        screen_bounds: RectBox,
        anchor_position: tuple[int, int] | None = None,
    ) -> RectBox | None:
        if self.source_rect is None:
            return None
        if self.anchor_mode == "screen_static":
            return self.source_rect
        if self.anchor_mode == "visual_anchor":
            if anchor_position is None:
                return None
            anchor_x, anchor_y = anchor_position
        else:
            anchor_x, anchor_y = screen_bounds.center
        width, height = self.size
        return RectBox(anchor_x + self.offset_x, anchor_y + self.offset_y, width, height)

    def current_visible_rect(
        self,
        screen_bounds: RectBox,
        anchor_position: tuple[int, int] | None = None,
    ) -> RectBox | None:
        rect = self.current_rect(screen_bounds, anchor_position)
        if rect is None:
            return None
        return rect.clipped_to(screen_bounds)


@dataclass
class TemplateImage:
    image: Image.Image
    logical_rect: RectBox
    captured_at: str
    source_name: str = "screen capture"


@dataclass(frozen=True)
class TemplateSample:
    x: int
    y: int
    rgb: tuple[int, int, int]


@dataclass(frozen=True)
class TemplateVariant:
    image: Image.Image
    angle_degrees: int
    scale_factor: float
    samples: tuple[TemplateSample, ...]


@dataclass
class AgentConfig:
    name: str
    enabled: bool = True
    detection_type: DetectionType = "pixel"
    target_rgb: tuple[int, int, int] = (255, 0, 0)
    tolerance: int = 18
    minimum_matches: int = 8
    scan_stride: int = 3
    image_threshold: int = 14
    image_search_stride: int = 5
    template_rotation_mode: RotationMode = "quarter"
    template_scale_mode: ScaleMode = "close"
    action_type: ActionType = "mouse_left_click"
    hotkey: str = ""
    recording_file: str = ""
    recording_relative_to_pointer: bool = False
    playback_speed: float = 1.0
    polling_interval_ms: int = 25
    cooldown_seconds: float = 0.35
    click_at_match_center: bool = True
    template: TemplateImage | None = None
    _agent_id: str = field(default_factory=lambda: f"agent_{uuid.uuid4().hex[:10]}")


@dataclass(frozen=True)
class DetectionResult:
    found: bool
    target_x: int = 0
    target_y: int = 0
    count: int = 0
    score: float = 0.0
    message: str = ""


def build_template_variants(
    template: TemplateImage | None,
    rotation_mode: RotationMode,
    scale_mode: ScaleMode = "exact",
) -> list[TemplateVariant]:
    if template is None:
        return []
    if rotation_mode == "eighth":
        angles = [0, 45, 90, 135, 180, 225, 270, 315]
    elif rotation_mode == "quarter":
        angles = [0, 90, 180, 270]
    else:
        angles = [0]

    if scale_mode == "wide":
        scales = [0.75, 0.9, 1.0, 1.1, 1.25]
    elif scale_mode == "close":
        scales = [0.9, 1.0, 1.1]
    else:
        scales = [1.0]

    variants: list[TemplateVariant] = []
    base = template.image.convert("RGBA")
    resampling = getattr(Image, "Resampling", Image).BICUBIC
    for scale in scales:
        width = max(3, int(round(base.width * scale)))
        height = max(3, int(round(base.height * scale)))
        if scale == 1.0:
            scaled = base
        else:
            scaled = base.resize((width, height), resample=resampling)
        for angle in angles:
            if angle == 0:
                image = scaled
            else:
                image = scaled.rotate(-angle, resample=resampling, expand=True)
            rgb_image = image.convert("RGB")
            samples = _template_samples(image)
            if samples:
                variants.append(
                    TemplateVariant(
                        image=rgb_image,
                        angle_degrees=angle,
                        scale_factor=scale,
                        samples=tuple(samples),
                    )
                )
    return variants


def _template_samples(image: Image.Image) -> list[TemplateSample]:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    opaque_points: list[tuple[int, int, tuple[int, int, int]]] = []
    grid_step = max(1, min(rgba.width, rgba.height) // 22)
    for y in range(0, rgba.height, grid_step):
        for x in range(0, rgba.width, grid_step):
            r, g, b, a = pixels[x, y]
            if a >= 32:
                opaque_points.append((x, y, (int(r), int(g), int(b))))
    if not opaque_points:
        return []

    mean_r = sum(rgb[0] for _, _, rgb in opaque_points) / len(opaque_points)
    mean_g = sum(rgb[1] for _, _, rgb in opaque_points) / len(opaque_points)
    mean_b = sum(rgb[2] for _, _, rgb in opaque_points) / len(opaque_points)
    salient: list[TemplateSample] = []
    for x, y, rgb in opaque_points:
        distance = (
            abs(rgb[0] - mean_r)
            + abs(rgb[1] - mean_g)
            + abs(rgb[2] - mean_b)
        ) / 3
        if distance >= 12:
            salient.append(TemplateSample(x, y, rgb))

    if len(salient) >= 16:
        return salient
    return [TemplateSample(x, y, rgb) for x, y, rgb in opaque_points]


def match_template_in_region(
    image: Image.Image,
    rect: RectBox,
    screen_capture: ScreenCapture,
    variants: list[TemplateVariant],
    threshold: int,
    search_stride: int,
) -> DetectionResult:
    if not variants:
        return DetectionResult(False, message="no template variants")

    threshold = max(0, threshold)
    search_stride = max(1, search_stride)
    best_score = 9999.0
    best_xy: tuple[int, int] | None = None
    best_template: TemplateVariant | None = None
    image_pixels = image.load()

    for variant in variants:
        template = variant.image
        if template.width > image.width or template.height > image.height:
            continue
        for y in range(0, image.height - template.height + 1, search_stride):
            for x in range(0, image.width - template.width + 1, search_stride):
                score = template_variant_score(
                    image_pixels,
                    variant,
                    x,
                    y,
                    threshold,
                )
                if score < best_score:
                    best_score = score
                    best_xy = (x, y)
                    best_template = variant
                if score <= threshold:
                    break
            if best_score <= threshold:
                break
        if best_score <= threshold:
            break

    if best_xy is None or best_template is None or best_score > threshold:
        return DetectionResult(False, score=best_score)

    info = screen_capture.get_screen_info()
    scale = info.scale_factor
    target_x = rect.x + int(round((best_xy[0] + best_template.image.width / 2) / scale))
    target_y = rect.y + int(round((best_xy[1] + best_template.image.height / 2) / scale))
    return DetectionResult(
        True,
        target_x,
        target_y,
        score=best_score,
        message=(
            f"image {best_template.angle_degrees}deg "
            f"{best_template.scale_factor:.2f}x"
        ),
    )


def template_variant_score(
    image_pixels,
    variant: TemplateVariant,
    start_x: int,
    start_y: int,
    early_stop_score: float | None = None,
) -> float:
    total = 0
    samples = 0
    for sample in variant.samples:
        r1, g1, b1 = image_pixels[start_x + sample.x, start_y + sample.y][:3]
        r2, g2, b2 = sample.rgb
        total += abs(int(r1) - int(r2))
        total += abs(int(g1) - int(g2))
        total += abs(int(b1) - int(b2))
        samples += 3
        if early_stop_score is not None and samples >= 30:
            if total / samples > early_stop_score * 2.5:
                return total / samples
    return total / max(1, samples)


@dataclass
class VisualAnchorState:
    template: TemplateImage | None = None
    threshold: int = 14
    search_stride: int = 4
    search_radius_px: int = 320
    variants: list[TemplateVariant] = field(default_factory=list)
    last_center: tuple[int, int] | None = None
    last_checked_at: float = 0.0
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def set_template(self, template: TemplateImage) -> None:
        with self._lock:
            self.template = template
            self.variants = build_template_variants(template, "none", "exact")
            self.last_center = None
            self.last_checked_at = 0.0

    def locate(self, capture: "RegionCapture", screen_bounds: RectBox) -> tuple[int, int] | None:
        with self._lock:
            now = time.monotonic()
            if self.last_center is not None and now - self.last_checked_at <= 0.04:
                return self.last_center
            if self.template is None or not self.variants:
                return None
            if self.last_center is None:
                search_rect = screen_bounds
            else:
                radius = max(80, self.search_radius_px)
                search_rect = RectBox(
                    self.last_center[0] - radius,
                    self.last_center[1] - radius,
                    radius * 2,
                    radius * 2,
                ).clipped_to(screen_bounds)
            if search_rect.is_empty:
                return None
            image = capture.capture_region(search_rect)
            result = match_template_in_region(
                image,
                search_rect,
                capture.screen_capture,
                self.variants,
                self.threshold,
                self.search_stride,
            )
            self.last_checked_at = now
            if result.found:
                self.last_center = (result.target_x, result.target_y)
                return self.last_center
            if self.last_center is not None:
                full_image = capture.capture_region(screen_bounds)
                full_result = match_template_in_region(
                    full_image,
                    screen_bounds,
                    capture.screen_capture,
                    self.variants,
                    self.threshold,
                    self.search_stride,
                )
                if full_result.found:
                    self.last_center = (full_result.target_x, full_result.target_y)
                    return self.last_center
            return None


class RegionCapture:
    def __init__(self, screen_capture: ScreenCapture) -> None:
        self.screen_capture = screen_capture
        self._thread_local = threading.local()

    def _mss(self):
        import mss

        ctx = getattr(self._thread_local, "mss_ctx", None)
        if ctx is None:
            ctx = mss.mss()
            self._thread_local.mss_ctx = ctx
        return ctx

    def screen_bounds(self) -> RectBox:
        info = self.screen_capture.get_screen_info()
        return RectBox(0, 0, info.width, info.height)

    def capture_region(self, logical_rect: RectBox) -> Image.Image:
        info = self.screen_capture.get_screen_info()
        screen_bounds = RectBox(0, 0, info.width, info.height)
        rect = logical_rect.clipped_to(screen_bounds)
        if rect.is_empty:
            raise ValueError("Geofence is outside the visible screen.")

        scale = info.scale_factor
        mss_ctx = self._mss()
        monitor = mss_ctx.monitors[1] if len(mss_ctx.monitors) > 1 else mss_ctx.monitors[0]
        physical_rect = {
            "left": int(monitor["left"] + round(rect.x * scale)),
            "top": int(monitor["top"] + round(rect.y * scale)),
            "width": max(1, int(round(rect.width * scale))),
            "height": max(1, int(round(rect.height * scale))),
        }
        shot = mss_ctx.grab(physical_rect)
        return Image.frombytes("RGB", shot.size, shot.rgb)


class GeofenceOverlay(QWidget):
    rect_selected = Signal(object)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self._selected_rect: QRect | None = None
        self._hint = "Drag to select geofence. Enter locks, Esc cancels."

    def show_fullscreen_overlay(self) -> None:
        screen = QApplication.primaryScreen()
        geometry = screen.geometry() if screen else QRect(0, 0, 1280, 720)
        self.setGeometry(geometry)
        self._start = None
        self._current = None
        self._selected_rect = None
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        self._start = event.position().toPoint()
        self._current = self._start
        self._selected_rect = None
        self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._start is None:
            return
        self._current = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or self._start is None:
            return
        self._current = event.position().toPoint()
        self._selected_rect = QRect(self._start, self._current).normalized()
        self.update()

    def keyPressEvent(self, event) -> None:
        if event.key() in {Qt.Key_Escape, Qt.Key_C}:
            self.cancelled.emit()
            self.close()
            return
        if event.key() in {Qt.Key_Return, Qt.Key_Enter}:
            rect = self._active_rect()
            if rect is not None and rect.width() >= 3 and rect.height() >= 3:
                selected = RectBox(rect.x(), rect.y(), rect.width(), rect.height())
                self.close()
                QTimer.singleShot(120, lambda: self.rect_selected.emit(selected))
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 70))
        rect = self._active_rect()
        if rect is not None:
            painter.fillRect(rect, QColor(20, 180, 255, 45))
            painter.setPen(QPen(QColor(20, 180, 255), 2))
            painter.drawRect(rect)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(24, 34, self._hint)

    def _active_rect(self) -> QRect | None:
        if self._selected_rect is not None:
            return self._selected_rect
        if self._start is None or self._current is None:
            return None
        return QRect(self._start, self._current).normalized()


class TemplateOverlay(GeofenceOverlay):
    def __init__(self) -> None:
        super().__init__()
        self._hint = "Drag small target image. Enter captures template, Esc cancels."


class AgentWorker(threading.Thread):
    def __init__(
        self,
        agent: AgentConfig,
        geofence: GeofenceState,
        visual_anchor: VisualAnchorState,
        capture: RegionCapture,
        action_executor: ActionExecutor,
        stop_event: threading.Event,
        pause_event: threading.Event,
        event_queue: "queue.Queue[str]",
    ) -> None:
        super().__init__(name=f"GeofenceWorker-{agent.name[:16]}", daemon=True)
        self.agent = agent
        self.geofence = geofence
        self.visual_anchor = visual_anchor
        self.capture = capture
        self.action_executor = action_executor
        self.stop_event = stop_event
        self.pause_event = pause_event
        self.event_queue = event_queue
        self.last_action_at = 0.0
        self.template_variants = build_template_variants(
            agent.template,
            agent.template_rotation_mode,
            agent.template_scale_mode,
        )

    def run(self) -> None:
        self._log(f"{self.agent.name}: worker started")
        while not self.stop_event.is_set():
            try:
                if self.pause_event.is_set() or not self.agent.enabled:
                    self.stop_event.wait(0.1)
                    continue

                screen_bounds = self.capture.screen_bounds()
                anchor_position = None
                if self.geofence.anchor_mode == "visual_anchor":
                    anchor_position = self.visual_anchor.locate(self.capture, screen_bounds)
                    if anchor_position is None:
                        self._sleep_poll()
                        continue

                raw_rect = self.geofence.current_rect(screen_bounds, anchor_position)
                visible_rect = self.geofence.current_visible_rect(screen_bounds, anchor_position)
                if raw_rect is None or visible_rect is None:
                    self.stop_event.wait(0.1)
                    continue
                if visible_rect.is_empty:
                    self._sleep_poll()
                    continue

                image = self.capture.capture_region(visible_rect)
                result = self._detect(image, visible_rect)
                if result.found:
                    self._maybe_execute(result, visible_rect, screen_bounds)
            except Exception as exc:
                self._log(f"{self.agent.name}: {exc}")
                self.stop_event.wait(0.25)
            self._sleep_poll()
        self._log(f"{self.agent.name}: worker stopped")

    def _detect(self, image: Image.Image, rect: RectBox) -> DetectionResult:
        if self.agent.detection_type == "image":
            return self._detect_template(image, rect)
        return self._detect_pixel(image, rect)

    def _detect_pixel(self, image: Image.Image, rect: RectBox) -> DetectionResult:
        pixels = image.load()
        expected = self.agent.target_rgb
        tolerance = max(0, self.agent.tolerance)
        stride = max(1, self.agent.scan_stride)
        info = self.capture.screen_capture.get_screen_info()
        physical_step = max(1, int(round(stride * info.scale_factor)))

        count = 0
        min_x = image.width
        min_y = image.height
        max_x = 0
        max_y = 0
        for y in range(0, image.height, physical_step):
            for x in range(0, image.width, physical_step):
                actual = pixels[x, y][:3]
                if all(abs(int(a) - int(e)) <= tolerance for e, a in zip(expected, actual)):
                    count += 1
                    min_x = min(min_x, x)
                    min_y = min(min_y, y)
                    max_x = max(max_x, x)
                    max_y = max(max_y, y)

        if count < max(1, self.agent.minimum_matches):
            return DetectionResult(False, count=count)

        scale = info.scale_factor
        if self.agent.click_at_match_center:
            physical_x = (min_x + max_x) / 2
            physical_y = (min_y + max_y) / 2
        else:
            physical_x = min_x
            physical_y = min_y
        target_x = rect.x + int(round(physical_x / scale))
        target_y = rect.y + int(round(physical_y / scale))
        return DetectionResult(True, target_x, target_y, count=count, message="pixel")

    def _detect_template(self, image: Image.Image, rect: RectBox) -> DetectionResult:
        if self.agent.template is None:
            return DetectionResult(False, message="no template")
        return match_template_in_region(
            image,
            rect,
            self.capture.screen_capture,
            self.template_variants,
            self.agent.image_threshold,
            self.agent.image_search_stride,
        )

    def _maybe_execute(
        self,
        result: DetectionResult,
        visible_rect: RectBox,
        screen_bounds: RectBox,
    ) -> None:
        now = time.monotonic()
        if now - self.last_action_at < max(0.0, self.agent.cooldown_seconds):
            return
        if not visible_rect.contains_point(result.target_x, result.target_y):
            return
        if not screen_bounds.contains_point(result.target_x, result.target_y):
            return

        self.last_action_at = now
        self._log(
            f"{self.agent.name}: {result.message} found at "
            f"{result.target_x},{result.target_y}"
        )
        if self.agent.action_type == "none":
            return
        action_type = self.agent.action_type
        if action_type == "hotkey":
            action = ActionConfig(action_type="hotkey", hotkey=self.agent.hotkey)
            self.action_executor.execute(action, human_like=False)
            return
        if action_type == "recording":
            action = ActionConfig(
                action_type="recording",
                recording_file=self.agent.recording_file,
                recording_relative_to_pointer=self.agent.recording_relative_to_pointer,
                playback_speed=self.agent.playback_speed,
            )
            self.action_executor.execute(
                action,
                human_like=False,
                trigger_position=(result.target_x, result.target_y),
            )
            return
        action = ActionConfig(action_type=action_type)
        self.action_executor.execute(
            action,
            human_like=False,
            trigger_position=(result.target_x, result.target_y),
        )

    def _sleep_poll(self) -> None:
        interval = max(1, self.agent.polling_interval_ms) / 1000
        self.stop_event.wait(interval)

    def _log(self, message: str) -> None:
        self.event_queue.put(message)


class MainWindow(QMainWindow):
    capture_pixel_hotkey_pressed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Motion Clicker Geofence UI")
        self.resize(1080, 680)
        self.setMinimumSize(760, 520)
        self.screen_capture = ScreenCapture()
        self.region_capture = RegionCapture(self.screen_capture)
        self.action_executor = ActionExecutor()
        self.recording_store = RecordingStore()
        self.geofence = GeofenceState()
        self.visual_anchor = VisualAnchorState()
        self.agents: list[AgentConfig] = []
        self.workers: list[AgentWorker] = []
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.event_queue: "queue.Queue[str]" = queue.Queue()
        self.overlay: GeofenceOverlay | None = None
        self.template_overlay: TemplateOverlay | None = None
        self.anchor_overlay: TemplateOverlay | None = None
        self.hotkey_listener = None
        self._build_ui()
        self._wire_events()
        self.refresh_recordings()
        self._start_hotkeys()
        self._add_default_agent()

        self.timer = QTimer(self)
        self.timer.setInterval(160)
        self.timer.timeout.connect(self._drain_events)
        self.timer.start()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)

        top_row = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.stop_btn = QPushButton("Stop")
        self.pause_btn = QPushButton("Pause")
        self.resume_btn = QPushButton("Resume")
        self.stop_btn.setEnabled(False)
        self.resume_btn.setEnabled(False)
        top_row.addWidget(self.start_btn)
        top_row.addWidget(self.stop_btn)
        top_row.addWidget(self.pause_btn)
        top_row.addWidget(self.resume_btn)
        top_row.addStretch(1)
        root_layout.addLayout(top_row)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Agents"))
        self.agent_list = QListWidget()
        left_layout.addWidget(self.agent_list, 1)
        agent_buttons = QHBoxLayout()
        self.add_agent_btn = QPushButton("Add Agent")
        self.duplicate_agent_btn = QPushButton("Duplicate")
        self.delete_agent_btn = QPushButton("Delete")
        agent_buttons.addWidget(self.add_agent_btn)
        agent_buttons.addWidget(self.duplicate_agent_btn)
        agent_buttons.addWidget(self.delete_agent_btn)
        left_layout.addLayout(agent_buttons)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self._build_geofence_group(right_layout)
        self._build_detector_group(right_layout)
        self._build_action_group(right_layout)
        right_layout.addStretch(1)
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QScrollArea.NoFrame)
        self.settings_scroll.setWidget(right)
        splitter.addWidget(self.settings_scroll)
        splitter.setSizes([280, 900])
        root_layout.addWidget(splitter, 1)

        root_layout.addWidget(QLabel("Status"))
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(140)
        root_layout.addWidget(self.log)
        self.setCentralWidget(root)

        self.setStyleSheet(
            """
            QMainWindow { background: #f7f8fa; }
            QGroupBox { border: 1px solid #d6dbe3; border-radius: 6px; margin-top: 10px; padding: 8px; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            QPushButton { padding: 6px 10px; }
            QListWidget, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                border: 1px solid #cfd6df; border-radius: 5px; background: white;
            }
            QTextEdit { background: #111827; color: #e5e7eb; }
            """
        )

    def _build_geofence_group(self, layout: QVBoxLayout) -> None:
        group = QGroupBox("Geofence")
        form = QFormLayout(group)
        self.anchor_mode_combo = QComboBox()
        self.anchor_mode_combo.addItem("Center Relative", "center_relative")
        self.anchor_mode_combo.addItem("Visual Anchor", "visual_anchor")
        self.anchor_mode_combo.addItem("Static Screen", "screen_static")
        self.overlay_delay_spin = QDoubleSpinBox()
        self.overlay_delay_spin.setRange(0.2, 10.0)
        self.overlay_delay_spin.setSingleStep(0.2)
        self.overlay_delay_spin.setValue(1.5)
        self.overlay_delay_spin.setSuffix(" s")
        self.set_geofence_btn = QPushButton("Set Geofence")
        self.capture_anchor_btn = QPushButton("Capture Visual Anchor")
        self.geofence_label = QLabel("Not set")
        self.visible_geofence_label = QLabel("Not set")
        self.anchor_label = QLabel("No visual anchor")
        form.addRow("Anchor mode", self.anchor_mode_combo)
        form.addRow("Overlay delay", self.overlay_delay_spin)
        form.addRow("", self.set_geofence_btn)
        form.addRow("", self.capture_anchor_btn)
        form.addRow("Visual anchor", self.anchor_label)
        form.addRow("Saved", self.geofence_label)
        form.addRow("Visible clipped", self.visible_geofence_label)
        layout.addWidget(group)

    def _build_detector_group(self, layout: QVBoxLayout) -> None:
        group = QGroupBox("Detector")
        form = QFormLayout(group)
        self.agent_name_edit = QLineEdit()
        self.agent_enabled_check = QCheckBox("Enabled")
        self.detection_type_combo = QComboBox()
        self.detection_type_combo.addItem("Pixel color", "pixel")
        self.detection_type_combo.addItem("Image template", "image")
        self.capture_pixel_btn = QPushButton("Capture Pixel Under Mouse (Shift+C)")
        self.capture_template_btn = QPushButton("Capture Image Template")
        self.upload_template_btn = QPushButton("Upload Template Image")
        self.red_spin = self._rgb_spin()
        self.green_spin = self._rgb_spin()
        self.blue_spin = self._rgb_spin()
        rgb_row = QHBoxLayout()
        rgb_row.addWidget(QLabel("R"))
        rgb_row.addWidget(self.red_spin)
        rgb_row.addWidget(QLabel("G"))
        rgb_row.addWidget(self.green_spin)
        rgb_row.addWidget(QLabel("B"))
        rgb_row.addWidget(self.blue_spin)
        self.tolerance_spin = QSpinBox()
        self.tolerance_spin.setRange(0, 255)
        self.minimum_matches_spin = QSpinBox()
        self.minimum_matches_spin.setRange(1, 100000)
        self.scan_stride_spin = QSpinBox()
        self.scan_stride_spin.setRange(1, 50)
        self.image_threshold_spin = QSpinBox()
        self.image_threshold_spin.setRange(0, 255)
        self.image_search_stride_spin = QSpinBox()
        self.image_search_stride_spin.setRange(1, 50)
        self.rotation_mode_combo = QComboBox()
        self.rotation_mode_combo.addItem("No rotation", "none")
        self.rotation_mode_combo.addItem("4 directions", "quarter")
        self.rotation_mode_combo.addItem("8 directions", "eighth")
        self.scale_mode_combo = QComboBox()
        self.scale_mode_combo.addItem("Exact size", "exact")
        self.scale_mode_combo.addItem("Close scale", "close")
        self.scale_mode_combo.addItem("Wide scale", "wide")
        self.template_label = QLabel("No template")
        self.click_center_check = QCheckBox("Click center of matched blob/template")
        self.polling_spin = QSpinBox()
        self.polling_spin.setRange(1, 5000)
        self.polling_spin.setSuffix(" ms")
        self.cooldown_spin = QDoubleSpinBox()
        self.cooldown_spin.setRange(0.0, 3600.0)
        self.cooldown_spin.setSingleStep(0.05)
        self.cooldown_spin.setDecimals(2)
        self.cooldown_spin.setSuffix(" s")

        form.addRow("Name", self.agent_name_edit)
        form.addRow("", self.agent_enabled_check)
        form.addRow("Detection", self.detection_type_combo)
        form.addRow("", self.capture_pixel_btn)
        form.addRow("", self.capture_template_btn)
        form.addRow("", self.upload_template_btn)
        form.addRow("RGB", rgb_row)
        form.addRow("Tolerance", self.tolerance_spin)
        form.addRow("Minimum matches", self.minimum_matches_spin)
        form.addRow("Pixel scan stride", self.scan_stride_spin)
        form.addRow("Image threshold", self.image_threshold_spin)
        form.addRow("Image search stride", self.image_search_stride_spin)
        form.addRow("Rotation match", self.rotation_mode_combo)
        form.addRow("Scale match", self.scale_mode_combo)
        form.addRow("Template", self.template_label)
        form.addRow("", self.click_center_check)
        form.addRow("Polling", self.polling_spin)
        form.addRow("Cooldown", self.cooldown_spin)
        layout.addWidget(group)

    def _build_action_group(self, layout: QVBoxLayout) -> None:
        group = QGroupBox("Action")
        form = QFormLayout(group)
        self.action_type_combo = QComboBox()
        self.action_type_combo.addItem("None", "none")
        self.action_type_combo.addItem("Mouse Left Click", "mouse_left_click")
        self.action_type_combo.addItem("Mouse Right Click", "mouse_right_click")
        self.action_type_combo.addItem("Press Key / Hotkey / Type Text", "hotkey")
        self.action_type_combo.addItem("Select Recorded Sequence", "recording")
        self.hotkey_edit = QLineEdit()
        self.recording_combo = QComboBox()
        self.refresh_recordings_btn = QPushButton("Refresh Recordings")
        recording_row = QHBoxLayout()
        recording_row.addWidget(self.recording_combo, 1)
        recording_row.addWidget(self.refresh_recordings_btn)
        self.recording_relative_check = QCheckBox("Play recording relative to detected target")
        self.playback_speed_combo = QComboBox()
        for label, value in [
            ("0.05x", 0.05),
            ("0.1x", 0.1),
            ("0.2x", 0.2),
            ("0.5x", 0.5),
            ("1.0x", 1.0),
            ("1.5x", 1.5),
            ("2.0x", 2.0),
            ("5.0x", 5.0),
            ("10.0x", 10.0),
            ("20.0x", 20.0),
        ]:
            self.playback_speed_combo.addItem(label, value)
        form.addRow("Action", self.action_type_combo)
        form.addRow("Key / Hotkey / Text", self.hotkey_edit)
        form.addRow("Recording", recording_row)
        form.addRow("", self.recording_relative_check)
        form.addRow("Playback speed", self.playback_speed_combo)
        layout.addWidget(group)

    @staticmethod
    def _rgb_spin() -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, 255)
        return spin

    def _wire_events(self) -> None:
        self.start_btn.clicked.connect(self.start_workers)
        self.stop_btn.clicked.connect(self.stop_workers)
        self.pause_btn.clicked.connect(self.pause_workers)
        self.resume_btn.clicked.connect(self.resume_workers)
        self.set_geofence_btn.clicked.connect(self.begin_geofence_selection)
        self.capture_anchor_btn.clicked.connect(self.begin_anchor_capture)
        self.capture_pixel_btn.clicked.connect(self.capture_pixel)
        self.capture_template_btn.clicked.connect(self.begin_template_capture)
        self.upload_template_btn.clicked.connect(self.upload_template_image)
        self.refresh_recordings_btn.clicked.connect(self.refresh_recordings)
        self.capture_pixel_hotkey_pressed.connect(self.capture_pixel)
        self.add_agent_btn.clicked.connect(self.add_agent)
        self.duplicate_agent_btn.clicked.connect(self.duplicate_agent)
        self.delete_agent_btn.clicked.connect(self.delete_agent)
        self.agent_list.currentItemChanged.connect(self._selected_agent_changed)

        widgets = [
            self.agent_name_edit,
            self.agent_enabled_check,
            self.detection_type_combo,
            self.red_spin,
            self.green_spin,
            self.blue_spin,
            self.tolerance_spin,
            self.minimum_matches_spin,
            self.scan_stride_spin,
            self.image_threshold_spin,
            self.image_search_stride_spin,
            self.rotation_mode_combo,
            self.scale_mode_combo,
            self.click_center_check,
            self.polling_spin,
            self.cooldown_spin,
            self.action_type_combo,
            self.hotkey_edit,
            self.recording_combo,
            self.recording_relative_check,
            self.playback_speed_combo,
        ]
        for widget in widgets:
            if hasattr(widget, "textChanged"):
                widget.textChanged.connect(self._write_form_to_agent)
            if hasattr(widget, "stateChanged"):
                widget.stateChanged.connect(self._write_form_to_agent)
            if hasattr(widget, "currentIndexChanged"):
                widget.currentIndexChanged.connect(self._write_form_to_agent)
            if hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self._write_form_to_agent)
        self.detection_type_combo.currentIndexChanged.connect(self._update_detector_visibility)
        self.action_type_combo.currentIndexChanged.connect(self._update_action_visibility)

    def _add_default_agent(self) -> None:
        self.agents.append(
            AgentConfig(
                name="Agent 1",
                target_rgb=(255, 0, 0),
                tolerance=18,
                minimum_matches=8,
                image_threshold=14,
                polling_interval_ms=25,
                cooldown_seconds=0.35,
            )
        )
        self.refresh_agent_list(self.agents[0]._agent_id)

    def _start_hotkeys(self) -> None:
        try:
            from pynput.keyboard import GlobalHotKeys

            self.hotkey_listener = GlobalHotKeys(
                {
                    "<shift>+c": lambda: self.capture_pixel_hotkey_pressed.emit(),
                }
            )
            self.hotkey_listener.start()
            self.append_status("Global hotkey registered: Shift+C captures pixel under mouse.")
        except Exception as exc:
            self.hotkey_listener = None
            self.append_status(f"Global hotkey unavailable: {exc}")

    def refresh_recordings(self) -> None:
        current = self.recording_combo.currentData() if hasattr(self, "recording_combo") else None
        self.recording_combo.blockSignals(True)
        self.recording_combo.clear()
        try:
            recordings = self.recording_store.list_recordings()
        except Exception as exc:
            self.recording_combo.blockSignals(False)
            self.append_status(f"Recording refresh failed: {exc}")
            return
        for item in recordings:
            label = f"{item['name']} ({item['file']})"
            self.recording_combo.addItem(label, item["file"])
        if current:
            index = self.recording_combo.findData(current)
            self.recording_combo.setCurrentIndex(index if index >= 0 else -1)
        self.recording_combo.blockSignals(False)
        self.append_status(f"Recordings refreshed: {len(recordings)} found")

    def add_agent(self) -> None:
        self._write_form_to_agent()
        agent = AgentConfig(name=f"Agent {len(self.agents) + 1}")
        self.agents.append(agent)
        self.refresh_agent_list(agent._agent_id)
        self.append_status(f"Added {agent.name}")

    def duplicate_agent(self) -> None:
        current = self._selected_agent()
        if current is None:
            return
        clone = AgentConfig(
            name=f"{current.name} Copy",
            enabled=current.enabled,
            detection_type=current.detection_type,
            target_rgb=current.target_rgb,
            tolerance=current.tolerance,
            minimum_matches=current.minimum_matches,
            scan_stride=current.scan_stride,
            image_threshold=current.image_threshold,
            image_search_stride=current.image_search_stride,
            template_rotation_mode=current.template_rotation_mode,
            template_scale_mode=current.template_scale_mode,
            action_type=current.action_type,
            hotkey=current.hotkey,
            recording_file=current.recording_file,
            recording_relative_to_pointer=current.recording_relative_to_pointer,
            playback_speed=current.playback_speed,
            polling_interval_ms=current.polling_interval_ms,
            cooldown_seconds=current.cooldown_seconds,
            click_at_match_center=current.click_at_match_center,
            template=current.template,
        )
        self.agents.append(clone)
        self.refresh_agent_list(clone._agent_id)

    def delete_agent(self) -> None:
        current = self._selected_agent()
        if current is None:
            return
        if len(self.agents) == 1:
            QMessageBox.information(self, "Delete Agent", "At least one agent is required.")
            return
        self.agents = [agent for agent in self.agents if agent._agent_id != current._agent_id]
        self.refresh_agent_list(self.agents[0]._agent_id if self.agents else None)

    def refresh_agent_list(self, selected_agent_id: str | None = None) -> None:
        self.agent_list.blockSignals(True)
        self.agent_list.clear()
        for agent in self.agents:
            state = "on" if agent.enabled else "off"
            item = QListWidgetItem(f"{agent.name} | {state} | {agent.detection_type}")
            item.setData(Qt.UserRole, agent._agent_id)
            self.agent_list.addItem(item)
            if selected_agent_id == agent._agent_id:
                self.agent_list.setCurrentItem(item)
        self.agent_list.blockSignals(False)
        if self.agent_list.currentRow() < 0 and self.agent_list.count() > 0:
            self.agent_list.setCurrentRow(0)
        self._selected_agent_changed(self.agent_list.currentItem(), None)

    def _selected_agent_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        agent_id = current.data(Qt.UserRole) if current else None
        agent = self._agent_by_id(agent_id)
        self._load_agent(agent)

    def _load_agent(self, agent: AgentConfig | None) -> None:
        enabled = agent is not None
        for widget in [
            self.agent_name_edit,
            self.agent_enabled_check,
            self.detection_type_combo,
            self.capture_pixel_btn,
            self.capture_template_btn,
            self.upload_template_btn,
            self.red_spin,
            self.green_spin,
            self.blue_spin,
            self.tolerance_spin,
            self.minimum_matches_spin,
            self.scan_stride_spin,
            self.image_threshold_spin,
            self.image_search_stride_spin,
            self.rotation_mode_combo,
            self.scale_mode_combo,
            self.click_center_check,
            self.polling_spin,
            self.cooldown_spin,
            self.action_type_combo,
            self.hotkey_edit,
            self.recording_combo,
            self.refresh_recordings_btn,
            self.recording_relative_check,
            self.playback_speed_combo,
        ]:
            widget.blockSignals(True)
            widget.setEnabled(enabled)
        if agent is not None:
            self.agent_name_edit.setText(agent.name)
            self.agent_enabled_check.setChecked(agent.enabled)
            self.detection_type_combo.setCurrentIndex(
                max(0, self.detection_type_combo.findData(agent.detection_type))
            )
            self.red_spin.setValue(agent.target_rgb[0])
            self.green_spin.setValue(agent.target_rgb[1])
            self.blue_spin.setValue(agent.target_rgb[2])
            self.tolerance_spin.setValue(agent.tolerance)
            self.minimum_matches_spin.setValue(agent.minimum_matches)
            self.scan_stride_spin.setValue(agent.scan_stride)
            self.image_threshold_spin.setValue(agent.image_threshold)
            self.image_search_stride_spin.setValue(agent.image_search_stride)
            self.rotation_mode_combo.setCurrentIndex(
                max(0, self.rotation_mode_combo.findData(agent.template_rotation_mode))
            )
            self.scale_mode_combo.setCurrentIndex(
                max(0, self.scale_mode_combo.findData(agent.template_scale_mode))
            )
            self.click_center_check.setChecked(agent.click_at_match_center)
            self.polling_spin.setValue(agent.polling_interval_ms)
            self.cooldown_spin.setValue(agent.cooldown_seconds)
            self.action_type_combo.setCurrentIndex(
                max(0, self.action_type_combo.findData(agent.action_type))
            )
            self.hotkey_edit.setText(agent.hotkey)
            recording_index = self.recording_combo.findData(agent.recording_file)
            self.recording_combo.setCurrentIndex(recording_index if recording_index >= 0 else -1)
            self.recording_relative_check.setChecked(agent.recording_relative_to_pointer)
            speed_index = self.playback_speed_combo.findData(agent.playback_speed)
            self.playback_speed_combo.setCurrentIndex(speed_index if speed_index >= 0 else 4)
            self.template_label.setText(
                "No template"
                if agent.template is None
                else f"{agent.template.source_name} | {agent.template.image.width}x{agent.template.image.height} @ {agent.template.captured_at}"
            )
        for widget in [
            self.agent_name_edit,
            self.agent_enabled_check,
            self.detection_type_combo,
            self.capture_pixel_btn,
            self.capture_template_btn,
            self.upload_template_btn,
            self.red_spin,
            self.green_spin,
            self.blue_spin,
            self.tolerance_spin,
            self.minimum_matches_spin,
            self.scan_stride_spin,
            self.image_threshold_spin,
            self.image_search_stride_spin,
            self.rotation_mode_combo,
            self.scale_mode_combo,
            self.click_center_check,
            self.polling_spin,
            self.cooldown_spin,
            self.action_type_combo,
            self.hotkey_edit,
            self.recording_combo,
            self.refresh_recordings_btn,
            self.recording_relative_check,
            self.playback_speed_combo,
        ]:
            widget.blockSignals(False)
        self._update_detector_visibility()
        self._update_action_visibility()

    def _write_form_to_agent(self, *_args) -> None:
        agent = self._selected_agent()
        if agent is None:
            return
        agent.name = self.agent_name_edit.text().strip() or "Agent"
        agent.enabled = self.agent_enabled_check.isChecked()
        agent.detection_type = self.detection_type_combo.currentData()
        agent.target_rgb = (
            self.red_spin.value(),
            self.green_spin.value(),
            self.blue_spin.value(),
        )
        agent.tolerance = self.tolerance_spin.value()
        agent.minimum_matches = self.minimum_matches_spin.value()
        agent.scan_stride = self.scan_stride_spin.value()
        agent.image_threshold = self.image_threshold_spin.value()
        agent.image_search_stride = self.image_search_stride_spin.value()
        agent.template_rotation_mode = self.rotation_mode_combo.currentData()
        agent.template_scale_mode = self.scale_mode_combo.currentData()
        agent.click_at_match_center = self.click_center_check.isChecked()
        agent.polling_interval_ms = self.polling_spin.value()
        agent.cooldown_seconds = float(self.cooldown_spin.value())
        agent.action_type = self.action_type_combo.currentData()
        agent.hotkey = self.hotkey_edit.text().strip()
        agent.recording_file = self.recording_combo.currentData() or ""
        agent.recording_relative_to_pointer = self.recording_relative_check.isChecked()
        agent.playback_speed = float(self.playback_speed_combo.currentData() or 1.0)
        current = self.agent_list.currentItem()
        if current:
            state = "on" if agent.enabled else "off"
            current.setText(f"{agent.name} | {state} | {agent.detection_type}")

    def _selected_agent(self) -> AgentConfig | None:
        item = self.agent_list.currentItem()
        return self._agent_by_id(item.data(Qt.UserRole) if item else None)

    def _agent_by_id(self, agent_id: str | None) -> AgentConfig | None:
        for agent in self.agents:
            if agent._agent_id == agent_id:
                return agent
        return None

    def begin_geofence_selection(self) -> None:
        self.append_status(
            f"Geofence picker opens in {self.overlay_delay_spin.value():.1f}s. "
            "Switch to target window, then drag area and press Enter."
        )
        self.showMinimized()
        QTimer.singleShot(int(self.overlay_delay_spin.value() * 1000), self._show_geofence_overlay)

    def _show_geofence_overlay(self) -> None:
        self.overlay = GeofenceOverlay()
        self.overlay.rect_selected.connect(self._set_geofence_from_overlay)
        self.overlay.cancelled.connect(lambda: self._finish_overlay("Geofence selection cancelled."))
        self.overlay.show_fullscreen_overlay()

    def _set_geofence_from_overlay(self, rect: RectBox) -> None:
        screen_bounds = self.region_capture.screen_bounds()
        anchor_mode = self.anchor_mode_combo.currentData()
        anchor_position = None
        if anchor_mode == "visual_anchor":
            anchor_position = self.visual_anchor.locate(self.region_capture, screen_bounds)
            anchor_position = anchor_position or self.visual_anchor.last_center
            if anchor_position is None:
                self._finish_overlay("Capture a visual anchor before setting a visual-anchor geofence.")
                return
        self.geofence.set_rect(rect, anchor_mode, screen_bounds, anchor_position)
        self._update_geofence_labels()
        self._finish_overlay("Geofence locked.")

    def begin_anchor_capture(self) -> None:
        self.append_status(
            f"Visual anchor picker opens in {self.overlay_delay_spin.value():.1f}s. "
            "Drag a stable player marker/healthbar/character detail and press Enter."
        )
        self.showMinimized()
        QTimer.singleShot(int(self.overlay_delay_spin.value() * 1000), self._show_anchor_overlay)

    def _show_anchor_overlay(self) -> None:
        self.anchor_overlay = TemplateOverlay()
        self.anchor_overlay._hint = "Drag player anchor/marker. Enter captures, Esc cancels."
        self.anchor_overlay.rect_selected.connect(self._capture_anchor_from_overlay)
        self.anchor_overlay.cancelled.connect(lambda: self._finish_overlay("Visual anchor capture cancelled."))
        self.anchor_overlay.show_fullscreen_overlay()

    def _capture_anchor_from_overlay(self, rect: RectBox) -> None:
        try:
            screen_bounds = self.region_capture.screen_bounds()
            logical_rect = rect.normalized().clipped_to(screen_bounds)
            image = self.region_capture.capture_region(logical_rect)
            anchor = TemplateImage(
                image=image,
                logical_rect=logical_rect,
                captured_at=datetime.now().isoformat(timespec="seconds"),
                source_name="visual anchor",
            )
            self.visual_anchor.set_template(anchor)
            self.visual_anchor.last_center = logical_rect.center
            self.anchor_label.setText(
                f"{logical_rect.describe()} | {image.width}x{image.height}"
            )
            self._finish_overlay("Visual anchor captured.")
        except Exception as exc:
            self._finish_overlay(f"Visual anchor capture failed: {exc}")

    def _finish_overlay(self, message: str) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.append_status(message)

    def begin_template_capture(self) -> None:
        agent = self._selected_agent()
        if agent is None:
            return
        self._write_form_to_agent()
        self.append_status(
            f"Template picker opens in {self.overlay_delay_spin.value():.1f}s. "
            "Switch to target window, drag target image and press Enter."
        )
        self.showMinimized()
        QTimer.singleShot(int(self.overlay_delay_spin.value() * 1000), self._show_template_overlay)

    def _show_template_overlay(self) -> None:
        self.template_overlay = TemplateOverlay()
        self.template_overlay.rect_selected.connect(self._capture_template_from_overlay)
        self.template_overlay.cancelled.connect(lambda: self._finish_overlay("Template capture cancelled."))
        self.template_overlay.show_fullscreen_overlay()

    def _capture_template_from_overlay(self, rect: RectBox) -> None:
        agent = self._selected_agent()
        if agent is None:
            self._finish_overlay("No agent selected.")
            return
        try:
            screen_bounds = self.region_capture.screen_bounds()
            logical_rect = rect.normalized().clipped_to(screen_bounds)
            image = self.region_capture.capture_region(logical_rect)
            agent.template = TemplateImage(
                image=image,
                logical_rect=logical_rect,
                captured_at=datetime.now().isoformat(timespec="seconds"),
                source_name="screen capture",
            )
            self.template_label.setText(
                f"{agent.template.source_name} | {image.width}x{image.height} @ {agent.template.captured_at}"
            )
            self.detection_type_combo.setCurrentIndex(self.detection_type_combo.findData("image"))
            self._write_form_to_agent()
            self._finish_overlay("Template captured.")
        except Exception as exc:
            self._finish_overlay(f"Template capture failed: {exc}")

    def upload_template_image(self) -> None:
        agent = self._selected_agent()
        if agent is None:
            return
        filename, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Upload Template Image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*)",
        )
        if not filename:
            return
        try:
            image = Image.open(filename).convert("RGBA")
        except Exception as exc:
            self.append_status(f"Template upload failed: {exc}")
            return

        source_name = Path(filename).name
        agent.template = TemplateImage(
            image=image,
            logical_rect=RectBox(0, 0, image.width, image.height),
            captured_at=datetime.now().isoformat(timespec="seconds"),
            source_name=source_name,
        )
        self.detection_type_combo.setCurrentIndex(self.detection_type_combo.findData("image"))
        self.template_label.setText(
            f"{source_name} | {image.width}x{image.height} @ {agent.template.captured_at}"
        )
        self._write_form_to_agent()
        self.append_status(f"Template uploaded: {source_name} ({image.width}x{image.height})")

    def capture_pixel(self) -> None:
        agent = self._selected_agent()
        if agent is None:
            return
        try:
            pixel = self.screen_capture.capture_cursor_pixel()
            self.red_spin.setValue(pixel.rgb[0])
            self.green_spin.setValue(pixel.rgb[1])
            self.blue_spin.setValue(pixel.rgb[2])
            self.detection_type_combo.setCurrentIndex(self.detection_type_combo.findData("pixel"))
            self._write_form_to_agent()
            self.append_status(f"Captured pixel {pixel.rgb} at {pixel.x},{pixel.y}")
        except Exception as exc:
            self.append_status(f"Pixel capture failed: {exc}")

    def start_workers(self) -> None:
        self._write_form_to_agent()
        if self.geofence.source_rect is None:
            QMessageBox.information(self, "Geofence Required", "Set a geofence before starting.")
            return
        if self.geofence.anchor_mode == "visual_anchor" and self.visual_anchor.template is None:
            QMessageBox.information(
                self,
                "Visual Anchor Required",
                "Capture a visual anchor before starting a visual-anchor geofence.",
            )
            return
        active_agents = [agent for agent in self.agents if agent.enabled]
        if not active_agents:
            QMessageBox.information(self, "No Active Agents", "Enable at least one agent.")
            return
        for agent in active_agents:
            if agent.detection_type == "image" and agent.template is None:
                QMessageBox.information(
                    self,
                    "Template Required",
                    f"{agent.name} uses image detection but has no template.",
                )
                return
            if agent.action_type == "hotkey" and not agent.hotkey:
                QMessageBox.information(
                    self,
                    "Hotkey Required",
                    f"{agent.name} uses hotkey action but the key/hotkey field is empty.",
                )
                return
            if agent.action_type == "recording":
                if not agent.recording_file:
                    QMessageBox.information(
                        self,
                        "Recording Required",
                        f"{agent.name} uses recorded sequence action but no recording is selected.",
                    )
                    return
                if not self.recording_store.recording_exists(agent.recording_file):
                    QMessageBox.information(
                        self,
                        "Recording Missing",
                        f"{agent.name} selected recording was not found: {agent.recording_file}",
                    )
                    return

        self.stop_workers(silent=True)
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.workers = [
            AgentWorker(
                agent,
                self.geofence,
                self.visual_anchor,
                self.region_capture,
                self.action_executor,
                self.stop_event,
                self.pause_event,
                self.event_queue,
            )
            for agent in active_agents
        ]
        for worker in self.workers:
            worker.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.pause_btn.setEnabled(True)
        self.resume_btn.setEnabled(False)
        self.append_status(f"Started {len(self.workers)} agent(s).")

    def stop_workers(self, silent: bool = False) -> None:
        self.stop_event.set()
        for worker in self.workers:
            if worker.is_alive():
                worker.join(timeout=1.2)
        self.workers = []
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.resume_btn.setEnabled(False)
        if not silent:
            self.append_status("Stopped.")

    def pause_workers(self) -> None:
        self.pause_event.set()
        self.pause_btn.setEnabled(False)
        self.resume_btn.setEnabled(True)
        self.append_status("Paused.")

    def resume_workers(self) -> None:
        self.pause_event.clear()
        self.pause_btn.setEnabled(True)
        self.resume_btn.setEnabled(False)
        self.append_status("Resumed.")

    def closeEvent(self, event) -> None:
        self.stop_workers(silent=True)
        if self.hotkey_listener is not None:
            try:
                self.hotkey_listener.stop()
            except Exception:
                pass
            self.hotkey_listener = None
        super().closeEvent(event)

    def _update_geofence_labels(self) -> None:
        screen_bounds = self.region_capture.screen_bounds()
        anchor_position = (
            self.visual_anchor.last_center
            if self.geofence.anchor_mode == "visual_anchor"
            else None
        )
        current = self.geofence.current_rect(screen_bounds, anchor_position)
        visible = self.geofence.current_visible_rect(screen_bounds, anchor_position)
        self.geofence_label.setText("Not set" if current is None else current.describe())
        self.visible_geofence_label.setText(
            "Not set"
            if visible is None
            else ("outside screen" if visible.is_empty else visible.describe())
        )

    def _update_detector_visibility(self) -> None:
        is_image = self.detection_type_combo.currentData() == "image"
        for widget in [
            self.image_threshold_spin,
            self.image_search_stride_spin,
            self.rotation_mode_combo,
            self.scale_mode_combo,
            self.template_label,
            self.capture_template_btn,
            self.upload_template_btn,
        ]:
            widget.setEnabled(is_image)
        for widget in [
            self.red_spin,
            self.green_spin,
            self.blue_spin,
            self.tolerance_spin,
            self.minimum_matches_spin,
            self.scan_stride_spin,
            self.capture_pixel_btn,
        ]:
            widget.setEnabled(not is_image)

    def _update_action_visibility(self) -> None:
        action_type = self.action_type_combo.currentData()
        is_hotkey = action_type == "hotkey"
        is_recording = action_type == "recording"
        self.hotkey_edit.setEnabled(is_hotkey)
        self.recording_combo.setEnabled(is_recording)
        self.refresh_recordings_btn.setEnabled(is_recording)
        self.recording_relative_check.setEnabled(is_recording)
        self.playback_speed_combo.setEnabled(is_recording)

    def _drain_events(self) -> None:
        self._update_geofence_labels()
        while True:
            try:
                self.append_status(self.event_queue.get_nowait())
            except queue.Empty:
                break

    def append_status(self, message: str) -> None:
        self.log.append(message)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())


def run_app() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run_app())
