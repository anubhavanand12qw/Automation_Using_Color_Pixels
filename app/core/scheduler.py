from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass

from app.core.action_executor import ActionExecutor
from app.core.models import AutomationRule
from app.core.rule_engine import RuleRuntimeState, evaluate_rule_conditions, rule_uses_cursor_position
from app.core.screen_capture import ScreenCapture

logger = logging.getLogger("pixel_automation.scheduler")


@dataclass
class SchedulerEvent:
    level: str
    message: str
    rule_id: str | None = None


class RuleWorker(threading.Thread):
    def __init__(
        self,
        rule: AutomationRule,
        screen_capture: ScreenCapture,
        action_executor: ActionExecutor,
        stop_event: threading.Event,
        pause_event: threading.Event,
        event_queue: "queue.Queue[SchedulerEvent]",
    ) -> None:
        super().__init__(name=f"RuleWorker-{rule.rule_id[:8]}", daemon=True)
        self.rule = rule
        self.screen_capture = screen_capture
        self.action_executor = action_executor
        self.stop_event = stop_event
        self.pause_event = pause_event
        self.event_queue = event_queue
        self.state = RuleRuntimeState()
        self.cursor_sensitive = rule_uses_cursor_position(rule)
        self._last_mouse_activity_version = action_executor.mouse_activity_version

    def run(self) -> None:
        self._emit("info", f"Rule monitoring started: {self.rule.rule_name}")
        while not self.stop_event.is_set():
            try:
                if self.pause_event.is_set() or not self.rule.enabled:
                    self.stop_event.wait(0.1)
                    continue

                if self.cursor_sensitive:
                    self._process_pointer_activity_events()
                else:
                    cursor_position = self.screen_capture.get_cursor_position()
                    self._evaluate_and_execute(cursor_position)

                interval = self._poll_interval()
                if self.cursor_sensitive:
                    self.action_executor.wait_for_mouse_activity(
                        self._last_mouse_activity_version,
                        interval,
                        self.stop_event,
                    )
                else:
                    self.stop_event.wait(interval)
            except Exception as exc:
                logger.exception("Rule worker crashed for %s", self.rule.rule_name)
                self._emit("error", f"{self.rule.rule_name}: {exc}")
                self.stop_event.wait(0.5)
        self._emit("info", f"Rule monitoring stopped: {self.rule.rule_name}")

    def _process_pointer_activity_events(self) -> None:
        latest_event = self.action_executor.latest_mouse_activity_since(
            self._last_mouse_activity_version
        )
        if latest_event is not None:
            self._last_mouse_activity_version = latest_event.version
            if latest_event.position is not None:
                self._evaluate_and_execute(latest_event.position)

        cursor_position = self.screen_capture.get_cursor_position()
        self._evaluate_and_execute(cursor_position)

    def _evaluate_and_execute(self, cursor_position: tuple[int, int]) -> None:
        result = evaluate_rule_conditions(
            self.rule,
            self.screen_capture.sample_pixel,
            lambda: cursor_position,
        )
        if self.state.should_trigger(self.rule, result):
            self._emit("info", f"Rule triggered: {self.rule.rule_name}")
            self.action_executor.execute(
                self.rule.action,
                self.rule.human_like,
                self.rule.click_randomness_px,
                cursor_position,
            )

    def _emit(self, level: str, message: str) -> None:
        logger.log(logging.ERROR if level == "error" else logging.INFO, message)
        self.event_queue.put(SchedulerEvent(level=level, message=message, rule_id=self.rule.rule_id))

    def _poll_interval(self) -> float:
        configured = max(0.001, self.rule.polling_interval_ms / 1000)
        if self.cursor_sensitive and self.rule.action.action_type in {
            "mouse_left_click",
            "mouse_right_click",
        }:
            return min(configured, 0.002)
        return configured


class AutomationScheduler:
    def __init__(
        self,
        screen_capture: ScreenCapture | None = None,
        action_executor: ActionExecutor | None = None,
    ) -> None:
        self.screen_capture = screen_capture or ScreenCapture()
        self.action_executor = action_executor or ActionExecutor()
        self.event_queue: "queue.Queue[SchedulerEvent]" = queue.Queue()
        self._workers: list[RuleWorker] = []
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._lock = threading.RLock()

    @property
    def is_running(self) -> bool:
        return any(worker.is_alive() for worker in self._workers)

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def start(self, rules: list[AutomationRule]) -> None:
        with self._lock:
            self.stop()
            self.action_executor.reset_stop_token()
            self._stop_event = threading.Event()
            self._pause_event = threading.Event()
            active_rules = [rule for rule in rules if rule.enabled]
            self.action_executor.set_fast_pointer_watch_enabled(
                any(
                    rule_uses_cursor_position(rule)
                    and rule.action.action_type in {"mouse_left_click", "mouse_right_click"}
                    for rule in active_rules
                )
            )
            self._workers = [
                RuleWorker(
                    rule,
                    self.screen_capture,
                    self.action_executor,
                    self._stop_event,
                    self._pause_event,
                    self.event_queue,
                )
                for rule in active_rules
            ]
            for worker in self._workers:
                worker.start()
            logger.info("Automation scheduler started with %s active rules", len(active_rules))
            self.event_queue.put(
                SchedulerEvent("info", f"Automation started with {len(active_rules)} active rules")
            )

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            for worker in self._workers:
                if worker.is_alive():
                    worker.join(timeout=1.5)
            self._workers = []
            self.action_executor.set_fast_pointer_watch_enabled(False)
            logger.info("Automation scheduler stopped")

    def pause(self) -> None:
        self._pause_event.set()
        self.event_queue.put(SchedulerEvent("info", "Automation paused"))

    def resume(self) -> None:
        self._pause_event.clear()
        self.event_queue.put(SchedulerEvent("info", "Automation resumed"))

    def emergency_stop(self) -> None:
        self._stop_event.set()
        self.action_executor.emergency_stop()
        self.stop()
        self.event_queue.put(SchedulerEvent("error", "Emergency stop activated"))

    def drain_events(self) -> list[SchedulerEvent]:
        events: list[SchedulerEvent] = []
        while True:
            try:
                events.append(self.event_queue.get_nowait())
            except queue.Empty:
                return events
