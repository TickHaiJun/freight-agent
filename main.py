import asyncio
import json
import logging
import os
import time
from copy import deepcopy

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from config import settings
from feedback import ChatFeedbackRequest, ChatFeedbackResponse, submit_feedback
from graph.agent import agent
from graph.state import AgentState
from graph.time_utils import get_current_beijing_date_str
from logging_config import setup_logging
from logging_schema import (
    build_request_id,
    log_event,
    summarize_latest_quote_result,
    summarize_retrieved_docs,
)

# 禁止访问内网地址时走系统代理，避免本地内网服务请求被错误转发
os.environ.setdefault("NO_PROXY", "192.168.0.0/16,127.0.0.1,localhost")

setup_logging()
logger = logging.getLogger(__name__)

# 结果分析依赖“最近一次完整报价结果”留在后端内存态中。
# 这里先用进程内字典按 session_id 持有，满足当前单服务实例场景。
SESSION_RUNTIME_STORE: dict[str, dict] = {}

app = FastAPI(title="AI 运价 Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str
    message: str
    context: dict | None = None
    reset_quote_context: bool = False


def _build_context_data(final_state: AgentState, request_id: str | None = None) -> dict:
    """保持前端依赖的 context 回传协议不变。"""
    return {
        "sfg": final_state.get("sfg"),
        "mdg": final_state.get("mdg"),
        "inputWeight": final_state.get("inputWeight"),
        "inputVol": final_state.get("inputVol"),
        "hbrq": final_state.get("hbrq"),
        "hbrqBegin": final_state.get("hbrqBegin"),
        "hbrqEnd": final_state.get("hbrqEnd"),
        "flightType": final_state.get("flightType"),
        "packageType": final_state.get("packageType"),
        "cargoType": final_state.get("cargoType"),
        "twoCode": final_state.get("twoCode"),
        "gid": final_state.get("gid"),
        "query_completed": final_state.get("query_completed", False),
        "pending_clarify_slot": final_state.get("pending_clarify_slot"),
        "pending_clarify_message": final_state.get("pending_clarify_message"),
        "pending_clarify_context": final_state.get("pending_clarify_context"),
        "pending_action_type": final_state.get("pending_action_type"),
        "pending_action_prompt": final_state.get("pending_action_prompt"),
        "pending_action_payload": final_state.get("pending_action_payload"),
        "pending_action_retry_count": final_state.get("pending_action_retry_count", 0),
        "pending_reuse_confirmation": final_state.get("pending_reuse_confirmation", False),
        "pending_reuse_message": final_state.get("pending_reuse_message"),
        "reuse_candidate_context": final_state.get("reuse_candidate_context"),
        "result_display_mode": final_state.get("result_display_mode"),
        # 可选字段，旧前端忽略即可；新前端用它精确关联某一轮回答的反馈。
        "request_id": request_id,
    }


@app.post("/api/chat")
async def chat(request: ChatRequest, http_request: Request):
    """聊天主接口，保持现有 SSE 协议不变。"""

    async def generate():
        request_started = time.perf_counter()
        stored_runtime = deepcopy(SESSION_RUNTIME_STORE.get(request.session_id, {}))
        current_beijing_date = get_current_beijing_date_str()
        request_id = build_request_id()

        if request.reset_quote_context:
            stored_runtime = {
                "quote_result_active": False,
                "latest_quote_result": None,
            }

        initial_state: AgentState = {
            "messages": [HumanMessage(content=request.message)],
            "session_id": request.session_id,
            "request_id": request_id,
            "intent": None,
            "query_subtype": None,
            "response_mode": None,
            "quantity_mode": None,
            "sfg": request.context.get("sfg") if request.context else None,
            "mdg": request.context.get("mdg") if request.context else None,
            "inputWeight": request.context.get("inputWeight") if request.context else None,
            "inputVol": request.context.get("inputVol") if request.context else None,
            "hbrq": request.context.get("hbrq") if request.context else None,
            "hbrqBegin": request.context.get("hbrqBegin") if request.context else None,
            "hbrqEnd": request.context.get("hbrqEnd") if request.context else None,
            "flightType": request.context.get("flightType") if request.context else None,
            "packageType": request.context.get("packageType") if request.context else None,
            "cargoType": request.context.get("cargoType") if request.context else None,
            "twoCode": request.context.get("twoCode") if request.context else None,
            "gid": request.context.get("gid") if request.context else None,
            "missing_slots": [],
            "query_ready": False,
            "query_completed": request.context.get("query_completed", False) if request.context else False,
            "reset_quote_context": request.reset_quote_context,
            "current_beijing_date": current_beijing_date,
            "time_clarify_message": None,
            "pending_clarify_slot": request.context.get("pending_clarify_slot") if request.context else None,
            "pending_clarify_message": request.context.get("pending_clarify_message") if request.context else None,
            "pending_clarify_context": request.context.get("pending_clarify_context") if request.context else None,
            "pending_action_type": request.context.get("pending_action_type") if request.context else None,
            "pending_action_prompt": request.context.get("pending_action_prompt") if request.context else None,
            "pending_action_payload": request.context.get("pending_action_payload") if request.context else None,
            "pending_action_retry_count": request.context.get("pending_action_retry_count", 0) if request.context else 0,
            "pending_reuse_confirmation": request.context.get("pending_reuse_confirmation", False) if request.context else False,
            "pending_reuse_message": request.context.get("pending_reuse_message") if request.context else None,
            "reuse_candidate_context": request.context.get("reuse_candidate_context") if request.context else None,
            "reuse_confirmation_decision": None,
            "result_display_mode": request.context.get("result_display_mode") if request.context else None,
            "api_result": None,
            "api_error": None,
            "quote_result_active": stored_runtime.get("quote_result_active", False),
            "latest_quote_result": stored_runtime.get("latest_quote_result"),
            "result_analysis_intent": None,
            "result_analysis_filters": None,
            "result_reference_field": None,
            "result_reference_request": None,
            "support_info_kind": None,
            "rag_query": None,
            "retrieval_query": None,
            "retrieval_filters": None,
            "retrieved_docs": None,
            "rag_answer": None,
        }

        final_state: AgentState | None = None
        try:
            log_event(
                logger,
                event="request_started",
                session_id=request.session_id,
                request_id=request_id,
                client_ip=http_request.client.host if http_request.client else None,
                http_method=http_request.method,
                path=str(http_request.url.path),
                message_text=request.message,
                reset_quote_context=request.reset_quote_context,
            )

            if await http_request.is_disconnected():
                log_event(
                    logger,
                    event="request_cancelled_before_invoke",
                    session_id=request.session_id,
                    request_id=request_id,
                )
                return

            agent_started = time.perf_counter()
            final_state = await asyncio.to_thread(agent.invoke, initial_state)

            log_event(
                logger,
                event="agent_finished",
                session_id=request.session_id,
                request_id=request_id,
                intent=final_state.get("intent"),
                support_info_kind=final_state.get("support_info_kind"),
                elapsed_ms=round((time.perf_counter() - agent_started) * 1000, 2),
                query_ready=final_state.get("query_ready"),
                query_completed=final_state.get("query_completed"),
                missing_slots=final_state.get("missing_slots"),
                pending_action_type=final_state.get("pending_action_type"),
                retrieval_query=final_state.get("retrieval_query"),
                retrieval_filters=final_state.get("retrieval_filters"),
                **summarize_retrieved_docs(final_state.get("retrieved_docs")),
                **summarize_latest_quote_result(final_state.get("latest_quote_result")),
            )

            SESSION_RUNTIME_STORE[request.session_id] = {
                "quote_result_active": final_state.get("quote_result_active", False),
                "latest_quote_result": deepcopy(final_state.get("latest_quote_result")),
            }

            ai_messages = [
                msg for msg in final_state["messages"]
                if (hasattr(msg, "type") and msg.type == "ai") or msg.__class__.__name__ == "AIMessage"
            ]

            if ai_messages:
                content = ai_messages[-1].content
                for char in content:
                    if await http_request.is_disconnected():
                        log_event(
                            logger,
                            event="request_cancelled_during_stream",
                            session_id=request.session_id,
                            request_id=request_id,
                        )
                        return
                    yield {"data": json.dumps({"type": "text", "content": char}, ensure_ascii=False)}
                    await asyncio.sleep(0.02)

            if await http_request.is_disconnected():
                log_event(
                    logger,
                    event="request_cancelled_before_context",
                    session_id=request.session_id,
                    request_id=request_id,
                )
                return

            yield {
                "data": json.dumps(
                    {"type": "context", "context": _build_context_data(final_state, request_id)},
                    ensure_ascii=False,
                )
            }

            if await http_request.is_disconnected():
                log_event(
                    logger,
                    event="request_cancelled_before_done",
                    session_id=request.session_id,
                    request_id=request_id,
                )
                return

            yield {"data": json.dumps({"type": "done"})}

            log_event(
                logger,
                event="request_completed",
                session_id=request.session_id,
                request_id=request_id,
                intent=final_state.get("intent"),
                total_elapsed_ms=round((time.perf_counter() - request_started) * 1000, 2),
                stream_completed=True,
                result_display_mode=final_state.get("result_display_mode"),
                pending_action_type=final_state.get("pending_action_type"),
                **summarize_retrieved_docs(final_state.get("retrieved_docs")),
                **summarize_latest_quote_result(final_state.get("latest_quote_result")),
            )
        except Exception as exc:
            log_event(
                logger,
                level=logging.ERROR,
                event="request_failed",
                message="chat request failed",
                session_id=request.session_id,
                request_id=request_id,
                total_elapsed_ms=round((time.perf_counter() - request_started) * 1000, 2),
                error_stage="main.chat",
                error_type=type(exc).__name__,
                error_message=str(exc),
                exc_info=True,
            )
            yield {
                "data": json.dumps(
                    {"type": "error", "content": f"系统异常：{str(exc)}"},
                    ensure_ascii=False,
                )
            }
            yield {"data": json.dumps({"type": "done"})}

    return EventSourceResponse(generate())


@app.post("/api/chat-feedback", response_model=ChatFeedbackResponse)
async def chat_feedback(request: ChatFeedbackRequest) -> ChatFeedbackResponse:
    """独立反馈接口：不影响已完成的聊天 SSE 主链路。"""
    if not settings.chat_feedback_enabled:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="聊天反馈功能当前未启用")
    return await submit_feedback(request)


@app.get("/health")
async def health():
    return {"status": "ok"}
