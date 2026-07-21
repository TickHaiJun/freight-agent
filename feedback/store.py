"""JSONL 反馈事件存储及既有请求日志摘要读取。"""

import json
import logging
import threading
from pathlib import Path
from typing import Any

from config import settings

logger = logging.getLogger(__name__)
_WRITE_LOCK = threading.Lock()


class FeedbackStore:
    """单实例场景下安全追加 JSONL，并提供只读链路摘要查询。"""

    def __init__(self, feedback_dir: str | Path | None = None) -> None:
        self.feedback_dir = Path(feedback_dir or settings.chat_feedback_dir)

    @property
    def path(self) -> Path:
        return self.feedback_dir / f"{settings.chat_feedback_file_prefix}.jsonl"

    def append_event(self, event: dict[str, Any]) -> None:
        self.feedback_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        # 一次锁内完成单行写入，避免同一进程的并发请求互相穿插。
        with _WRITE_LOCK, self.path.open("a", encoding="utf-8") as file:
            file.write(f"{line}\n")
            file.flush()

    def find_request_trace(self, request_id: str | None) -> dict[str, Any]:
        snapshot: dict[str, Any] = {"trace_found": False}
        if not request_id:
            return snapshot

        log_dir = Path(settings.app_log_dir)
        pattern = f"{settings.app_log_file_prefix}-app.jsonl*"
        for log_path in sorted(log_dir.glob(pattern), reverse=True):
            self._merge_trace_events(log_path, request_id, snapshot)

        return snapshot

    @staticmethod
    def _merge_trace_events(log_path: Path, request_id: str, snapshot: dict[str, Any]) -> None:
        try:
            with log_path.open("r", encoding="utf-8") as file:
                for line in file:
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning("跳过无法解析的应用 JSONL 行: %s", log_path)
                        continue
                    if event.get("request_id") != request_id:
                        continue
                    FeedbackStore._merge_event(event, snapshot)
        except FileNotFoundError:
            return

    @staticmethod
    def _merge_event(event: dict[str, Any], snapshot: dict[str, Any]) -> None:
        snapshot["trace_found"] = True
        event_name = event.get("event")
        if event_name == "agent_finished":
            snapshot.update({
                "intent": event.get("intent"),
                "query_ready": event.get("query_ready"),
                "tool_status": "succeeded" if event.get("query_ready") else None,
                "retrieved_docs_count": event.get("retrieved_docs_count"),
            })
        elif event_name == "request_completed":
            snapshot.update({
                "total_elapsed_ms": event.get("total_elapsed_ms"),
                "origin": event.get("best_origin"),
                "destination": event.get("best_route"),
                "retrieved_docs_count": event.get("retrieved_docs_count"),
            })
        elif event_name == "request_failed":
            snapshot.update({
                "error_type": event.get("error_type"),
                "error_stage": event.get("error_stage"),
                "total_elapsed_ms": event.get("total_elapsed_ms"),
            })
