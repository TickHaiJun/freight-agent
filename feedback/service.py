"""聊天反馈服务编排：先落盘，再做可失败的 AI 增强。"""

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import settings
from logging_schema import log_event, summarize_text

from .models import ChatFeedbackRequest, ChatFeedbackResponse, FeedbackAiAnalysis
from .prompts import FEEDBACK_ANALYSIS_SYSTEM, FEEDBACK_ANALYSIS_USER
from .sanitize import sanitize_text
from .store import FeedbackStore

logger = logging.getLogger(__name__)
_BEIJING_TZ = timezone(timedelta(hours=8))


def _now_beijing() -> str:
    return datetime.now(_BEIJING_TZ).isoformat(timespec="seconds")


def _build_conversation_snapshot(request: ChatFeedbackRequest) -> dict[str, Any]:
    if not request.allow_context_for_review:
        # 未授权时不留存问答文本，仅保留显式标记供平台解释数据缺口。
        return {"context_available_for_review": False}
    return {
        "context_available_for_review": True,
        "user_question": sanitize_text(request.user_question, 2000),
        "assistant_answer": sanitize_text(request.assistant_answer, settings.chat_feedback_max_answer_length),
        "conversation_excerpt": [sanitize_text(item, 2000) for item in request.conversation_excerpt or []],
    }


def _parse_json_response(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    return json.loads(cleaned)


def analyze_feedback(event: dict[str, Any]) -> FeedbackAiAnalysis:
    """同步调用模型；由上层放到线程并施加超时，避免阻塞事件循环。"""
    llm = ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0,
    )
    response = llm.invoke([
        SystemMessage(content=FEEDBACK_ANALYSIS_SYSTEM),
        HumanMessage(content=FEEDBACK_ANALYSIS_USER.format(
            dissatisfaction_types=event["user_feedback"]["dissatisfaction_types"],
            feedback_text=event["user_feedback"]["feedback_text"],
            conversation_snapshot=event["conversation_snapshot"],
            trace_snapshot=event["trace_snapshot"],
        )),
    ])
    return FeedbackAiAnalysis.model_validate(_parse_json_response(str(response.content or "")))


async def submit_feedback(request: ChatFeedbackRequest, store: FeedbackStore | None = None) -> ChatFeedbackResponse:
    """保存反馈原文后再分析，任何 AI 异常都不会影响已落盘的原始记录。"""
    store = store or FeedbackStore()
    feedback_id = f"fb_{uuid.uuid4().hex}"
    trace_snapshot = store.find_request_trace(request.request_id)
    event = {
        "record_type": "feedback",
        "schema_version": 1,
        "feedback_id": feedback_id,
        "created_at": _now_beijing(),
        "source": "web_chat",
        "session_id": request.session_id,
        "request_id": request.request_id,
        "user_feedback": {
            "dissatisfaction_types": [item.value for item in request.dissatisfaction_types],
            "feedback_text": sanitize_text(request.feedback_text, settings.chat_feedback_max_text_length),
            "allow_context_for_review": request.allow_context_for_review,
        },
        "conversation_snapshot": _build_conversation_snapshot(request),
        "trace_snapshot": trace_snapshot,
        "ai_analysis": {"status": "pending"},
        "workflow": {"status": "new", "owner": None},
    }
    store.append_event(event)
    log_event(logger, event="chat_feedback_received", feedback_id=feedback_id,
              session_id=request.session_id, request_id=request.request_id,
              dissatisfaction_type_count=len(request.dissatisfaction_types), trace_found=trace_snapshot["trace_found"])

    if not settings.chat_feedback_ai_enabled:
        return ChatFeedbackResponse(feedback_id=feedback_id, ai_analysis_status="pending")

    started = time.perf_counter()
    try:
        analysis = await asyncio.wait_for(
            asyncio.to_thread(analyze_feedback, event),
            timeout=settings.chat_feedback_ai_timeout_seconds,
        )
        enrichment = {
            "record_type": "feedback_enrichment",
            "schema_version": 1,
            "feedback_id": feedback_id,
            "created_at": _now_beijing(),
            "ai_analysis": {"status": "completed", "model": settings.deepseek_model,
                            "analyzed_at": _now_beijing(), **analysis.model_dump(mode="json")},
        }
        store.append_event(enrichment)
        log_event(logger, event="chat_feedback_ai_completed", feedback_id=feedback_id,
                  business_domain=analysis.business_domain.value, pipeline_stage=analysis.pipeline_stage.value,
                  severity=analysis.severity.value, confidence=analysis.confidence,
                  elapsed_ms=round((time.perf_counter() - started) * 1000, 2))
        return ChatFeedbackResponse(feedback_id=feedback_id, ai_analysis_status="completed")
    except Exception as exc:
        # AI 分析失败只补充失败事件；原始 feedback 已成功落盘，不能向上抛出导致用户误以为未提交。
        error_type = type(exc).__name__
        enrichment = {
            "record_type": "feedback_enrichment",
            "schema_version": 1,
            "feedback_id": feedback_id,
            "created_at": _now_beijing(),
            "ai_analysis": {"status": "failed", "analyzed_at": _now_beijing(),
                            "error_type": error_type, "error_message": summarize_text(str(exc), max_length=200)},
        }
        try:
            store.append_event(enrichment)
        except Exception:
            logger.exception("反馈 AI 失败事件写入失败: feedback_id=%s", feedback_id)
        log_event(logger, level=logging.WARNING, event="chat_feedback_ai_failed", feedback_id=feedback_id,
                  error_type=error_type, elapsed_ms=round((time.perf_counter() - started) * 1000, 2))
        return ChatFeedbackResponse(feedback_id=feedback_id, ai_analysis_status="failed")
