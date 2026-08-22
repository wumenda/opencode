"""轻量 Prometheus 指标实现（stdlib，无 prometheus_client 依赖）。

暴露 Counter / Gauge / Histogram 与 Registry；render_prometheus 输出
Prometheus 文本展示格式 0.0.4。"""
from __future__ import annotations

import threading
from typing import Iterable


_DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)


class _Metric:
    kind = "untyped"

    def __init__(self, name: str, help_text: str, labels: Iterable[str] = ()) -> None:
        self.name = name
        self.help_text = help_text
        self.labels = tuple(labels)
        self._lock = threading.Lock()

    def _label_key(self, kwargs: dict[str, str]) -> tuple:
        return tuple(kwargs.get(label, "") for label in self.labels)

    def collect(self) -> list[tuple]:
        raise NotImplementedError


class Counter(_Metric):
    kind = "counter"

    def __init__(self, name, help_text, labels=()):
        super().__init__(name, help_text, labels)
        self._values: dict[tuple, float] = {}

    def inc(self, amount: float = 1.0, **label_kwargs) -> None:
        key = self._label_key(label_kwargs)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def collect(self):
        with self._lock:
            return [(self.name, self.labels, k, v, None) for k, v in self._values.items()]


class Gauge(_Metric):
    kind = "gauge"

    def __init__(self, name, help_text, labels=()):
        super().__init__(name, help_text, labels)
        self._values: dict[tuple, float] = {}

    def set(self, value: float, **label_kwargs) -> None:
        key = self._label_key(label_kwargs)
        with self._lock:
            self._values[key] = value

    def inc(self, amount: float = 1.0, **label_kwargs) -> None:
        key = self._label_key(label_kwargs)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, **label_kwargs) -> None:
        self.inc(-amount, **label_kwargs)

    def collect(self):
        with self._lock:
            return [(self.name, self.labels, k, v, None) for k, v in self._values.items()]


class Histogram(_Metric):
    kind = "histogram"

    def __init__(self, name, help_text, labels=(), buckets=_DEFAULT_BUCKETS):
        super().__init__(name, help_text, labels)
        self.buckets = tuple(sorted(buckets))
        self._counts: dict[tuple, list[int]] = {}
        self._sums: dict[tuple, float] = {}

    def observe(self, value: float, **label_kwargs) -> None:
        key = self._label_key(label_kwargs)
        with self._lock:
            if key not in self._counts:
                self._counts[key] = [0] * len(self.buckets)
                self._sums[key] = 0.0
            for i, b in enumerate(self.buckets):
                if value <= b:
                    self._counts[key][i] += 1
            self._sums[key] += value

    def collect(self):
        rows = []
        with self._lock:
            for key, counts in self._counts.items():
                total = sum(counts)
                s = self._sums.get(key, 0.0)
                rows.append((self.name, self.labels, key, float(total), list(zip(self.buckets, counts)), s))
        return rows


class Registry:
    def __init__(self) -> None:
        self._metrics: list[_Metric] = []
        self._lock = threading.Lock()

    def counter(self, name, help_text, labels=()) -> Counter:
        m = Counter(name, help_text, labels)
        with self._lock:
            self._metrics.append(m)
        return m

    def gauge(self, name, help_text, labels=()) -> Gauge:
        m = Gauge(name, help_text, labels)
        with self._lock:
            self._metrics.append(m)
        return m

    def histogram(self, name, help_text, labels=(), buckets=_DEFAULT_BUCKETS) -> Histogram:
        m = Histogram(name, help_text, labels, buckets)
        with self._lock:
            self._metrics.append(m)
        return m

    def collect_all(self) -> list[_Metric]:
        return list(self._metrics)


def _fmt_labels(labels: tuple, key: tuple, extra: dict[str, str] | None = None) -> str:
    if not labels and not extra:
        return ""
    parts = []
    for label, v in zip(labels, key):
        parts.append(f'{label}="{v}"')
    if extra:
        for k, v in extra.items():
            parts.append(f'{k}="{v}"')
    return "{" + ",".join(parts) + "}"


def render_prometheus(reg: Registry) -> str:
    lines: list[str] = []
    for m in reg.collect_all():
        lines.append(f"# HELP {m.name} {m.help_text}")
        lines.append(f"# TYPE {m.name} {m.kind}")
        for row in m.collect():
            if m.kind == "histogram":
                name, labels, key, value, buckets, sum_val = row
                for le, cnt in buckets:
                    le_str = f"{le:g}"
                    lines.append(f'{name}_bucket{_fmt_labels(labels, key, {"le": le_str})} {cnt}')
                lines.append(f'{name}_bucket{{le="+Inf"}} {int(value)}')
                lines.append(f'{name}_sum{_fmt_labels(labels, key)} {sum_val}')
                lines.append(f'{name}_count{_fmt_labels(labels, key)} {int(value)}')
            else:
                name, labels, key, value, _ = row
                lines.append(f"{name}{_fmt_labels(labels, key)} {float(value)}")
    return "\n".join(lines) + "\n"


# 全局 registry
REGISTRY = Registry()

# 业务指标
TASKS_TOTAL = REGISTRY.counter("pfd_tasks_total", "Total extraction tasks", labels=["task_type"])
TASKS_COMPLETED = REGISTRY.counter("pfd_tasks_completed_total", "Completed tasks", labels=["task_type"])
TASKS_FAILED = REGISTRY.counter("pfd_tasks_failed_total", "Failed tasks", labels=["task_type"])
TASK_DURATION = REGISTRY.histogram("pfd_task_duration_seconds", "Task duration", labels=["task_type"])
VLM_CALLS_TOTAL = REGISTRY.counter("pfd_vlm_calls_total", "VLM API calls", labels=["provider", "expert"])
VLM_FAILURES_TOTAL = REGISTRY.counter("pfd_vlm_failures_total", "VLM API failures", labels=["provider"])
VLM_LATENCY = REGISTRY.histogram("pfd_vlm_latency_seconds", "VLM call latency", labels=["provider"])
JOBS_PENDING = REGISTRY.gauge("pfd_jobs_pending", "Pending jobs in queue")
JOBS_RUNNING = REGISTRY.gauge("pfd_jobs_running", "Running jobs")
