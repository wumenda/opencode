import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from logging import LogRecord
from pathlib import Path
from typing import Optional, Union

# 东八区（UTC+8），用于日志时间戳，不依赖系统时区
_CN_TZ = timezone(timedelta(hours=8))


def _cn_converter(seconds: float):
    """将 epoch 秒转换为东八区 struct_time，供 ``logging.Formatter.converter`` 使用。"""
    return time.gmtime(seconds + 8 * 3600)


class JsonFormatter(logging.Formatter):
    """结构化 JSON 日志 formatter。"""

    _STD_ATTRS = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "asctime", "taskName",
    }

    def format(self, record: LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=_CN_TZ).strftime(
                "%Y-%m-%dT%H:%M:%S"
            )
            + f".{int(record.msecs):03d}",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for k, v in vars(record).items():
            if k not in self._STD_ATTRS and not k.startswith("_"):
                payload[k] = v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(
    level: Union[str, int] = "INFO",
    log_file: Optional[Path] = None,
    verbose: bool = False,
) -> None:
    if isinstance(level, str):
        level = level.upper()

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)

    use_json = os.environ.get("LOG_FORMAT", "text").lower() == "json"
    if use_json:
        formatter: logging.Formatter = JsonFormatter()
    elif verbose:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # 固定东八区时间戳，不依赖系统时区
    formatter.converter = _cn_converter

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    root_logger.addHandler(console_handler)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


class LoggerMixin:
    @property
    def logger(self) -> logging.Logger:
        if not hasattr(self, "_logger"):
            self._logger = get_logger(f"{self.__class__.__module__}.{self.__class__.__name__}")
        return self._logger
