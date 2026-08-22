"""共用评估指标定义。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MetricSet:
    """Precision / Recall / F1 for one category."""

    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        predicted = self.tp + self.fp
        return self.tp / predicted if predicted > 0 else 0.0

    @property
    def recall(self) -> float:
        gold = self.tp + self.fn
        return self.tp / gold if gold > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }
