from __future__ import annotations

from collections import Counter
from typing import Mapping


class MetricsService:
    def __init__(self) -> None:
        self._counters: Counter[str] = Counter()

    def increment(self, metric: str, value: int = 1) -> None:
        self._counters[metric] += value

    def snapshot(self) -> Mapping[str, int]:
        return dict(self._counters)

