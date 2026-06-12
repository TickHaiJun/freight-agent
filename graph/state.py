from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # 对话历史
    messages: Annotated[list, add_messages]
    session_id: str | None
    request_id: str | None

    # 意图与响应控制
    intent: str | None
    query_subtype: str | None
    response_mode: str | None
    quantity_mode: str | None

    # 运价槽位
    sfg: str | None
    mdg: str | None
    inputWeight: float | None
    inputVol: float | None
    hbrq: str | None
    hbrqBegin: str | None
    hbrqEnd: str | None
    flightType: str | None
    packageType: str | None
    cargoType: str | None
    twoCode: str | None
    gid: int | None

    # 查询流程控制
    missing_slots: list[str]
    query_ready: bool
    query_completed: bool
    reset_quote_context: bool
    current_beijing_date: str | None
    time_clarify_message: str | None
    pending_clarify_slot: str | None
    pending_clarify_message: str | None
    pending_clarify_context: dict | None
    pending_action_type: str | None
    pending_action_prompt: str | None
    pending_action_payload: dict | None
    pending_action_retry_count: int
    pending_reuse_confirmation: bool
    pending_reuse_message: str | None
    reuse_candidate_context: dict | None
    reuse_confirmation_decision: str | None
    result_display_mode: str | None

    # 接口调用结果
    api_result: dict | None
    api_error: str | None

    # 报价结果分析上下文
    quote_result_active: bool
    latest_quote_result: dict | None
    result_analysis_intent: str | None
    result_analysis_filters: dict | None
    result_reference_field: str | None
    result_reference_request: dict | None
    support_info_kind: str | None

    # RAG 状态
    rag_query: str | None
    retrieval_query: str | None
    retrieval_filters: dict | None
    retrieved_docs: list | None
    rag_answer: str | None
