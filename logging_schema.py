import logging
import uuid
from typing import Any


MAX_STRING_LENGTH = 500
MAX_COLLECTION_ITEMS = 10


def build_request_id() -> str:
    """生成单次请求级别的稳定 ID，便于同一 session 下多次请求回放。"""
    return f"req_{uuid.uuid4().hex[:12]}"


def summarize_text(value: str | None, *, max_length: int = MAX_STRING_LENGTH) -> str | None:
    """截断超长文本，避免主日志被整段大对象和超长回答淹没。"""
    if value is None:
        return None
    text = str(value)
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}...(truncated,{len(text)} chars)"


def summarize_quotes(quotes: list[dict] | None) -> dict[str, Any]:
    """提取报价结果摘要字段，供日志和后续可视化使用。"""
    items = quotes or []
    summary: dict[str, Any] = {
        "quote_count_total": len(items),
        "best_price_total": None,
        "best_unit_price": None,
        "best_carrier": None,
        "best_route": None,
        "best_route_type": None,
        "best_origin": None,
    }
    if not items:
        return summary

    best = min(items, key=lambda item: item.get("price_total") or float("inf"))
    raw = best.get("raw") or {}
    summary.update(
        {
            "best_price_total": best.get("price_total"),
            "best_unit_price": best.get("unit_price"),
            "best_carrier": best.get("carrier"),
            "best_route": best.get("route"),
            "best_route_type": best.get("route_type"),
            "best_origin": (raw.get("sfg") or "").lower() or None,
        }
    )
    return summary


def summarize_latest_quote_result(latest_quote_result: dict | None) -> dict[str, Any]:
    """把完整报价结果对象压成可用于日志平台的摘要。"""
    if not latest_quote_result:
        return {
            "search_mode": None,
            "multi_origin": False,
            "quote_count_exact": 0,
            "quote_count_similar": 0,
            "quote_count_total": 0,
            "best_price_total": None,
            "best_unit_price": None,
            "best_carrier": None,
            "best_route": None,
            "best_route_type": None,
            "best_origin": None,
        }

    query = latest_quote_result.get("query") or {}
    quotes = latest_quote_result.get("quotes") or []
    exact_quotes = latest_quote_result.get("exact_quotes") or quotes
    similar_quotes = latest_quote_result.get("similar_quotes") or []
    summary = summarize_quotes(quotes)
    summary.update(
        {
            "search_mode": latest_quote_result.get("search_mode"),
            "multi_origin": "," in str(query.get("sfg") or ""),
            "quote_count_exact": len(exact_quotes),
            "quote_count_similar": len(similar_quotes),
        }
    )
    return summary


def summarize_retrieved_docs(retrieved_docs: list[dict] | None) -> dict[str, Any]:
    """保留文档命中数量和来源摘要，不把整批 chunk 打进主日志。"""
    docs = retrieved_docs or []
    sources: list[str] = []
    for item in docs[:MAX_COLLECTION_ITEMS]:
        metadata = item.get("metadata") or {}
        source = metadata.get("source_file")
        if source:
            sources.append(str(source))
    return {
        "retrieved_docs_count": len(docs),
        "retrieved_doc_sources": sources,
    }


def _safe_value(value: Any) -> Any:
    """把日志字段限制在稳定、可 JSON 序列化、可前端消费的范围内。"""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return summarize_text(value)
    if isinstance(value, (list, tuple, set)):
        values = list(value)[:MAX_COLLECTION_ITEMS]
        return [_safe_value(item) for item in values]
    if isinstance(value, dict):
        return {str(key): _safe_value(val) for key, val in list(value.items())[:MAX_COLLECTION_ITEMS]}
    return summarize_text(repr(value))


def sanitize_event_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """统一清洗事件字段，保证文本日志和 JSONL 都从同一结构输出。"""
    return {str(key): _safe_value(value) for key, value in fields.items() if value is not None}


def log_event(
    logger: logging.Logger,
    *,
    level: int = logging.INFO,
    event: str,
    message: str | None = None,
    exc_info: bool = False,
    **fields: Any,
) -> None:
    """统一事件日志入口，后续文本日志和 JSONL 都基于这里的结构输出。"""
    payload = sanitize_event_fields(fields)
    logger.log(
        level,
        message or event,
        extra={
            "event_name": event,
            "event_payload": payload,
        },
        exc_info=exc_info,
    )
