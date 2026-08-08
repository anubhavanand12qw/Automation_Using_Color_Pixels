from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class MouseActivity:
    version: int
    position: tuple[int, int] | None
    created_at: float


class MouseActivityNotifier:
    def __init__(self, max_events: int = 10000) -> None:
        self._condition = threading.Condition()
        self._version = 0
        self._events: deque[MouseActivity] = deque(maxlen=max_events)

    @property
    def version(self) -> int:
        with self._condition:
            return self._version

    def notify(self, position: tuple[int, int] | None = None) -> None:
        with self._condition:
            self._version += 1
            normalized_position = (
                (int(position[0]), int(position[1])) if position is not None else None
            )
            self._events.append(
                MouseActivity(
                    version=self._version,
                    position=normalized_position,
                    created_at=time.monotonic(),
                )
            )
            self._condition.notify_all()

    def events_since(self, last_seen_version: int) -> list[MouseActivity]:
        with self._condition:
            return [event for event in self._events if event.version > last_seen_version]

    def latest_event_since(self, last_seen_version: int) -> MouseActivity | None:
        with self._condition:
            for event in reversed(self._events):
                if event.version > last_seen_version:
                    return event
            return None

    def wait_for_change(
        self,
        last_seen_version: int,
        timeout: float,
        stop_event: threading.Event,
    ) -> None:
        deadline = max(0.0, float(timeout))
        with self._condition:
            if self._version != last_seen_version or stop_event.is_set():
                return
            self._condition.wait_for(
                lambda: self._version != last_seen_version or stop_event.is_set(),
                timeout=deadline,
            )
