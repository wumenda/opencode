"""LLM 调用的重试与熔断（stdlib 实现）。"""
from __future__ import annotations

import random
import threading
import time
from functools import wraps
from typing import Callable, TypeVar

from src.core.infra.exceptions import APIError

T = TypeVar("T")

_RETRYABLE_MARKERS = ("429", "500", "502", "503", "504", "timeout", "timed out", "connection reset")


def is_retryable(err: BaseException) -> bool:
    if isinstance(err, APIError):
        msg = str(err).lower()
        return any(m in msg for m in _RETRYABLE_MARKERS)
    return False


def retry_with_backoff(max_attempts: int = 3, base_delay: float = 1.0, max_delay: float = 30.0,
                       logger=None) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """指数退避 + jitter。仅对 is_retryable 的错误重试。"""

    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            attempt = 0
            while True:
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    attempt += 1
                    if not is_retryable(e) or attempt >= max_attempts:
                        raise
                    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                    delay = delay + random.uniform(0, base_delay)
                    if logger:
                        logger.warning(
                            f"retryable error (attempt {attempt}/{max_attempts}): {e}; "
                            f"retry in {delay:.1f}s"
                        )
                    time.sleep(delay)

        return wrapper

    return deco


class CircuitOpenError(Exception):
    """熔断器开启时抛出。"""


class CircuitBreaker:
    """三态熔断器：closed → open → half_open → closed/open。

    - closed：正常放行，记录失败数
    - open：达到 failure_threshold 后开启，recovery_timeout 内拒绝所有请求
    - half_open：超时后放行一个探测请求；成功则关闭，失败则重新开启
    """

    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 30.0,
                 half_open_max: int = 1) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max = half_open_max
        self._failures = 0
        self._state = "closed"
        self._opened_at = 0.0
        self._half_open_inflight = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        return self._state

    def allow(self) -> bool:
        with self._lock:
            if self._state == "closed":
                return True
            if self._state == "open":
                if time.time() - self._opened_at >= self.recovery_timeout:
                    self._state = "half_open"
                    self._half_open_inflight = 0
                else:
                    return False
            if self._state == "half_open":
                if self._half_open_inflight < self.half_open_max:
                    self._half_open_inflight += 1
                    return True
                return False
            return False

    def guard(self) -> None:
        if not self.allow():
            raise CircuitOpenError(
                f"circuit open (failures={self._failures}, state={self._state})"
            )

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._state = "closed"
            self._half_open_inflight = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state == "half_open":
                self._state = "open"
                self._opened_at = time.time()
                self._half_open_inflight = 0
            elif self._failures >= self.failure_threshold:
                self._state = "open"
                self._opened_at = time.time()


# 按 provider 名复用熔断器
_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def get_breaker(provider: str, **kwargs) -> CircuitBreaker:
    with _breakers_lock:
        if provider not in _breakers:
            _breakers[provider] = CircuitBreaker(**kwargs)
        return _breakers[provider]
