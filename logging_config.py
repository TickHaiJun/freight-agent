import json
import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from config import settings


class TextEventFormatter(logging.Formatter):
    """人读文本日志，保留标准字段并拼接稳定的 key=value 摘要。"""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        event_name = getattr(record, "event_name", None)
        payload = getattr(record, "event_payload", None) or {}
        parts = []
        if event_name:
            parts.append(f"event={event_name}")
        for key in sorted(payload.keys()):
            parts.append(f"{key}={payload[key]}")
        if not parts:
            return base
        return f"{base} | {' | '.join(parts)}"


class JsonLineFormatter(logging.Formatter):
    """机器读 JSON Line，供后续日志平台和 AI 分析直接消费。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "event_payload", None) or {}
        data = {
            "ts": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": settings.app_log_service_name,
            "event": getattr(record, "event_name", None),
            **payload,
        }
        if record.exc_info:
            data["stacktrace"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def _build_timed_handler(path: Path, level: int, formatter: logging.Formatter) -> TimedRotatingFileHandler:
    handler = TimedRotatingFileHandler(
        filename=str(path),
        when="midnight",
        backupCount=settings.app_log_backup_days,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def setup_logging() -> None:
    """初始化控制台、文本文件、JSONL 文件和错误日志。"""
    if getattr(setup_logging, "_configured", False):
        return

    log_dir = Path(settings.app_log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    text_formatter = TextEventFormatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    json_formatter = JsonLineFormatter()

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.app_log_level.upper(), logging.INFO))
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(root_logger.level)
    console_handler.setFormatter(text_formatter)
    root_logger.addHandler(console_handler)

    app_log_path = log_dir / f"{settings.app_log_file_prefix}-app.log"
    root_logger.addHandler(_build_timed_handler(app_log_path, root_logger.level, text_formatter))

    if settings.app_log_json_enabled:
        app_json_path = log_dir / f"{settings.app_log_file_prefix}-app.jsonl"
        root_logger.addHandler(_build_timed_handler(app_json_path, root_logger.level, json_formatter))

    error_log_path = log_dir / f"{settings.app_log_file_prefix}-error.log"
    error_handler = _build_timed_handler(error_log_path, logging.ERROR, text_formatter)
    root_logger.addHandler(error_handler)

    setup_logging._configured = True
