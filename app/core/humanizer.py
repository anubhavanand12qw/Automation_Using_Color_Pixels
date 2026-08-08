from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class Humanizer:
    delay_jitter_ratio: float = 0.08
    min_delay: float = 0.005
    max_delay: float = 2.0

    def vary_delay(self, base_delay: float) -> float:
        base = max(0.0, float(base_delay))
        spread = max(0.01, base * self.delay_jitter_ratio)
        varied = random.uniform(max(0.0, base - spread), base + spread)
        return min(self.max_delay, max(self.min_delay if base > 0 else 0.0, varied))

    def key_interval(self, low: float = 0.04, high: float = 0.12) -> float:
        return random.uniform(low, high)

    def click_press_duration(self) -> float:
        return random.uniform(0.035, 0.09)
