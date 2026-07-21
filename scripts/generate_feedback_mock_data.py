"""生成可供日志平台导入的聊天反馈模拟数据（100 条 JSONL 事件）。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


OUTPUT_PATH = Path("data/feedback/chat-feedback.mock-100.jsonl")
BEIJING_TZ = timezone(timedelta(hours=8))

SCENARIOS = [
    {
        "types": ["slow_response"], "text": "查询等待时间较长，希望尽快优化响应速度。",
        "question": "上海到洛杉矶，500公斤，1立方，明天出货，散货报价。",
        "answer": "已为您查询到 PVG 至 LAX 的最低参考方案。",
        "intent": "rate_query", "stage": "slot_extraction", "tags": ["latency"],
        "severity": "medium", "cause": "可能是模型槽位提取或上游查询耗时偏高，需复核阶段耗时。",
        "action": "检查意图识别、槽位提取和报价接口的耗时指标。",
    },
    {
        "types": ["quote_result_issue"], "text": "报价金额与我预期不一致，请核对数据来源。",
        "question": "只看直飞的最低价。", "answer": "已筛选直飞报价并展示最低方案。",
        "intent": "result_analysis", "stage": "freight_tool", "tags": ["tool_or_data_issue"],
        "severity": "high", "cause": "可能是上游运价数据或结果筛选规则需要复核。",
        "action": "核验上游报价返回、计费重和筛选条件。",
    },
    {
        "types": ["incomplete_answer"], "text": "回答没有说明锂电池货物需要哪些文件。",
        "question": "锂电池货物需要什么声明文件？", "answer": "锂电池货物需要按相关要求准备文件。",
        "intent": "rag", "stage": "rag_generation", "tags": ["missing_information", "knowledge_gap"],
        "severity": "medium", "cause": "可能是检索上下文不足或回答提示词未覆盖必要文件说明。",
        "action": "检查知识库召回结果并补充回答依据。",
    },
    {
        "types": ["misunderstood_question"], "text": "我问的是散货，系统却按托盘条件解释。",
        "question": "散货上海到法兰克福怎么报价？", "answer": "已按托盘货物为您查询参考报价。",
        "intent": "rate_query", "stage": "slot_extraction", "tags": ["misunderstanding"],
        "severity": "high", "cause": "可能是包装类型槽位提取错误，需复核对话上下文合并逻辑。",
        "action": "复核 packageType 抽取和多轮上下文覆盖规则。",
    },
    {
        "types": ["display_issue"], "text": "报价表格在页面上显示不完整，阅读困难。",
        "question": "展示全部数据。", "answer": "已为您展开当前报价的完整明细表。",
        "intent": "result_analysis", "stage": "frontend_display", "tags": ["display_issue"],
        "severity": "low", "cause": "可能是前端表格渲染或窄屏样式未适配。",
        "action": "检查报价表格的前端渲染、横向滚动和移动端样式。",
    },
    {
        "types": ["other"], "text": "回复内容不符合预期，请人工查看这次对话。",
        "question": "ACCOS 系统如何录入分单件数？", "answer": "请在系统中按业务要求录入相关信息。",
        "intent": "rag", "stage": "rag_retrieval", "tags": ["missing_information"],
        "severity": "medium", "cause": "可能是知识库召回内容与用户问题关联度不足。",
        "action": "复核检索 query、metadata 过滤和文档切分结果。",
    },
]


def timestamp(start: datetime, seconds: int) -> str:
    return (start + timedelta(seconds=seconds)).isoformat(timespec="seconds")


def build_events() -> list[dict]:
    start = datetime(2026, 7, 1, 9, 0, tzinfo=BEIJING_TZ)
    events: list[dict] = []
    for index in range(50):
        scenario = SCENARIOS[index % len(SCENARIOS)]
        feedback_id = f"fb_mock_{index + 1:04d}"
        request_id = f"req_mock_{index + 1:04d}"
        created_at = timestamp(start, index * 937)
        context_allowed = index % 5 != 0
        trace_found = index % 7 != 0
        total_elapsed = round(800 + (index * 431) % 18000, 2)

        snapshot = {"context_available_for_review": False}
        if context_allowed:
            snapshot = {
                "context_available_for_review": True,
                "user_question": scenario["question"],
                "assistant_answer": scenario["answer"],
                "conversation_excerpt": [f"用户：{scenario['question']}\n助手：{scenario['answer']}"] ,
            }

        events.append({
            "record_type": "feedback", "schema_version": 1, "feedback_id": feedback_id,
            "created_at": created_at, "source": "web_chat",
            "session_id": f"web_mock_{index + 1:04d}", "request_id": request_id,
            "user_feedback": {
                "dissatisfaction_types": scenario["types"], "feedback_text": scenario["text"],
                "allow_context_for_review": context_allowed,
            },
            "conversation_snapshot": snapshot,
            "trace_snapshot": {
                "trace_found": trace_found, "intent": scenario["intent"] if trace_found else None,
                "query_ready": scenario["intent"] == "rate_query", "tool_status": "success" if index % 4 else "failed",
                "retrieved_docs_count": 3 if scenario["intent"] == "rag" else 0,
                "total_elapsed_ms": total_elapsed, "origin": "pvg", "destination": "lax",
            },
            "ai_analysis": {"status": "pending"}, "workflow": {"status": "new", "owner": None},
        })

        analyzed_at = timestamp(start, index * 937 + 3)
        if index % 9 == 0:
            analysis = {"status": "failed", "analyzed_at": analyzed_at,
                        "error_type": "TimeoutError", "error_message": "模拟 AI 归因请求超时"}
        else:
            analysis = {
                "status": "completed", "model": "deepseek-chat", "analyzed_at": analyzed_at,
                "summary": f"模拟反馈：{scenario['text']}", "quality_tags": scenario["tags"],
                "business_domain": "rag" if scenario["intent"] == "rag" else "rate_query",
                "pipeline_stage": scenario["stage"], "root_cause_hypothesis": scenario["cause"],
                "severity": scenario["severity"], "confidence": round(0.61 + (index % 4) * 0.09, 2),
                "recommended_action": scenario["action"], "needs_human_review": scenario["severity"] != "low",
            }
        events.append({
            "record_type": "feedback_enrichment", "schema_version": 1, "feedback_id": feedback_id,
            "created_at": analyzed_at, "ai_analysis": analysis,
        })
    return events


def main() -> None:
    events = build_events()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(json.dumps(event, ensure_ascii=False, separators=(",", ":")) for event in events) + "\n", encoding="utf-8")
    print(f"已生成 {len(events)} 条模拟事件：{OUTPUT_PATH}")


if __name__ == "__main__":
    main()
