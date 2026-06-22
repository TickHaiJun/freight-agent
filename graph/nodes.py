import json
import logging
import random
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from config import settings
from graph.prompts import (
    FALLBACK_RESPONSES,
    HBRQ_SEMANTIC_SYSTEM,
    HBRQ_SEMANTIC_USER,
    INTENT_SYSTEM,
    INTENT_USER,
    QUOTE_FOLLOWUP_SYSTEM,
    QUOTE_FOLLOWUP_USER,
    SLOT_USER,
    build_slot_system,
)
from graph.origin_parser import (
    ALL_ORIGIN_SCOPE_TEXT,
    extract_origin_codes,
    looks_like_origin_reply,
)
from graph.query_validation import build_origin_clarify_message, validate_rate_slots
from graph.result_handlers import (
    analyze_result_request,
    analyze_result_reference_request,
    build_standard_quote_result,
    is_result_analysis_request,
    render_result_reference_message,
    render_result_analysis_message,
)
from graph.state import AgentState
from graph.time_utils import get_current_beijing_datetime
from logging_schema import (
    log_event,
    summarize_latest_quote_result,
    summarize_retrieved_docs,
    summarize_text,
)
from rag.generator import generate_answer
from rag.query_analyzer import analyze_query
from rag.retriever import hybrid_retrieve
from tools.air_freight import search_air_freight_rate

logger = logging.getLogger(__name__)


def _log_state_event(
    state: AgentState,
    *,
    event: str,
    level: int = logging.INFO,
    message: str | None = None,
    **fields,
) -> None:
    """给节点日志自动补 session_id/request_id，减少重复拼接。"""
    log_event(
        logger,
        level=level,
        event=event,
        message=message,
        session_id=state.get("session_id"),
        request_id=state.get("request_id"),
        **fields,
    )

RATE_CONTEXT_FIELDS = [
    "sfg",
    "mdg",
    "inputWeight",
    "inputVol",
    "hbrq",
    "hbrqBegin",
    "hbrqEnd",
    "flightType",
    "packageType",
    "cargoType",
    "twoCode",
    "gid",
]
# 当前业务规则下，包装类型已经与起运港/目的港/重量/体积并列为正式必填。
REQUIRED_RATE_FIELDS = ["sfg", "mdg", "inputWeight", "inputVol", "packageType"]
CORE_REUSE_FIELDS = ["inputWeight", "inputVol", "hbrq", "hbrqBegin", "hbrqEnd"]
FOLLOWUP_KEYWORDS = [
    "查一下",
    "再查",
    "查个",
    "看一下",
    "看看",
    "查价格",
    "报价",
    "空运",
    "运价",
    "改成",
    "换成",
    "改下",
    "改一下",
    "重新查",
    "再报",
    "还是这个",
    "按刚才",
    "继续",
    "明天",
    "后天",
    "今天",
    "这周",
    "本周",
    "下周",
    "下下周",
    "最快",
    "哪天",
    "什么时候",
    "航班",
    "包装",
    "托盘",
    "散货",
]
PARAMETER_PATTERNS = {
    "weight": r"\d+(\.\d+)?\s*(公斤|kg|KG|吨)",
    "volume": r"\d+(\.\d+)?\s*(立方|方|cbm|CBM)",
    "date": r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}月\d{1,2}日|明天|后天|今天|这周|本周|下周|下下周|周末",
}
SLOT_CLEAR_RULES = {
    "inputWeight": {
        "keywords": ["重量", "公斤", "kg", "KG", "吨", "毛重", "净重"],
        "markers": ["不知道", "不清楚", "不确定", "还没", "暂无", "没有", "未定", "先不", "别按", "别用"],
    },
    "inputVol": {
        "keywords": ["体积", "立方", "方", "cbm", "CBM", "尺寸", "长宽高"],
        "markers": ["不知道", "不清楚", "不确定", "还没", "没量", "暂无", "没有", "未定", "先不", "别按", "别用"],
    },
    "hbrq": {
        "keywords": ["日期", "时间", "出货", "起运", "航班", "哪天", "什么时候"],
        "markers": ["不知道", "不清楚", "不确定", "还没定", "未定", "先不", "别按", "别用", "待定"],
    },
    "hbrqBegin": {
        "keywords": ["开始", "起始", "从", "日期区间", "这几天", "未来"],
        "markers": ["不知道", "不清楚", "不确定", "未定", "先不", "别按", "别用", "待定"],
    },
    "hbrqEnd": {
        "keywords": ["结束", "截止", "到", "日期区间", "这几天", "未来"],
        "markers": ["不知道", "不清楚", "不确定", "未定", "先不", "别按", "别用", "待定"],
    },
    "sfg": {
        "keywords": ["起运港", "始发港", "始发地", "出发地", "从哪", "起飞机场"],
        "markers": ["不知道", "不清楚", "不确定", "还没定", "未定", "先不", "别按", "别用", "待定"],
    },
    "mdg": {
        "keywords": ["目的港", "目的地", "到哪", "飞哪", "去哪里"],
        "markers": ["不知道", "不清楚", "不确定", "还没定", "未定", "先不", "别按", "别用", "待定"],
    },
    "packageType": {
        "keywords": ["包装", "托盘", "散货", "板货"],
        "markers": ["不知道", "不清楚", "不确定", "还没定", "未定", "先不", "别按", "别用", "待定"],
    },
}
FIELD_LABELS = {
    "sfg": "起运港",
    "mdg": "目的港",
    "inputWeight": "重量",
    "inputVol": "体积",
    "packageType": "包装类型",
    "hbrq": "航班日期",
}
RESULT_CONTACT_EMAIL = "rooneyzhuangsh@wecanintl.com"
SERVICE_INFO_PATTERNS = [
    "人工客服",
    "客服联系方式",
    "联系方式",
    "联系你们",
    "联系人工",
    "销售团队",
    "客服邮箱",
    "邮箱",
]
CAPABILITY_PATTERNS = [
    "你有哪些功能",
    "你能做什么",
    "你可以做什么",
    "你们能做什么",
    "还能查什么",
    "可以帮我做什么",
]
ALL_ORIGIN_SCOPE_PATTERNS = [
    "全部港口有哪些",
    "全部港口有哪里",
    "全部查询有哪些港口",
    "全部查询有哪些口岸",
    "全部始发港有哪些",
    "全部口岸有哪些",
    "支持哪些始发港",
]
BUSINESS_META_PATTERNS = [
    "你不问我始发港",
    "你是不是理解错了",
    "你刚才是不是理解错了",
    "你先别查",
    "先确认下我的条件",
    "先确认我的条件",
    "还缺什么",
    "缺什么参数",
    "为什么不问我",
]
WEEKDAY_PATTERN = re.compile(r"(周|星期|礼拜)(一|二|三|四|五|六|日|天)")
WEEK_PREFIX_PATTERN = re.compile(r"(这周|本周|下周|下下周)\s*(一|二|三|四|五|六|日|天)")
AMBIGUOUS_TIME_PATTERNS = [
    "越快越好",
    "最快",
    "最近几天",
    "这几天",
    "哪天",
    "什么时候",
]
CARGO_READY_KEYWORDS = ["货好", "备好", "准备好", "ready", "货齐", "货物备好"]
FULL_QUOTE_KEYWORDS = [
    "全部数据",
    "所有数据",
    "全部报价",
    "所有报价",
    "全部明细",
    "完整报价",
    "展示全部",
    "全部展开",
    "全部列出来",
    "把所有方案给我看",
    "都列出来",
]
DIRECT_DATE_CLEAR_MESSAGE = "为了帮您准确查询运价，请明确一下具体日期。"
REUSE_CONFIRM_REPLIES = {
    "reuse": ["是", "可以", "对", "好的", "行", "沿用", "按之前的", "按上一票", "按上次的", "就按之前的"],
    "reject": ["不是", "不用", "不沿用", "重新来", "重新填", "我重新给", "不一样", "别沿用"],
}
ROUTE_ROLE_CONFIRM_REPLIES = {
    "sfg": ["起运港", "始发港", "始发地", "出发地", "从", "起飞", "从这边发", "从这里发"],
    "mdg": ["目的港", "目的地", "到", "飞到", "运到", "送到"],
}
HBRQ_SEMANTIC_REPLIES = {
    "flight_date": ["航班日期", "航班", "飞", "出运", "走货", "按这天查", "按这个日期查", "是航班"],
    "cargo_ready": ["货好", "备好", "准备好", "ready", "工厂", "货好日期", "备货日期"],
}
WEAK_CONFIRM_REPLIES = ["是的", "是", "对", "嗯", "好的", "好", "没错"]
SMALL_TALK_PATTERNS = [
    r"你?好[呀啊哈]?[\s！!。?？]*",
    r"您好[\s！!。?？]*",
    r"在吗[\s！!。?？]*",
    r"谢谢[\s！!。?？]*",
    r"好的[\s！!。?？]*",
    r"收到[\s！!。?？]*",
]
GREETING_PATTERNS = [
    r"你?好[呀啊哈]?[\s！!。?？]*",
    r"您好[\s！!。?？]*",
    r"在吗[\s！!。?？]*",
    r"hi[\s！!。?？]*",
    r"hello[\s！!。?？]*",
]
PACKAGE_TYPE_NORMALIZATION = {
    "散货": "散货",
    "散": "散货",
    "散货包装": "散货",
    "托盘": "托盘",
    "托": "托盘",
    "托盘货": "托盘",
    "托盘包装": "托盘",
    "板货": "托盘",
}


def get_llm(streaming: bool = False):
    """获取统一的大模型客户端。"""
    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        streaming=streaming,
        temperature=0.2,
    )


def _current_rate_context(state: AgentState) -> dict:
    """提取当前运价上下文，便于日志和重置。"""
    return {field: state.get(field) for field in RATE_CONTEXT_FIELDS}


def _reset_rate_context(state: AgentState) -> AgentState:
    """开启新询价时，清空上一轮运价状态，避免旧值污染。"""
    reset_values = {field: None for field in RATE_CONTEXT_FIELDS}
    reset_values.update(
        {
            "missing_slots": [],
            "query_ready": False,
            "query_completed": False,
            "api_result": None,
            "api_error": None,
            "quote_result_active": False,
            "latest_quote_result": None,
            "result_analysis_intent": None,
            "result_analysis_filters": None,
            "time_clarify_message": None,
            "pending_clarify_slot": None,
            "pending_clarify_message": None,
            "pending_clarify_context": None,
            "pending_action_type": None,
            "pending_action_prompt": None,
            "pending_action_payload": None,
            "pending_action_retry_count": 0,
            "pending_reuse_confirmation": False,
            "pending_reuse_message": None,
            "reuse_candidate_context": None,
            "reuse_confirmation_decision": None,
            "result_display_mode": None,
            "result_reference_field": None,
            "result_reference_request": None,
            "response_mode": None,
            "quantity_mode": None,
            "support_info_kind": None,
            "query_subtype": None,
        }
    )
    return {**state, **reset_values}


def _derive_pending_action_type(state: AgentState) -> str | None:
    """
    兼容旧 pending_clarify_* / pending_reuse_* 字段，推导统一 pending action 类型。

    第一版先并行维护两套状态，避免一次性改穿前后端 context 协议。
    """
    if state.get("pending_action_type"):
        return state.get("pending_action_type")
    if state.get("pending_reuse_confirmation"):
        return "reuse_confirmation"
    return state.get("pending_clarify_slot")


def _derive_pending_action_prompt(state: AgentState) -> str | None:
    if state.get("pending_action_prompt"):
        return state.get("pending_action_prompt")
    return state.get("pending_reuse_message") or state.get("pending_clarify_message")


def _derive_pending_action_payload(state: AgentState) -> dict | None:
    if state.get("pending_action_payload") is not None:
        return state.get("pending_action_payload")
    if state.get("pending_reuse_confirmation"):
        return state.get("reuse_candidate_context")
    return state.get("pending_clarify_context")


def _set_pending_action(
    state: AgentState,
    action_type: str | None,
    prompt: str | None,
    payload: dict | None,
    retry_count: int = 0,
) -> AgentState:
    """统一写入新的 pending action 字段。"""
    return {
        **state,
        "pending_action_type": action_type,
        "pending_action_prompt": prompt,
        "pending_action_payload": payload,
        "pending_action_retry_count": retry_count,
    }


def _clear_pending_action(state: AgentState) -> AgentState:
    """统一清空 pending action 字段。"""
    return {
        **state,
        "pending_action_type": None,
        "pending_action_prompt": None,
        "pending_action_payload": None,
        "pending_action_retry_count": 0,
    }


def _normalize_package_type(value: str | None) -> str | None:
    """
    将用户表达的包装类型标准化为系统内部只允许的两个值。

    这层规则必须前置存在，否则 packageType 升级为必填后，
    用户只回复“托盘 / 板货 / 散”这类短句时很容易掉到 unknown。
    """
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None

    compact = re.sub(r"[\s，,。.!！?？]", "", normalized)
    for candidate, standard in PACKAGE_TYPE_NORMALIZATION.items():
        if candidate.lower() == compact:
            return standard

    if "托盘" in compact or "板货" in compact:
        return "托盘"
    if "散货" in compact:
        return "散货"

    return None


def _extract_package_type_from_message(message: str) -> str | None:
    """从用户当前输入中直接提取包装类型，作为 LLM 抽槽位前的稳定兜底。"""
    return _normalize_package_type(message)


def _looks_like_package_type_reply(message: str, state: AgentState) -> bool:
    """
    判断当前输入是否只是“补包装类型”的短答。

    适用场景：
    - 当前缺 packageType，用户只回复“托盘 / 散货”
    - 当前仍在报价上下文里，用户说“改成托盘 / 只看托盘”
    """
    package_type = _extract_package_type_from_message(message)
    if not package_type:
        return False

    normalized = (message or "").strip()
    # 只把“散货 / 托盘 / 改成托盘”这类短回复视为补包装。
    # 如果一句话里已经同时带了航线、重量、体积或日期，就优先按新询价处理。
    if len(normalized) > 12:
        return False
    if any(re.search(pattern, normalized) for pattern in PARAMETER_PATTERNS.values()):
        return False
    if any(token in normalized for token in ["从", "到", "飞", "发往", "发去", "送往", "去往"]):
        return False

    if state.get("pending_clarify_slot") == "packageType":
        return True

    missing_slots = state.get("missing_slots") or []
    if "packageType" in missing_slots:
        return True

    return _has_rate_context(state) and not state.get("quote_result_active")


def _build_rate_context_snapshot(state: AgentState, slots: dict) -> dict:
    """
    在进入语义澄清前，先固化当前已经识别出的询价参数快照。

    目的：
    - 避免用户只回答“按航班日期”后，系统丢掉前面已经识别出的航线、重量、体积、包装
    - 把“解释歧义”和“重做整票询价”拆开
    """
    snapshot = {
        field: slots.get(field) if slots.get(field) not in (None, "") else state.get(field)
        for field in RATE_CONTEXT_FIELDS
    }
    snapshot["packageType"] = _normalize_package_type(snapshot.get("packageType"))
    return _normalize_date_slots(snapshot)


def _summarize_rate_context_for_prompt(state: AgentState) -> str:
    """把当前报价上下文压成短文本，供 follow-up 语义识别 Prompt 使用。"""
    parts = []
    for field in RATE_CONTEXT_FIELDS:
        value = state.get(field)
        if value not in (None, ""):
            parts.append(f"{field}={value}")
    return "；".join(parts) if parts else "无"


def _looks_like_weak_confirmation(message: str) -> bool:
    """识别“是的 / 对 / 嗯”这类过于模糊、不能直接执行枚举动作的确认回复。"""
    normalized = (message or "").strip()
    return any(normalized == candidate for candidate in WEAK_CONFIRM_REPLIES)


def _detect_support_info_kind(message: str) -> str | None:
    """识别业务服务信息或能力说明类问题，避免误走结果分析或 unknown。"""
    normalized = (message or "").strip()
    if not normalized:
        return None

    if any(keyword in normalized for keyword in ALL_ORIGIN_SCOPE_PATTERNS):
        return "all_origin_scope"

    if any(keyword in normalized for keyword in BUSINESS_META_PATTERNS):
        return "business_meta"

    if any(keyword in normalized for keyword in CAPABILITY_PATTERNS) or (
        "功能" in normalized and any(token in normalized for token in ["你", "你们"])
    ):
        return "capability_intent"

    if any(keyword in normalized for keyword in SERVICE_INFO_PATTERNS) or (
        any(token in normalized for token in ["客服", "销售", "人工"])
        and any(token in normalized for token in ["联系", "联系方式", "邮箱"])
    ):
        return "service_info"

    return None


def _parse_current_beijing_date(state: AgentState) -> datetime:
    """统一从当前请求状态中获取北京时间日期。"""
    current_date = state.get("current_beijing_date")
    if current_date:
        return datetime.strptime(current_date, "%Y-%m-%d")
    # 兜底时仍显式按 UTC+8 计算北京时间，避免环境缺失 tzdata 导致节点执行失败。
    return get_current_beijing_datetime()


def _next_weekend_range(base_date: datetime) -> tuple[str, str]:
    """返回“周末”对应的日期区间，按当前北京时间推到最近一个周六 / 周日。"""
    weekday = base_date.weekday()  # 周一=0，周日=6
    days_until_saturday = (5 - weekday) % 7
    saturday = base_date + timedelta(days=days_until_saturday)
    sunday = saturday + timedelta(days=1)
    return saturday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


def _resolve_prefixed_weekday_date(normalized: str, base_date: datetime) -> str | None:
    """
    解析“这周六 / 本周六 / 下周六 / 下下周六”这类表达。

    这类表达在业务上已经足够明确，不应再进入追问。
    """
    match = WEEK_PREFIX_PATTERN.search(normalized)
    if not match:
        return None

    prefix, weekday_text = match.groups()
    weekday_mapping = {
        "一": 0,
        "二": 1,
        "三": 2,
        "四": 3,
        "五": 4,
        "六": 5,
        "日": 6,
        "天": 6,
    }
    target_weekday = weekday_mapping[weekday_text]
    current_week_monday = base_date - timedelta(days=base_date.weekday())

    week_offset = {
        "这周": 0,
        "本周": 0,
        "下周": 1,
        "下下周": 2,
    }[prefix]

    target_date = current_week_monday + timedelta(days=target_weekday + week_offset * 7)
    return target_date.strftime("%Y-%m-%d")


def _resolve_relative_date_from_message(message: str, state: AgentState) -> tuple[dict, str | None]:
    """
    将高频相对时间词标准化成具体日期 / 日期区间，或返回追问文案。

    规则：
    - 今天 / 明天 / 后天：直接落单日期
    - 明后天：落日期区间
    - 周末：落日期区间
    - 周一这类不带“这周 / 下周”的表达：优先追问
    - 越快越好 / 最快 / 最近几天 / 这几天 / 哪天 / 什么时候：优先追问
    """
    normalized = (message or "").strip()
    base_date = _parse_current_beijing_date(state)

    prefixed_weekday_date = _resolve_prefixed_weekday_date(normalized, base_date)
    if prefixed_weekday_date:
        return {"hbrq": prefixed_weekday_date, "hbrqBegin": None, "hbrqEnd": None}, None

    for pattern in AMBIGUOUS_TIME_PATTERNS:
        if pattern in normalized:
            if pattern in {"越快越好", "最快"}:
                return {}, "请问您希望查询具体哪一天，或者哪几天内的班期价格？"
            if pattern in {"最近几天", "这几天"}:
                return {}, "请问您希望查询哪一天，或者给我一个明确的日期区间？"
            return {}, DIRECT_DATE_CLEAR_MESSAGE

    # “下周一 / 本周一 / 这周一”这类仍交给模型处理；只拦截纯“周一 / 星期一 / 礼拜一”。
    weekday_match = WEEKDAY_PATTERN.search(normalized)
    if weekday_match and not any(token in normalized for token in ["这周", "本周", "下周", "下下周"]):
        return {}, f"请问您是指这周{weekday_match.group(2)}，还是下周{weekday_match.group(2)}？"

    if "明后天" in normalized:
        begin = base_date + timedelta(days=1)
        end = base_date + timedelta(days=2)
        return {
            "hbrq": None,
            "hbrqBegin": begin.strftime("%Y-%m-%d"),
            "hbrqEnd": end.strftime("%Y-%m-%d"),
        }, None

    if "后天" in normalized:
        target = base_date + timedelta(days=2)
        return {"hbrq": target.strftime("%Y-%m-%d"), "hbrqBegin": None, "hbrqEnd": None}, None

    if "明天" in normalized:
        target = base_date + timedelta(days=1)
        return {"hbrq": target.strftime("%Y-%m-%d"), "hbrqBegin": None, "hbrqEnd": None}, None

    if "今天" in normalized:
        return {"hbrq": base_date.strftime("%Y-%m-%d"), "hbrqBegin": None, "hbrqEnd": None}, None

    if "周末" in normalized:
        begin, end = _next_weekend_range(base_date)
        return {"hbrq": None, "hbrqBegin": begin, "hbrqEnd": end}, None

    return {}, None


def _looks_like_time_clarify_reply(message: str, state: AgentState) -> bool:
    """
    判断本轮是否是在回答上一轮的日期澄清问题。

    这里不要求用户重述整句询价，只要当前处于待澄清状态，
    且本轮消息像一个明确日期补充，就应直接回到补槽位链路。
    """
    if state.get("pending_clarify_slot") != "hbrq":
        return False

    normalized = (message or "").strip()
    if not normalized:
        return False

    explicit_date_patterns = [
        r"\d{4}-\d{1,2}-\d{1,2}",
        r"\d{1,2}月\d{1,2}日",
    ]
    if any(re.search(pattern, normalized) for pattern in explicit_date_patterns):
        return True

    if _resolve_prefixed_weekday_date(normalized, _parse_current_beijing_date(state)):
        return True

    if any(keyword in normalized for keyword in ["今天", "明天", "后天", "明后天", "周末"]):
        return True

    return False


def _extract_city_followup_label(message: str) -> str | None:
    """
    提取“那青岛呢 / 广州呢”这类短追问里的城市文本。

    这里只做轻量文本提取，不做机场代码映射；机场代码仍由槽位抽取负责。
    """
    normalized = re.sub(r"[？?！!。,.，\s]", "", (message or "").strip())
    normalized = normalized.removeprefix("那")

    if normalized.endswith("呢"):
        normalized = normalized[:-1]
    elif normalized.endswith("的话"):
        normalized = normalized[:-2]

    if 1 < len(normalized) <= 8 and re.fullmatch(r"[\u4e00-\u9fa5A-Za-z]+", normalized or ""):
        return normalized
    return None


def _looks_like_small_talk(message: str) -> bool:
    """
    识别明显闲聊短句。

    这类输入在已有报价上下文下最容易被误吸进 follow-up 询价链，
    因此需要在 city_followup / rate_followup 之前先排除。
    """
    normalized = (message or "").strip()
    if not normalized or len(normalized) > 12:
        return False
    return any(re.fullmatch(pattern, normalized, re.IGNORECASE) for pattern in SMALL_TALK_PATTERNS)


def _looks_like_greeting(message: str) -> bool:
    """将 greeting 单独识别出来，避免继续复用 unknown 兜底。"""
    normalized = (message or "").strip()
    if not normalized or len(normalized) > 12:
        return False
    return any(re.fullmatch(pattern, normalized, re.IGNORECASE) for pattern in GREETING_PATTERNS)


def _looks_like_explicit_new_quote_request(message: str) -> bool:
    """
    用更强的确定性规则识别“这是新的完整询价”。

    这条规则专门用来挡住旧结果追问误截新询价的情况。
    """
    normalized = (message or "").strip()
    if not normalized or _looks_like_small_talk(normalized):
        return False

    route_signal = any(
        token in normalized for token in ["从", "到", "飞", "发往", "发去", "送往", "去往", "运往", "运到"]
    )
    intro_signal = any(token in normalized for token in ["我有一票货", "帮我查", "查一下", "重新查", "再查一票"])
    detail_hits = sum(1 for pattern in PARAMETER_PATTERNS.values() if re.search(pattern, normalized))

    if _extract_package_type_from_message(normalized):
        detail_hits += 1

    if route_signal and detail_hits >= 2:
        return True

    return intro_signal and route_signal and detail_hits >= 1


def _looks_like_city_followup(message: str, state: AgentState) -> bool:
    """
    判断是否是“已有一票货，继续把起运港/目的港改成另一个城市”的短追问。

    第一版只做保守识别：
    - 上一轮已完成报价
    - 当前消息较短
    - 像“那青岛呢 / 广州呢 / 从青岛出发呢”这种航线延续追问
    """
    if not state.get("query_completed") or not _has_rate_context(state):
        return False

    normalized = (message or "").strip()
    if not normalized or len(normalized) > 20:
        return False

    if _looks_like_small_talk(normalized):
        return False

    # 结果引用短句、结果解释短句不应再被误判为“改城市继续查”。
    if any(keyword in normalized for keyword in ["最便宜", "最低", "全部", "直飞", "中转", "明天", "后天", "今天", "多少号", "几号", "哪天", "航司", "包装", "为什么"]):
        return False

    label = _extract_city_followup_label(normalized)
    # 城市短追问必须带承接信号，避免“你好”这类双字短句被当成城市名。
    if (
        label
        and not any(token in normalized for token in ["什么", "多少", "几", "哪"])
        and ("呢" in normalized or "的话" in normalized or normalized.startswith("那"))
    ):
        return True

    return bool(re.search(r"从[\u4e00-\u9fa5A-Za-z]{2,8}出发", normalized))


def _extract_route_role_decision(message: str) -> str | None:
    """识别用户是在确认“改起运港”还是“改目的港”."""
    normalized = (message or "").strip()
    for decision, candidates in ROUTE_ROLE_CONFIRM_REPLIES.items():
        if any(candidate in normalized for candidate in candidates):
            return decision
    return None


def _looks_like_route_city_clarify_reply(message: str, state: AgentState) -> bool:
    """判断本轮是否在回答“青岛是起运港还是目的港”的澄清问题。"""
    if state.get("pending_clarify_slot") != "route_city_role":
        return False
    return _extract_route_role_decision(message) is not None


def _build_route_city_clarify_message(city_label: str) -> str:
    """为城市短追问生成固定澄清文案。"""
    return f"您是指起运港改成{city_label}，还是目的港改成{city_label}？请直接回复“起运港”或“目的港”。"


def _build_route_city_retry_message(city_label: str) -> str:
    """当用户只回答“是的 / 对”这类模糊确认时，要求其给出明确枚举答案。"""
    return f"我需要您明确一下：您是指起运港改成{city_label}，还是目的港改成{city_label}？请直接回复“起运港”或“目的港”。"


def _looks_like_hbrq_semantic_reply(message: str, state: AgentState) -> bool:
    """判断用户是否在回答“货好日期还是航班日期”的语义澄清。"""
    if state.get("pending_clarify_slot") != "hbrq_semantic":
        return False

    normalized = (message or "").strip()
    return any(candidate in normalized for candidates in HBRQ_SEMANTIC_REPLIES.values() for candidate in candidates)


def _extract_hbrq_semantic_decision(message: str) -> str | None:
    """识别用户将日期解释为航班日期还是货好日期。"""
    normalized = (message or "").strip()
    for decision, candidates in HBRQ_SEMANTIC_REPLIES.items():
        if any(candidate in normalized for candidate in candidates):
            return decision
    return None


def _classify_hbrq_semantic_reply_with_llm(message: str, state: AgentState) -> str | None:
    """
    当规则无法识别“按航班日期 / 这是货好日期”的回答时，再用 LLM 做一次结构化兜底。

    注意：
    - 这里只做二分类补盲，不直接生成回复
    - 只有当前确实处于 hbrq_semantic 待澄清状态时才会调用
    """
    if state.get("pending_clarify_slot") != "hbrq_semantic":
        return None

    llm = get_llm()
    response = llm.invoke(
        [
            SystemMessage(content=HBRQ_SEMANTIC_SYSTEM),
            HumanMessage(
                content=HBRQ_SEMANTIC_USER.format(
                    prompt=state.get("pending_action_prompt") or state.get("pending_clarify_message") or "",
                    message=message,
                )
            ),
        ]
    )

    try:
        payload = json.loads(response.content.strip())
    except json.JSONDecodeError:
        start = response.content.find("{")
        end = response.content.rfind("}") + 1
        try:
            payload = json.loads(response.content[start:end])
        except Exception:
            payload = {}

    decision = str(payload.get("decision") or "").strip()
    return decision if decision in {"flight_date", "cargo_ready"} else None


def _classify_quote_followup_with_llm(message: str, state: AgentState) -> dict | None:
    """
    对规则未覆盖的报价域 follow-up 做结构化识别。

    这一步不是全局 intent 分类，而是明确建立在“当前仍处于报价域”前提下的补盲层。
    """
    if not state.get("quote_result_active"):
        return None

    llm = get_llm()
    response = llm.invoke(
        [
            SystemMessage(content=QUOTE_FOLLOWUP_SYSTEM),
            HumanMessage(
                content=QUOTE_FOLLOWUP_USER.format(
                    message=message,
                    quote_result_active=bool(state.get("quote_result_active")),
                    pending_action_type=state.get("pending_action_type") or "none",
                    context_summary=_summarize_rate_context_for_prompt(state),
                )
            ),
        ]
    )

    try:
        payload = json.loads(response.content.strip())
    except json.JSONDecodeError:
        start = response.content.find("{")
        end = response.content.rfind("}") + 1
        try:
            payload = json.loads(response.content[start:end])
        except Exception:
            payload = {}

    intent = str(payload.get("intent") or "").strip()
    if intent not in {"result_analysis", "result_reference", "rate_query", "clarify_needed"}:
        return None

    return payload


def _looks_like_cargo_ready_phrase(message: str) -> bool:
    """识别“货5月22日准备好”这类应先澄清而不是直接查价的行业表达。"""
    normalized = (message or "").lower()
    if any(keyword in normalized for keyword in CARGO_READY_KEYWORDS):
        return True

    # 行业里常见的口语表达并不总会完整说“准备好”，
    # 例如“货大概 5 月 27 号好”“5 月 27 号能出货”。
    cargo_ready_patterns = [
        r"货.*\d{1,2}月\d{1,2}[日号]?\s*好",
        r"\d{1,2}月\d{1,2}[日号]?.*货.*好",
        r"\d{1,2}月\d{1,2}[日号]?.*(能出货|可以出货|可出货)",
        r"货.*(能出货|可以出货|可出货)",
    ]
    return any(re.search(pattern, normalized) for pattern in cargo_ready_patterns)


def _looks_like_industry_date_semantic_followup(message: str, state: AgentState) -> bool:
    """
    判断本轮是否是“行业日期语义”补充。

    这类输入本质上仍然属于当前询价上下文，不应直接掉到 unknown。
    """
    if not _has_rate_context(state):
        return False

    normalized = (message or "").strip()
    if not normalized:
        return False

    has_date_token = bool(
        re.search(
            r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}月\d{1,2}[日号]?|今天|明天|后天|周末|这周[一二三四五六日天]|本周[一二三四五六日天]|下周[一二三四五六日天]",
            normalized,
        )
    )
    return has_date_token and _looks_like_cargo_ready_phrase(normalized)


def _extract_human_date_token(message: str, fallback: str | None = None) -> str:
    """从用户原话中提取便于追问复述的日期片段。"""
    match = re.search(
        r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}月\d{1,2}日|今天|明天|后天|明后天|周末|这周[一二三四五六日天]|本周[一二三四五六日天]|下周[一二三四五六日天]",
        message or "",
    )
    return match.group(0) if match else (fallback or "这个日期")


def _count_filled_required_rate_fields(state: AgentState) -> int:
    """统计当前必填报价槽位里已经有值的数量。"""
    return sum(1 for field in REQUIRED_RATE_FIELDS if state.get(field) not in (None, ""))


def _has_effective_date_value(data: dict) -> bool:
    """统一判断当前是否已经有单日期或日期区间。"""
    return bool(data.get("hbrq") or (data.get("hbrqBegin") and data.get("hbrqEnd")))


def _has_rate_context(state: AgentState) -> bool:
    """已有两个以上必填槽位时，认为存在可承接的报价上下文。"""
    return _count_filled_required_rate_fields(state) >= 2


def _looks_like_rate_followup(message: str, state: AgentState) -> bool:
    """
    判断本轮是否是“承接上文的继续报价/修改参数”请求。

    规则尽量保守：
    - 必须已有有效报价上下文
    - 当前消息里需要出现续问词、报价词、时间词或参数模式之一
    """
    if not _has_rate_context(state):
        return False

    normalized = (message or "").strip()
    if not normalized:
        return False

    if any(keyword in normalized for keyword in FOLLOWUP_KEYWORDS):
        return True

    return any(re.search(pattern, normalized) for pattern in PARAMETER_PATTERNS.values())


def _looks_like_new_complete_rate_query(message: str, state: AgentState) -> bool:
    """
    判定“新的完整询价”。

    仅在上一轮已经完成查询后启用该规则，避免用户补参过程中被误重置。
    口径与已确认方案一致：
    - 本轮重新出现新的起运港/目的港线索
    - 且同时带了重量/体积/日期中的至少两项
    """
    if not state.get("query_completed"):
        return False

    normalized = (message or "").strip()
    if not normalized:
        return False

    route_signal = bool(re.search(r"(到|飞|运往|至)", normalized))
    if not route_signal:
        return False

    detail_hits = sum(
        1
        for pattern in PARAMETER_PATTERNS.values()
        if re.search(pattern, normalized)
    )
    return detail_hits >= 2


def _detect_cleared_slots(message: str) -> set[str]:
    """识别用户是否明确表达某个槽位未知、未定或不要沿用旧值。"""
    normalized = (message or "").strip()
    cleared_fields: set[str] = set()

    for field, rule in SLOT_CLEAR_RULES.items():
        if any(keyword in normalized for keyword in rule["keywords"]) and any(
            marker in normalized for marker in rule["markers"]
        ):
            cleared_fields.add(field)

    if "hbrqBegin" in cleared_fields or "hbrqEnd" in cleared_fields:
        cleared_fields.update({"hbrqBegin", "hbrqEnd", "hbrq"})

    return cleared_fields


def _merge_slot_value(extracted_value, existing_value, field_name: str, cleared_fields: set[str]):
    """槽位合并优先级：新值 > 明确清空/未知 > 旧 context。"""
    if extracted_value not in (None, ""):
        return extracted_value
    if field_name in cleared_fields:
        return None
    return existing_value


def _normalize_date_slots(updated: dict) -> dict:
    """
    统一日期槽位的优先级。

    - 如果拿到了日期区间，则清空单日期
    - 如果只有单日期，则清空区间字段
    """
    if updated.get("hbrqBegin") and updated.get("hbrqEnd"):
        updated["hbrq"] = None
    elif updated.get("hbrq"):
        updated["hbrqBegin"] = None
        updated["hbrqEnd"] = None

    return updated


def _is_route_changed_by_current_turn(state: AgentState, slots: dict) -> bool:
    """
    判断本轮是否在上一轮已完成查询后，明确切换到了新的航线。

    这里基于“本轮抽取得到的新 sfg/mdg”和“旧 context 中的 sfg/mdg”做比较，
    只要用户明确改了起运港或目的港，就视为新航线。
    """
    if not state.get("query_completed"):
        return False

    extracted_sfg = slots.get("sfg")
    extracted_mdg = slots.get("mdg")

    if not extracted_sfg and not extracted_mdg:
        return False

    old_sfg = state.get("sfg")
    old_mdg = state.get("mdg")

    sfg_changed = bool(extracted_sfg and old_sfg and extracted_sfg != old_sfg)
    mdg_changed = bool(extracted_mdg and old_mdg and extracted_mdg != old_mdg)

    return sfg_changed or mdg_changed


def _reset_state_for_new_route_query(state: AgentState, slots: dict) -> AgentState:
    """
    处理“新航线但询价不完整”的场景。

    与 intent_node 里“完整新询价直接 reset”不同，这里发生在 slot 阶段：
    - 保留本轮已明确抽取出来的新航线和新参数
    - 清空上一轮未在本轮重复声明的旧重量/体积/日期/可选字段
    - 让后续缺参判断自然进入一次性提醒
    """
    reset_fields = {
        "inputWeight": None,
        "inputVol": None,
        "hbrq": None,
        "hbrqBegin": None,
        "hbrqEnd": None,
        "flightType": None,
        "packageType": None,
        "cargoType": None,
        "twoCode": None,
        "gid": None,
        "api_result": None,
        "api_error": None,
        "query_ready": False,
        "missing_slots": [],
        # 本轮仍然处于新的询价中，因此先标回未完成，等待重新补参或查询。
        "query_completed": False,
    }

    # 起运港/目的港保留旧值作为兜底，但只要本轮抽到了新的值，后面 merge 就会覆盖它们。
    return {**state, **reset_fields}


def _build_missing_required_slots(updated: dict) -> list[str]:
    """
    生成一次性追问的必填缺失列表。

    日期规则：
    - 单日期 hbrq 有值则视为满足
    - 或 hbrqBegin + hbrqEnd 成对存在也视为满足
    """
    missing = [field for field in REQUIRED_RATE_FIELDS if not updated.get(field)]

    if not _has_effective_date_value(updated):
        missing.append("hbrq")

    return missing


def _extract_reuse_confirmation_decision(message: str) -> str | None:
    """
    识别用户是否在回答“是否沿用上一轮参数”的确认问题。

    第一版先走规则识别，不依赖模型。
    """
    normalized = (message or "").strip().lower()
    if not normalized:
        return None

    for decision, candidates in REUSE_CONFIRM_REPLIES.items():
        if any(candidate in normalized for candidate in candidates):
            return decision

    return None


def _looks_like_direct_core_refill(message: str, normalized_time_slots: dict, slots: dict) -> bool:
    """
    在等待复用确认时，判断用户是否没有正面回答“是否沿用”，
    而是直接开始重新补重量 / 体积 / 日期。
    """
    normalized = (message or "").strip()
    if not normalized:
        return False

    if any(re.search(pattern, normalized) for pattern in PARAMETER_PATTERNS.values()):
        return True

    return any(
        key in normalized_time_slots or slots.get(key) not in (None, "")
        for key in CORE_REUSE_FIELDS
    )


def _build_reuse_candidate_context(state: AgentState, current_turn_values: dict) -> dict:
    """
    构造“可供当前新询价沿用”的上一轮核心参数快照。

    规则：
    - 只收录本轮没有明确重填、但上一轮已存在的核心字段
    - 第一版只处理重量 / 体积 / 日期，不处理可选字段
    """
    candidate: dict = {}

    if current_turn_values.get("inputWeight") in (None, "") and state.get("inputWeight") not in (None, ""):
        candidate["inputWeight"] = state.get("inputWeight")

    if current_turn_values.get("inputVol") in (None, "") and state.get("inputVol") not in (None, ""):
        candidate["inputVol"] = state.get("inputVol")

    if not _has_effective_date_value(current_turn_values):
        if state.get("hbrq"):
            candidate["hbrq"] = state.get("hbrq")
        elif state.get("hbrqBegin") and state.get("hbrqEnd"):
            candidate["hbrqBegin"] = state.get("hbrqBegin")
            candidate["hbrqEnd"] = state.get("hbrqEnd")

    return candidate


def _build_reuse_confirmation_message(candidate_context: dict, sfg: str | None, mdg: str | None) -> str:
    """生成是否沿用上一轮参数的固定确认文案。"""
    parts = []

    if candidate_context.get("inputWeight") not in (None, ""):
        parts.append(f"{candidate_context['inputWeight']}公斤")

    if candidate_context.get("inputVol") not in (None, ""):
        parts.append(f"{candidate_context['inputVol']}个立方")

    if candidate_context.get("hbrq"):
        parts.append(str(candidate_context["hbrq"]))
    elif candidate_context.get("hbrqBegin") and candidate_context.get("hbrqEnd"):
        parts.append(f"{candidate_context['hbrqBegin']} 至 {candidate_context['hbrqEnd']}")

    condition_text = "、".join(parts) if parts else "上一轮核心条件"
    route_text = f"{(sfg or '').upper()} 到 {(mdg or '').upper()}".strip()

    return (
        f"您是想沿用上一票的 {condition_text} 这个条件，查询 {route_text} 吗？"
        "如果是，我可以直接继续查；如果不是，请告诉我新的重量、体积和日期。"
    )


def _clear_core_fields_for_new_query(state: AgentState) -> AgentState:
    """在用户明确不沿用旧参数时，只清空核心必填字段，保留当前新航线。"""
    return {
        **state,
        "inputWeight": None,
        "inputVol": None,
        "hbrq": None,
        "hbrqBegin": None,
        "hbrqEnd": None,
    }


def _prepare_route_reuse_confirmation_state(state: AgentState, slots: dict) -> AgentState | None:
    """
    为“新航线但询价不完整”的场景构造复用确认状态。

    第一版只做最小闭环：
    - 仅在航线变化时触发
    - 仅确认是否沿用上一轮重量 / 体积 / 日期
    - 不处理包装 / 货类 / 航司等可选字段
    """
    if not _is_route_changed_by_current_turn(state, slots):
        return None

    explicit_current_values = {
        "sfg": slots.get("sfg") or state.get("sfg"),
        "mdg": slots.get("mdg") or state.get("mdg"),
        "inputWeight": slots.get("inputWeight"),
        "inputVol": slots.get("inputVol"),
        "hbrq": slots.get("hbrq"),
        "hbrqBegin": slots.get("hbrqBegin"),
        "hbrqEnd": slots.get("hbrqEnd"),
        "flightType": slots.get("flightType"),
        "packageType": slots.get("packageType"),
        "cargoType": slots.get("cargoType"),
        "twoCode": slots.get("twoCode"),
        "gid": slots.get("gid"),
    }
    explicit_current_values = _normalize_date_slots(explicit_current_values)
    missing = _build_missing_required_slots(explicit_current_values)

    if not missing:
        return None

    candidate_context = _build_reuse_candidate_context(state, explicit_current_values)
    if not candidate_context:
        return None

    return {
        **state,
        **explicit_current_values,
        "query_subtype": "clarify_reply",
        "missing_slots": missing,
        "query_ready": False,
        "query_completed": False,
        "time_clarify_message": None,
        "pending_clarify_slot": None,
        "pending_clarify_message": None,
        "pending_clarify_context": None,
        # 进入“待确认复用”状态后，后续用户的“是/不用/我重新给”会单独走一条确认链路。
        "pending_reuse_confirmation": True,
        "pending_reuse_message": _build_reuse_confirmation_message(
            candidate_context,
            explicit_current_values.get("sfg"),
            explicit_current_values.get("mdg"),
        ),
        "pending_action_type": "reuse_confirmation",
        "pending_action_prompt": _build_reuse_confirmation_message(
            candidate_context,
            explicit_current_values.get("sfg"),
            explicit_current_values.get("mdg"),
        ),
        "pending_action_payload": candidate_context,
        "pending_action_retry_count": 0,
        "reuse_candidate_context": candidate_context,
        "reuse_confirmation_decision": None,
        # 一旦开启新询价路径，上一批结果分析上下文不再继续有效。
        "quote_result_active": False,
        "latest_quote_result": None,
        "result_analysis_intent": None,
        "result_analysis_filters": None,
        "result_reference_field": None,
    }


def _apply_reuse_confirmation_decision(state: AgentState) -> AgentState:
    """
    处理用户对“是否沿用上一轮参数”的确认结果。

    - reuse：把候选上下文回填到当前新航线查询
    - reject：清空核心字段，再进入缺参追问
    """
    decision = state.get("reuse_confirmation_decision")
    candidate_context = state.get("reuse_candidate_context") or {}

    if decision == "reuse":
        updated = {**state}
        for field, value in candidate_context.items():
            if updated.get(field) in (None, ""):
                updated[field] = value
        updated = _normalize_date_slots(updated)
    else:
        updated = _clear_core_fields_for_new_query(state)

    validation = validate_rate_slots(updated)
    updated = validation["normalized_slots"]
    validation_clarify_message = validation.get("clarify_message")
    validation_clarify_slot = validation.get("clarify_slot")
    missing = validation["missing_slots"]
    return {
        **updated,
        "missing_slots": missing,
        "query_ready": len(missing) == 0,
        "query_completed": False,
        "query_subtype": "quote_update",
        "time_clarify_message": None,
        "pending_clarify_slot": None,
        "pending_clarify_message": None,
        "pending_clarify_context": None,
        "pending_action_type": None,
        "pending_action_prompt": None,
        "pending_action_payload": None,
        "pending_action_retry_count": 0,
        "pending_reuse_confirmation": False,
        "pending_reuse_message": None,
        "reuse_candidate_context": None,
        "reuse_confirmation_decision": None,
    }


def _prepare_route_city_clarify_state(state: AgentState, slots: dict, city_label: str) -> AgentState:
    """
    针对“那青岛呢”这类只有城市名、但没有说明改起运港还是目的港的追问，先进入澄清态。

    这里不直接猜角色，避免错误地把“青岛”硬套成起运港或目的港。
    """
    candidate_city_code = slots.get("sfg") or slots.get("mdg")
    return {
        **state,
        "query_subtype": "clarify_reply",
        "query_ready": False,
        "query_completed": False,
        "missing_slots": ["sfg", "mdg"],
        "time_clarify_message": None,
        "pending_clarify_slot": "route_city_role",
        "pending_clarify_message": _build_route_city_clarify_message(city_label),
        "pending_clarify_context": {
            "city_label": city_label,
            "city_code": candidate_city_code,
        },
        "pending_action_type": "route_city_role",
        "pending_action_prompt": _build_route_city_clarify_message(city_label),
        "pending_action_payload": {
            "city_label": city_label,
            "city_code": candidate_city_code,
        },
        "pending_action_retry_count": 0,
        "pending_reuse_confirmation": False,
        "pending_reuse_message": None,
        "reuse_candidate_context": None,
        "reuse_confirmation_decision": None,
        "quote_result_active": False,
        "latest_quote_result": None,
        "result_analysis_intent": None,
        "result_analysis_filters": None,
    }


def _apply_route_city_clarify_decision(state: AgentState, decision: str) -> AgentState:
    """消费“起运港 / 目的港”的澄清答案，并将候选城市代码回填到对应槽位。"""
    clarify_context = state.get("pending_clarify_context") or {}
    city_code = clarify_context.get("city_code")

    updated = {
        **state,
        "pending_clarify_slot": None,
        "pending_clarify_message": None,
        "pending_clarify_context": None,
        "pending_action_type": None,
        "pending_action_prompt": None,
        "pending_action_payload": None,
        "pending_action_retry_count": 0,
    }

    if decision == "sfg":
        updated["sfg"] = city_code
    elif decision == "mdg":
        updated["mdg"] = city_code

    return updated


def _prepare_hbrq_semantic_clarify_state(
    state: AgentState,
    candidate_hbrq: str,
    candidate_text: str,
    resolved_slots_snapshot: dict,
) -> AgentState:
    """
    当用户给出的是“货好日期”类表达时，先澄清它是不是航班日期。

    这里必须把当前已识别出的报价槽位一起保存进 pending payload。
    否则用户下一轮只回复“按航班日期”，系统就会丢掉原本已经给出的航线、重量、体积、包装。
    """
    clarify_message = (
        f"请问您说的 {candidate_text} 是货物备好日期，还是希望查询 {candidate_text} 的航班价格？"
        "如果是航班日期，请直接回复“按航班日期查”；如果只是货好日期，请继续告诉我希望查询的航班日期。"
    )
    pending_payload = {
        "candidate_hbrq": candidate_hbrq,
        "candidate_text": candidate_text,
        "resolved_slots_snapshot": resolved_slots_snapshot,
    }
    missing = _build_missing_required_slots({**resolved_slots_snapshot, "hbrq": None, "hbrqBegin": None, "hbrqEnd": None})
    if "hbrq" not in missing:
        missing.append("hbrq")
    return {
        **state,
        **resolved_slots_snapshot,
        # 候选日期只保存在 pending payload 中，未澄清前不直接写入公开上下文，
        # 避免前端缓存把“货好日期候选值”误当成已确认的航班日期。
        "hbrq": None,
        "hbrqBegin": None,
        "hbrqEnd": None,
        "query_subtype": "clarify_reply",
        "query_ready": False,
        "query_completed": False,
        "missing_slots": missing,
        "time_clarify_message": None,
        "pending_clarify_slot": "hbrq_semantic",
        "pending_clarify_message": clarify_message,
        "pending_clarify_context": pending_payload,
        "pending_action_type": "hbrq_semantic",
        "pending_action_prompt": clarify_message,
        "pending_action_payload": pending_payload,
        "pending_action_retry_count": 0,
        "pending_reuse_confirmation": False,
        "pending_reuse_message": None,
        "reuse_candidate_context": None,
        "reuse_confirmation_decision": None,
    }


def _apply_hbrq_semantic_decision(state: AgentState, decision: str) -> AgentState:
    """消费“货好日期 / 航班日期”语义澄清答案。"""
    clarify_context = state.get("pending_action_payload") or state.get("pending_clarify_context") or {}
    candidate_hbrq = clarify_context.get("candidate_hbrq")
    resolved_slots_snapshot = clarify_context.get("resolved_slots_snapshot") or {}
    restored_state = {**state, **resolved_slots_snapshot}

    if decision == "flight_date" and candidate_hbrq:
        updated = {
            **restored_state,
            "hbrq": candidate_hbrq,
            "hbrqBegin": None,
            "hbrqEnd": None,
            "pending_clarify_slot": None,
            "pending_clarify_message": None,
            "pending_clarify_context": None,
            "pending_action_type": None,
            "pending_action_prompt": None,
            "pending_action_payload": None,
            "pending_action_retry_count": 0,
        }
        missing = _build_missing_required_slots(updated)
        return {
            **updated,
            "missing_slots": missing,
            "query_ready": len(missing) == 0,
            "query_completed": False,
            "query_subtype": "quote_update",
        }

    # 如果用户确认这是“货好日期”，则清掉候选 hbrq，继续追问真正的航班日期。
    missing = _build_missing_required_slots(
        {**resolved_slots_snapshot, "hbrq": None, "hbrqBegin": None, "hbrqEnd": None}
    )
    if "hbrq" not in missing:
        missing.append("hbrq")
    return {
        **restored_state,
        "hbrq": None,
        "hbrqBegin": None,
        "hbrqEnd": None,
        "query_subtype": "clarify_reply",
        "query_ready": False,
        "query_completed": False,
        "missing_slots": missing,
        "time_clarify_message": None,
        "pending_clarify_slot": "hbrq",
        "pending_clarify_message": "请再告诉我您希望查询的航班日期。",
        "pending_clarify_context": None,
        "pending_action_type": "hbrq",
        "pending_action_prompt": "请再告诉我您希望查询的航班日期。",
        "pending_action_payload": None,
        "pending_action_retry_count": 0,
    }


def _build_missing_fields_message(missing_slots: list[str]) -> str:
    """一次性告诉用户当前缺少哪些必填信息。"""
    if "sfg" in missing_slots:
        return build_origin_clarify_message()

    missing_labels = [FIELD_LABELS[field] for field in missing_slots if field in FIELD_LABELS]
    missing_part = "、".join(missing_labels)
    details = []

    if "sfg" in missing_slots:
        details.append("起运港（支持一个、多个，或直接回复“全部港口”）")
    if "mdg" in missing_slots:
        details.append("目的港（运往哪个城市/国家）")
    if "inputWeight" in missing_slots:
        details.append("重量（公斤）")
    if "inputVol" in missing_slots:
        details.append("体积（立方米/CBM）")
    if "packageType" in missing_slots:
        details.append("包装类型（散货或托盘）")
    if "hbrq" in missing_slots:
        # 用户侧不再暴露“日期区间”概念，统一只提示补充单一航班日期。
        details.append("航班日期")

    return f"为了帮您准确查询运价，我还缺少这些必填信息：{missing_part}。请补充：{'、'.join(details)}。"


def _detect_result_display_mode(message: str, existing_mode: str | None = None) -> str | None:
    """
    识别当前询价是否要求“一个直飞一个中转”的定向展示模式。

    第一版只识别高频明确表达，不把它当成查询参数，而是作为结果渲染偏好。
    """
    normalized = (message or "").strip()
    if ("直飞" in normalized or "直达" in normalized) and "中转" in normalized and any(
        keyword in normalized for keyword in ["一个", "分别", "各", "一条", "一票"]
    ):
        return "direct_transit_pair"
    return existing_mode


def _format_currency(value) -> str:
    """统一金额展示格式。"""
    if value in (None, ""):
        return "-"
    try:
        return f"{float(value):.2f}CNY"
    except (TypeError, ValueError):
        return str(value)


def _normalize_package_bucket(package_value: str | None) -> str | None:
    """将包装展示值映射为默认首屏需要的两类包装桶。"""
    normalized = str(package_value or "").strip()
    if normalized == "散货":
        return "散货"
    if normalized == "托盘":
        return "托盘"
    return None


def _filter_raw_quotes_by_package_type(quotes: list[dict], package_type: str | None) -> list[dict]:
    """
    在展示层再做一次包装类型防御性过滤。

    原因：
    - packageType 已升级为正式必填
    - 即使接口理论上已按 packageType 查询，展示层也要避免混入另一种包装结果
    """
    normalized_package_type = _normalize_package_type(package_type)
    if not normalized_package_type:
        return list(quotes)

    filtered = [
        quote
        for quote in quotes
        if _normalize_package_bucket(quote.get("packingDisplay")) == normalized_package_type
    ]
    return filtered


def _apply_package_type_filter_to_result(result: dict, package_type: str | None) -> dict:
    """
    把当前选择的包装类型同步收口到接口结果对象里。

    这样后续：
    - 首屏默认最低参考
    - latest_quote_result
    - result_analysis / result_reference

    都基于同一批已收口的数据，不会出现首屏看托盘、分析链却拿混合结果的问题。
    """
    normalized_package_type = _normalize_package_type(package_type)
    if not normalized_package_type:
        return result

    filtered_result = {**result, "packageType": normalized_package_type}
    if result.get("quotes") is not None:
        filtered_result["quotes"] = _filter_raw_quotes_by_package_type(result.get("quotes") or [], normalized_package_type)
    if result.get("exact_quotes") is not None:
        filtered_result["exact_quotes"] = _filter_raw_quotes_by_package_type(result.get("exact_quotes") or [], normalized_package_type)
    if result.get("similar_quotes") is not None:
        filtered_result["similar_quotes"] = _filter_raw_quotes_by_package_type(result.get("similar_quotes") or [], normalized_package_type)
    return filtered_result


def _group_quotes_for_default_best(quotes: list[dict]) -> dict[str, list[dict]]:
    """
    为默认首屏最低价准备包装分组。

    口径：
    - 优先使用纯“散货”/纯“托盘”
    - 若某一类纯包装不存在，再允许“散货/托盘”作为补位候选
    """
    pure_groups = defaultdict(list)
    combo_quotes = []

    for quote in quotes:
        package_value = str(quote.get("packingDisplay") or "")
        bucket = _normalize_package_bucket(package_value)
        if bucket:
            pure_groups[bucket].append(quote)
        elif "散货" in package_value and "托盘" in package_value:
            combo_quotes.append(quote)

    grouped = {"散货": list(pure_groups.get("散货", [])), "托盘": list(pure_groups.get("托盘", []))}
    for bucket in ["散货", "托盘"]:
        if not grouped[bucket] and combo_quotes:
            grouped[bucket] = list(combo_quotes)

    return grouped


def _pick_cheapest_quote(quotes: list[dict]) -> dict | None:
    """按合计挑选最便宜一条；若并列最低，随机返回一条。"""
    if not quotes:
        return None

    sorted_quotes = sorted(quotes, key=lambda item: float(item.get("priceTotal") or 0))
    cheapest_total = float(sorted_quotes[0].get("priceTotal") or 0)
    cheapest_candidates = [
        quote for quote in sorted_quotes if float(quote.get("priceTotal") or 0) == cheapest_total
    ]
    return random.choice(cheapest_candidates)


def _format_route(sfg: str, zzg: str | None, mdg: str) -> str:
    """输出航线与直达/中转展示值。"""
    if not zzg or zzg == "直达":
        return f"{sfg.upper()}-{mdg.upper()}"
    return f"{sfg.upper()}-{zzg.upper()}-{mdg.upper()}"


def _group_quotes_by_date(quotes: list[dict]) -> dict[str, list[dict]]:
    """按航班日期分组，便于输出多日期 Markdown 表格。"""
    grouped = defaultdict(list)
    for quote in quotes:
        date_key = quote.get("hbrq") or "未知日期"
        grouped[str(date_key)].append(quote)
    return dict(grouped)


def _build_markdown_table(quotes: list[dict], sfg: str, mdg: str, include_unit_price: bool = True) -> str:
    """将运价结果稳定地输出成 Markdown table。"""
    headers = ["航司", "航线", "货类", "包装"]
    if include_unit_price:
        headers.append("预估运费单价")
    headers.extend(["预估运费总价", "预估卡车费", "合计"])

    rows = []
    for quote in quotes:
        row = [
            quote.get("twocode") or "-",
            quote.get("routingDisplay") or "-",
            quote.get("cargoType") or "-",
            quote.get("packingDisplay") or "-",
        ]
        if include_unit_price:
            row.append(_format_currency(quote.get("unitPrice")))
        row.extend(
            [
                _format_currency(quote.get("flightPriceTotal")),
                _format_currency(quote.get("truckPriceTotal")),
                _format_currency(quote.get("priceTotal")),
            ]
        )
        rows.append("| " + " | ".join(row) + " |")

    header_line = "| " + " | ".join(headers) + " |"
    separator_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    return "\n".join([header_line, separator_line, *rows])


def _build_quotes_summary(quotes: list[dict]) -> str:
    """给报价结果补一句简短总结，避免完全依赖模型。"""
    if not quotes:
        return ""

    cheapest = min(quotes, key=lambda item: float(item.get("priceTotal") or 0))
    return (
        f"共找到 {len(quotes)} 条报价。当前最低参考方案为 "
        f"{cheapest.get('twocode') or '-'} / {cheapest.get('zzg') or '直达'}，"
        f"合计 {_format_currency(cheapest.get('priceTotal'))}。"
    )


def _build_default_best_quote_sections(
    quotes: list[dict], sfg: str, mdg: str, *, include_intro: bool = True, preferred_package_type: str | None = None
) -> str:
    """默认首屏按包装类型展示最低价方案。"""
    normalized_package_type = _normalize_package_type(preferred_package_type)
    if normalized_package_type:
        filtered_quotes = _filter_raw_quotes_by_package_type(quotes, normalized_package_type)
        cheapest_quote = _pick_cheapest_quote(filtered_quotes)
        if not cheapest_quote:
            return f"抱歉，当前结果中暂未找到符合 {normalized_package_type} 条件的报价。"

        intro = f"先为您展示当前 {normalized_package_type} 对应的最低参考方案。如需全部报价明细，您也可以继续告诉我“展示全部数据”。"
        section = f"**{normalized_package_type}最低参考**\n\n{_build_markdown_table([cheapest_quote], sfg, mdg, include_unit_price=True)}"
        return intro + "\n\n" + section if include_intro else section

    grouped = _group_quotes_for_default_best(quotes)
    sections = []

    for package_bucket in ["散货", "托盘"]:
        cheapest_quote = _pick_cheapest_quote(grouped.get(package_bucket, []))
        if not cheapest_quote:
            continue
        sections.append(f"**{package_bucket}最低参考**\n\n{_build_markdown_table([cheapest_quote], sfg, mdg, include_unit_price=True)}")

    if not sections:
        return _render_quote_sections(quotes, sfg, mdg, include_unit_price=True)

    intro = "先为您展示当前最有参考价值的散货和托盘最低价方案。如需全部报价明细，您也可以继续告诉我“展示全部数据”。"
    if include_intro:
        return intro + "\n\n" + "\n\n".join(sections)
    return "\n\n".join(sections)


def _build_direct_transit_pair_sections(
    quotes: list[dict], latest_quote_result: dict | None, sfg: str, mdg: str
) -> str:
    """按直飞 / 中转各取一条最低价，满足“一个直飞一个中转”的展示需求。"""
    standard_quotes = (latest_quote_result or {}).get("quotes") or []
    route_type_to_raw = defaultdict(list)
    for quote in standard_quotes:
        raw = quote.get("raw")
        if raw:
            route_type_to_raw[quote.get("route_type")].append(raw)

    sections = []
    for route_type in ["直达", "中转"]:
        cheapest_quote = _pick_cheapest_quote(route_type_to_raw.get(route_type, []))
        if not cheapest_quote:
            continue
        sections.append(f"**{route_type}**\n\n{_build_markdown_table([cheapest_quote], sfg, mdg, include_unit_price=True)}")

    if not sections:
        return _build_default_best_quote_sections(quotes, sfg, mdg)

    return "已按您的要求分别为您整理一条直飞和一条中转的参考方案：\n\n" + "\n\n".join(sections)


def _render_quote_sections(quotes: list[dict], sfg: str, mdg: str, include_unit_price: bool) -> str:
    """按日期分块输出 Markdown 表格和摘要。"""
    sections = []
    for date_key, date_quotes in sorted(_group_quotes_by_date(quotes).items()):
        table = _build_markdown_table(date_quotes, sfg, mdg, include_unit_price=include_unit_price)
        summary = _build_quotes_summary(date_quotes)
        section = [f"**{date_key}**", "", table]
        if summary:
            section.extend(["", summary])
        sections.append("\n".join(section))

    return "\n\n".join(sections)


def _build_exact_result_message(state: AgentState, api_result: dict) -> str:
    """精确查询命中时的稳定回复模板。"""
    package_type = _normalize_package_type(api_result.get("packageType") or state.get("packageType"))
    filtered_quotes = _filter_raw_quotes_by_package_type(api_result.get("quotes", []), package_type)
    date_desc = api_result.get("hbrq")
    if api_result.get("hbrqBegin") and api_result.get("hbrqEnd"):
        date_desc = f"{api_result['hbrqBegin']} 至 {api_result['hbrqEnd']}"

    header = (
        f"已为您查询到 {state['sfg'].upper()} 至 {state['mdg'].upper()} 的运价信息。"
        f"查询条件：{api_result['actual_weight']}kg / {state['inputVol']}CBM，日期 {date_desc}。"
    )
    if state.get("result_display_mode") == "direct_transit_pair":
        quote_sections = _build_direct_transit_pair_sections(
            filtered_quotes,
            state.get("latest_quote_result"),
            api_result["sfg"],
            api_result["mdg"],
        )
    else:
        quote_sections = _build_default_best_quote_sections(
            filtered_quotes,
            api_result["sfg"],
            api_result["mdg"],
            preferred_package_type=package_type,
        )
    return f"{header}\n\n{quote_sections}"


def _build_similar_result_message(state: AgentState, api_result: dict) -> str:
    """精确查询无结果、但找到了相近日期运价时的回复模板。"""
    package_type = _normalize_package_type(api_result.get("packageType") or state.get("packageType"))
    filtered_quotes = _filter_raw_quotes_by_package_type(api_result.get("similar_quotes", []), package_type)
    intro = (
        "抱歉，当前日期暂未查询到完全匹配的运价信息。"
        f"您可以联系我司相关人员 {RESULT_CONTACT_EMAIL} 获取更多咨询。\n\n"
        f"这边已为您自动查询到同航线、同重量体积条件下未来 7 天内的类似运价信息，请参考。"
    )
    if state.get("result_display_mode") == "direct_transit_pair":
        quote_sections = _build_direct_transit_pair_sections(
            filtered_quotes,
            state.get("latest_quote_result"),
            api_result["sfg"],
            api_result["mdg"],
        )
    else:
        quote_sections = _build_default_best_quote_sections(
            filtered_quotes,
            api_result["sfg"],
            api_result["mdg"],
            include_intro=False,
            preferred_package_type=package_type,
        )
    return f"{intro}\n\n{quote_sections}"


def _build_no_result_message() -> str:
    """精确查询和类似查询都无结果时的回复模板。"""
    return (
        "抱歉，暂时未满足相关运价信息，"
        f"您可以咨询我司相关人员 邮箱：{RESULT_CONTACT_EMAIL} 获取更多咨询。"
    )


def _prepare_state_for_result_reference(state: AgentState, result_reference_request: dict) -> AgentState:
    """
    进入结果引用解释链前，先记录当前用户正在追问哪个结果字段。

    这一步只做意图和字段定位，不做任何重查。
    """
    return {
        **state,
        "intent": "result_reference",
        "query_subtype": "result_reference",
        "response_mode": "summary_only",
        "quantity_mode": "single",
        "result_reference_field": result_reference_request.get("field"),
        "result_reference_request": result_reference_request,
        "support_info_kind": None,
    }


def _prepare_state_for_result_analysis(state: AgentState, override_payload: dict | None = None) -> AgentState:
    """
    进入结果分析链前，先根据当前消息解析子意图和过滤条件。

    第一批只覆盖结构化结果处理能力，不重新调用运价接口。
    """
    last_message = state["messages"][-1].content.strip()
    latest_quote_result = state.get("latest_quote_result")
    analysis_intent, filters, quantity_mode, response_mode = analyze_result_request(last_message, latest_quote_result or {})
    override_intent = (override_payload or {}).get("sub_intent")
    if override_intent in {
        "all_list",
        "lowest",
        "filter_list",
        "summary",
        "route_group_compare",
        "carrier_group_compare",
    }:
        analysis_intent = override_intent
        if analysis_intent == "all_list":
            quantity_mode = "multi"
            response_mode = "summary_plus_table"
    return {
        **state,
        "intent": "result_analysis",
        "query_subtype": "result_expand" if analysis_intent == "all_list" else "result_filter",
        "response_mode": response_mode,
        "quantity_mode": quantity_mode,
        "result_analysis_intent": analysis_intent,
        "result_analysis_filters": filters,
        "result_reference_field": None,
        "result_reference_request": None,
        "support_info_kind": None,
    }


def _prepare_state_for_support_info(state: AgentState, support_info_kind: str) -> AgentState:
    """为业务服务信息或能力说明问题准备轻量答复状态。"""
    return {
        **state,
        "intent": "support_info",
        "query_subtype": support_info_kind,
        "response_mode": "summary_only",
        "quantity_mode": None,
        "support_info_kind": support_info_kind,
        "result_reference_field": None,
        "result_reference_request": None,
    }


def intent_node(state: AgentState) -> AgentState:
    """意图识别节点，同时负责处理新完整询价的会话重置。"""
    started = time.perf_counter()
    last_message = state["messages"][-1].content.strip()
    state = {
        **state,
        "query_subtype": None,
        "pending_action_type": _derive_pending_action_type(state),
        "pending_action_prompt": _derive_pending_action_prompt(state),
        "pending_action_payload": _derive_pending_action_payload(state),
    }

    if state.get("reset_quote_context"):
        logger.info(
            "intent_node reset hit | reset_quote_context=true | last_message=%s | old_context=%s",
            last_message,
            _current_rate_context(state),
        )
        state = _reset_rate_context(state)

    if _looks_like_new_complete_rate_query(last_message, state):
        logger.info(
            "intent_node reset hit | new_complete_rate_query=true | last_message=%s | old_context=%s",
            last_message,
            _current_rate_context(state),
        )
        state = _reset_rate_context(state)

    # 如果当前正在等待枚举式澄清答案，而用户只回复了“是的/对/嗯”，
    # 不能直接掉 unknown，也不能擅自猜。最稳的做法是继续明确追问。
    if state.get("pending_action_type") == "route_city_role" and _looks_like_weak_confirmation(last_message):
        clarify_context = state.get("pending_action_payload") or state.get("pending_clarify_context") or {}
        city_label = clarify_context.get("city_label", "该城市")
        retry_message = _build_route_city_retry_message(city_label)
        logger.info(
            "intent_node rule hit | route_city_clarify_retry=true | last_message=%s",
            last_message,
        )
        updated = {
            **state,
            "intent": "rate_query",
            "query_subtype": "clarify_reply",
            "query_ready": False,
            "query_completed": False,
            "missing_slots": ["sfg", "mdg"],
            "pending_clarify_message": retry_message,
            "pending_action_prompt": retry_message,
            "pending_action_retry_count": int(state.get("pending_action_retry_count") or 0) + 1,
        }
        logger.info(
            "node intent finished | elapsed=%.3fs | intent=%s",
            time.perf_counter() - started,
            "rate_query",
        )
        return updated

    if _looks_like_greeting(last_message):
        logger.info(
            "intent_node rule hit | greeting=true | last_message=%s",
            last_message,
        )
        logger.info(
            "node intent finished | elapsed=%.3fs | intent=%s",
            time.perf_counter() - started,
            "support_info",
        )
        return _prepare_state_for_support_info(state, "greeting")

    if _looks_like_small_talk(last_message):
        logger.info(
            "intent_node rule hit | small_talk=true | last_message=%s",
            last_message,
        )
        logger.info(
            "node intent finished | elapsed=%.3fs | intent=%s",
            time.perf_counter() - started,
            "support_info",
        )
        return _prepare_state_for_support_info(state, "smalltalk")

    support_info_kind = _detect_support_info_kind(last_message)
    if support_info_kind:
        logger.info(
            "intent_node rule hit | support_info=true | last_message=%s | kind=%s",
            last_message,
            support_info_kind,
        )
        logger.info(
            "node intent finished | elapsed=%.3fs | intent=%s",
            time.perf_counter() - started,
            "support_info",
        )
        return _prepare_state_for_support_info(state, support_info_kind)

    if _looks_like_explicit_new_quote_request(last_message):
        logger.info(
            "intent_node reset hit | explicit_new_quote=true | last_message=%s | old_context=%s",
            last_message,
            _current_rate_context(state),
        )
        state = _reset_rate_context(state)
        return {
            **state,
            "intent": "rate_query",
            "query_subtype": "new_quote",
        }

    result_reference_request = None
    if state.get("quote_result_active"):
        result_reference_request = analyze_result_reference_request(last_message, state.get("latest_quote_result"))
        if result_reference_request:
            logger.info(
                "intent_node rule hit | result_reference=true | last_message=%s | request=%s",
                last_message,
                result_reference_request,
            )
            logger.info(
                "node intent finished | elapsed=%.3fs | intent=%s",
                time.perf_counter() - started,
                "result_reference",
            )
            return _prepare_state_for_result_reference(state, result_reference_request)

    if state.get("quote_result_active") and is_result_analysis_request(last_message, state.get("latest_quote_result")):
        logger.info(
            "intent_node rule hit | result_analysis=true | last_message=%s",
            last_message,
        )
        logger.info(
            "node intent finished | elapsed=%.3fs | intent=%s",
            time.perf_counter() - started,
            "result_analysis",
        )
        return _prepare_state_for_result_analysis(state)

    # packageType 现在是正式必填字段。
    # 当系统正在等包装类型，或者用户在当前报价上下文里只回复“托盘 / 散货”时，
    # 必须直接回到运价链补槽位，而不是掉到 unknown。
    if _looks_like_package_type_reply(last_message, state):
        logger.info(
            "intent_node rule hit | package_type_reply=true | last_message=%s | packageType=%s",
            last_message,
            _extract_package_type_from_message(last_message),
        )
        logger.info(
            "node intent finished | elapsed=%.3fs | intent=%s",
            time.perf_counter() - started,
            "rate_query",
        )
        return {**state, "intent": "rate_query", "query_subtype": "quote_update"}

    # 如果当前正在等待用户确认“是否沿用上一轮参数”，
    # 那么“是 / 不用 / 重新来”这类回复不应该再回到开放式意图识别，
    # 而应直接进入运价查询链，由 slot_node 消费确认结果。
    if state.get("pending_reuse_confirmation"):
        reuse_confirmation_decision = _extract_reuse_confirmation_decision(last_message)
        if reuse_confirmation_decision:
            logger.info(
                "intent_node rule hit | reuse_confirmation_reply=true | last_message=%s | decision=%s",
                last_message,
                reuse_confirmation_decision,
            )
            logger.info(
                "node intent finished | elapsed=%.3fs | intent=%s",
                time.perf_counter() - started,
                "rate_query",
            )
            return {
                **state,
                "intent": "rate_query",
                "query_subtype": "reuse_confirmation",
                "reuse_confirmation_decision": reuse_confirmation_decision,
            }

    # 如果当前正在等待用户确认“青岛是起运港还是目的港”，
    # 这类回复也应直接回到运价链，而不是再走开放式意图识别。
    if _looks_like_route_city_clarify_reply(last_message, state):
        logger.info(
            "intent_node rule hit | route_city_clarify_reply=true | last_message=%s",
            last_message,
        )
        logger.info(
            "node intent finished | elapsed=%.3fs | intent=%s",
            time.perf_counter() - started,
            "rate_query",
        )
        return {**state, "intent": "rate_query", "query_subtype": "clarify_reply"}

    # 如果当前正在等待用户确认“货好日期还是航班日期”，
    # 回复中只要明确到了语义角色，就直接回到补槽位链路。
    if _looks_like_hbrq_semantic_reply(last_message, state):
        logger.info(
            "intent_node rule hit | hbrq_semantic_reply=true | last_message=%s",
            last_message,
        )
        logger.info(
            "node intent finished | elapsed=%.3fs | intent=%s",
            time.perf_counter() - started,
            "rate_query",
        )
        return {**state, "intent": "rate_query", "query_subtype": "clarify_reply"}

    if state.get("pending_clarify_slot") == "hbrq_semantic":
        llm_semantic_decision = _classify_hbrq_semantic_reply_with_llm(last_message, state)
        if llm_semantic_decision:
            payload = {
                **(state.get("pending_action_payload") or state.get("pending_clarify_context") or {}),
                "resolved_decision": llm_semantic_decision,
            }
            logger.info(
                "intent_node llm hit | hbrq_semantic_reply=true | last_message=%s | decision=%s",
                last_message,
                llm_semantic_decision,
            )
            logger.info(
                "node intent finished | elapsed=%.3fs | intent=%s",
                time.perf_counter() - started,
                "rate_query",
            )
            return {
                **state,
                "intent": "rate_query",
                "query_subtype": "clarify_reply",
                "pending_action_payload": payload,
                "pending_clarify_context": payload,
            }

    # 如果上一轮正在等用户澄清日期，这一轮即使只回复“这周六 / 下周六”这类短句，
    # 也应该直接视为继续补槽位，而不是重新走开放式意图识别。
    if _looks_like_time_clarify_reply(last_message, state):
        logger.info(
            "intent_node rule hit | time_clarify_reply=true | last_message=%s | pending_clarify_slot=%s",
            last_message,
            state.get("pending_clarify_slot"),
        )
        logger.info(
            "node intent finished | elapsed=%.3fs | intent=%s",
            time.perf_counter() - started,
            "rate_query",
        )
        return {**state, "intent": "rate_query", "query_subtype": "clarify_reply"}

    # “货大概 5 月 27 号好 / 5 月 27 号能出货”这类表达，
    # 本质上仍在当前询价上下文里，只是日期语义需要进一步澄清。
    if _looks_like_industry_date_semantic_followup(last_message, state):
        logger.info(
            "intent_node rule hit | industry_date_semantic_followup=true | last_message=%s",
            last_message,
        )
        logger.info(
            "node intent finished | elapsed=%.3fs | intent=%s",
            time.perf_counter() - started,
            "rate_query",
        )
        return {**state, "intent": "rate_query", "query_subtype": "quote_update"}

    if _looks_like_greeting(last_message):
        logger.info(
            "intent_node rule hit | greeting=true | last_message=%s",
            last_message,
        )
        logger.info(
            "node intent finished | elapsed=%.3fs | intent=%s",
            time.perf_counter() - started,
            "support_info",
        )
        return _prepare_state_for_support_info(state, "greeting")

    # 非 greeting 的短闲聊仍走原兜底策略，避免误触发业务工作流。
    if _looks_like_small_talk(last_message):
        logger.info(
            "intent_node rule hit | small_talk_guard=true | last_message=%s",
            last_message,
        )
        logger.info(
            "node intent finished | elapsed=%.3fs | intent=%s",
            time.perf_counter() - started,
            "unknown",
        )
        return {
            **state,
            "intent": "unknown",
            "query_subtype": None,
            "response_mode": None,
            "quantity_mode": None,
            "support_info_kind": None,
            "result_reference_request": None,
        }

    # “那青岛呢 / 广州呢 / 从青岛出发呢”这类消息是明显承接上一轮的航线变更，
    # 不应掉到兜底。第一版先把它们稳定送回运价主链，再由 slot_node 做角色澄清。
    if _looks_like_city_followup(last_message, state):
        logger.info(
            "intent_node rule hit | city_followup_rate_query=true | last_message=%s | context=%s",
            last_message,
            _current_rate_context(state),
        )
        logger.info(
            "node intent finished | elapsed=%.3fs | intent=%s",
            time.perf_counter() - started,
            "rate_query",
        )
        return {**state, "intent": "rate_query", "query_subtype": "quote_update"}

    if _looks_like_rate_followup(last_message, state):
        logger.info(
            "intent_node rule hit | followup_rate_query=true | last_message=%s | context=%s",
            last_message,
            _current_rate_context(state),
        )
        logger.info(
            "node intent finished | elapsed=%.3fs | intent=%s",
            time.perf_counter() - started,
            "rate_query",
        )
        return {**state, "intent": "rate_query", "query_subtype": "quote_update"}

    llm_quote_followup = _classify_quote_followup_with_llm(last_message, state)
    if llm_quote_followup:
        llm_intent = llm_quote_followup.get("intent")
        logger.info(
            "intent_node llm hit | quote_followup=true | last_message=%s | payload=%s",
            last_message,
            llm_quote_followup,
        )
        logger.info(
            "node intent finished | elapsed=%.3fs | intent=%s",
            time.perf_counter() - started,
            llm_intent,
        )
        if llm_intent == "result_reference" and llm_quote_followup.get("field"):
            return _prepare_state_for_result_reference(
                state,
                {"field": llm_quote_followup.get("field"), "selector": "current"},
            )
        if llm_intent == "result_analysis":
            return _prepare_state_for_result_analysis(state, llm_quote_followup)
        if llm_intent == "rate_query":
            return {**state, "intent": "rate_query", "query_subtype": "quote_update"}
        if llm_intent == "clarify_needed":
            return {
                **state,
                "intent": "rate_query",
                "query_subtype": "clarify_reply",
            }

    llm = get_llm()
    response = llm.invoke(
        [
            SystemMessage(content=INTENT_SYSTEM),
            HumanMessage(content=INTENT_USER.format(message=last_message)),
        ]
    )

    intent = response.content.strip().lower()
    if intent not in {"rate_query", "rag", "unknown"}:
        intent = "unknown"

    logger.info(
        "intent_node debug | last_message=%s | response.content=%s | intent=%s",
        last_message,
        response.content,
        intent,
    )
    logger.info(
        "node intent finished | elapsed=%.3fs | intent=%s",
        time.perf_counter() - started,
        intent,
    )

    query_subtype = "new_quote" if intent == "rate_query" and not _has_rate_context(state) else None
    return {
        **state,
        "intent": intent,
        "query_subtype": query_subtype,
        "response_mode": None,
        "quantity_mode": None,
        "support_info_kind": None,
        "result_reference_request": None,
    }


def slot_node(state: AgentState) -> AgentState:
    """槽位提取节点，负责抽取必填/可选字段，并处理旧值清空规则。"""
    started = time.perf_counter()
    last_message = state["messages"][-1].content.strip()
    pending_action_type = _derive_pending_action_type(state)
    original_rate_context = _current_rate_context(state)
    normalized_time_slots, time_clarify_message = _resolve_relative_date_from_message(last_message, state)
    result_display_mode = _detect_result_display_mode(last_message, state.get("result_display_mode"))
    state = {**state, "result_display_mode": result_display_mode}

    history_lines = []
    for msg in state["messages"]:
        role = "用户" if isinstance(msg, HumanMessage) else "助手"
        history_lines.append(f"{role}：{msg.content}")
    history_text = "\n".join(history_lines)

    clarify_slots = {}

    # 如果用户在“起运港 / 目的港”二选一澄清里只回复了模糊确认，
    # 这里不要继续抽槽位或重查，直接把状态原样交给 ask_node 再追问一次。
    if pending_action_type == "route_city_role" and _looks_like_weak_confirmation(last_message):
        logger.info(
            "slot_node clarify retry hold | pending_action_type=%s | last_message=%s",
            pending_action_type,
            last_message,
        )
        return {
            **state,
            "query_ready": False,
            "query_completed": False,
            "missing_slots": ["sfg", "mdg"],
        }

    # 先消费“青岛是起运港还是目的港”的澄清回答，避免本轮再跑一次槽位抽取。
    if state.get("pending_clarify_slot") == "route_city_role":
        route_role_decision = _extract_route_role_decision(last_message)
        if route_role_decision:
            state = _apply_route_city_clarify_decision(state, route_role_decision)
            clarify_slots[route_role_decision] = state.get(route_role_decision)

    # 再消费“货好日期还是航班日期”的语义澄清回答。
    if state.get("pending_clarify_slot") == "hbrq_semantic":
        hbrq_semantic_decision = (state.get("pending_action_payload") or {}).get("resolved_decision")
        if not hbrq_semantic_decision:
            hbrq_semantic_decision = _extract_hbrq_semantic_decision(last_message)
        if not hbrq_semantic_decision:
            hbrq_semantic_decision = _classify_hbrq_semantic_reply_with_llm(last_message, state)
        if hbrq_semantic_decision == "cargo_ready":
            return _apply_hbrq_semantic_decision(state, hbrq_semantic_decision)
        if hbrq_semantic_decision == "flight_date":
            state = _apply_hbrq_semantic_decision(state, hbrq_semantic_decision)
            clarify_slots["hbrq"] = state.get("hbrq")

    # 先消费“是否沿用上一轮参数”的明确确认结果，避免这一轮再走 LLM 槽位抽取。
    if state.get("pending_reuse_confirmation") and state.get("reuse_confirmation_decision") in {"reuse", "reject"}:
        updated_state = _apply_reuse_confirmation_decision(state)
        logger.info(
            "slot_node reuse confirmation applied | decision=%s | merged=%s",
            state.get("reuse_confirmation_decision"),
            {
                "sfg": updated_state.get("sfg"),
                "mdg": updated_state.get("mdg"),
                "inputWeight": updated_state.get("inputWeight"),
                "inputVol": updated_state.get("inputVol"),
                "hbrq": updated_state.get("hbrq"),
                "hbrqBegin": updated_state.get("hbrqBegin"),
                "hbrqEnd": updated_state.get("hbrqEnd"),
            },
        )
        return updated_state

    if clarify_slots:
        slots = dict(clarify_slots)
    else:
        llm = get_llm()
        response = llm.invoke(
            [
                SystemMessage(content=build_slot_system(state.get("current_beijing_date") or "")),
                HumanMessage(content=SLOT_USER.format(history=history_text)),
            ]
        )

        try:
            slots = json.loads(response.content.strip())
        except json.JSONDecodeError:
            content = response.content
            start = content.find("{")
            end = content.rfind("}") + 1
            try:
                slots = json.loads(content[start:end])
            except Exception:
                slots = {}

    # 包装类型是正式必填字段，不能完全依赖 LLM 在短句里稳定抽取。
    # 因此这里用规则再兜一层，保证用户只回复“托盘 / 散货”时仍能稳定补槽位。
    direct_package_type = _extract_package_type_from_message(last_message)
    if direct_package_type:
        slots["packageType"] = direct_package_type

    # 多始发港与“全部查询”优先走规则解析，再由 LLM 兜底补齐其余槽位。
    normalized_origin_codes = extract_origin_codes(last_message)
    if normalized_origin_codes and (
        looks_like_origin_reply(last_message, state.get("missing_slots"))
        or "," in normalized_origin_codes
        or state.get("sfg") in (None, "")
    ):
        slots["sfg"] = normalized_origin_codes

    # 时间字段优先使用后端标准化规则结果，避免“今天 / 明后天 / 周末”等完全依赖模型自由理解。
    slots.update({key: value for key, value in normalized_time_slots.items() if value is not None or key in normalized_time_slots})
    if slots.get("packageType"):
        slots["packageType"] = _normalize_package_type(slots.get("packageType"))

    # 对“货5月22日准备好”这类行业表述，第一版先澄清语义，不直接把日期写入航班日期。
    candidate_hbrq = slots.get("hbrq") or normalized_time_slots.get("hbrq")
    if (
        state.get("pending_clarify_slot") not in {"hbrq", "hbrq_semantic"}
        and _looks_like_cargo_ready_phrase(last_message)
        and candidate_hbrq
    ):
        return _prepare_hbrq_semantic_clarify_state(
            {
                **state,
                "result_display_mode": result_display_mode,
            },
            candidate_hbrq,
            _extract_human_date_token(last_message, candidate_hbrq),
            _build_rate_context_snapshot(state, slots),
        )

    # 对“那青岛呢”这类短追问，不直接猜是起运港还是目的港，先做角色澄清。
    city_label = _extract_city_followup_label(last_message)
    if (
        state.get("pending_clarify_slot") is None
        and _looks_like_city_followup(last_message, state)
        and city_label
        and "从" not in last_message
        and "到" not in last_message
        and (slots.get("sfg") or slots.get("mdg"))
    ):
        return _prepare_route_city_clarify_state(
            {
                **state,
                "result_display_mode": result_display_mode,
            },
            slots,
            city_label,
        )

    # 如果当前还处于“待确认沿用旧参数”状态，而用户没有正面回复“是/不用”，
    # 反而直接开始补新的重量 / 体积 / 日期，那么应视为用户放弃沿用旧值，
    # 从本轮起按新的补参流程继续，不再继续追问“是否沿用”。
    if state.get("pending_reuse_confirmation") and _looks_like_direct_core_refill(last_message, normalized_time_slots, slots):
        state = {
            **_clear_core_fields_for_new_query(state),
            "pending_action_type": None,
            "pending_action_prompt": None,
            "pending_action_payload": None,
            "pending_action_retry_count": 0,
            "pending_reuse_confirmation": False,
            "pending_reuse_message": None,
            "reuse_candidate_context": None,
            "reuse_confirmation_decision": None,
        }

    reuse_confirmation_state = _prepare_route_reuse_confirmation_state(state, slots)
    if reuse_confirmation_state:
        logger.info(
            "slot_node reuse confirm hit | last_message=%s | old_context=%s | extracted=%s | candidate=%s",
            last_message,
            original_rate_context,
            slots,
            reuse_confirmation_state.get("reuse_candidate_context"),
        )
        return reuse_confirmation_state

    # 如果上一轮已完成，且本轮明确切换了新的航线，
    # 但用户没有把重量/体积/日期等参数一起补齐，则不能继续沿用旧询价参数。
    # 这里先重置旧参数，再让当前轮抽取结果重新回填，后续自然会进入缺参提醒。
    if _is_route_changed_by_current_turn(state, slots):
        logger.info(
            "slot_node route reset hit | last_message=%s | old_context=%s | extracted=%s",
            last_message,
            original_rate_context,
            slots,
        )
        state = _reset_state_for_new_route_query(state, slots)

    cleared_fields = _detect_cleared_slots(last_message)
    updated = {
        "sfg": _merge_slot_value(slots.get("sfg"), state.get("sfg"), "sfg", cleared_fields),
        "mdg": _merge_slot_value(slots.get("mdg"), state.get("mdg"), "mdg", cleared_fields),
        "inputWeight": _merge_slot_value(
            slots.get("inputWeight"), state.get("inputWeight"), "inputWeight", cleared_fields
        ),
        "inputVol": _merge_slot_value(
            slots.get("inputVol"), state.get("inputVol"), "inputVol", cleared_fields
        ),
        "hbrq": _merge_slot_value(slots.get("hbrq"), state.get("hbrq"), "hbrq", cleared_fields),
        "hbrqBegin": _merge_slot_value(
            slots.get("hbrqBegin"), state.get("hbrqBegin"), "hbrqBegin", cleared_fields
        ),
        "hbrqEnd": _merge_slot_value(
            slots.get("hbrqEnd"), state.get("hbrqEnd"), "hbrqEnd", cleared_fields
        ),
        "flightType": _merge_slot_value(
            slots.get("flightType"), state.get("flightType"), "flightType", cleared_fields
        ),
        "packageType": _merge_slot_value(
            slots.get("packageType"), state.get("packageType"), "packageType", cleared_fields
        ),
        "cargoType": _merge_slot_value(
            slots.get("cargoType"), state.get("cargoType"), "cargoType", cleared_fields
        ),
        "twoCode": _merge_slot_value(slots.get("twoCode"), state.get("twoCode"), "twoCode", cleared_fields),
        "gid": _merge_slot_value(slots.get("gid"), state.get("gid"), "gid", cleared_fields),
    }
    updated = _normalize_date_slots(updated)

    if time_clarify_message:
        # 模糊时间表达需要优先追问，因此不能沿用上一轮日期，也不能继续带着旧日期往下查。
        updated["hbrq"] = None
        updated["hbrqBegin"] = None
        updated["hbrqEnd"] = None

    validation = validate_rate_slots(updated)
    updated = validation["normalized_slots"]
    validation_clarify_message = validation.get("clarify_message")
    validation_clarify_slot = validation.get("clarify_slot")
    missing = validation["missing_slots"]
    if time_clarify_message and "hbrq" not in missing:
        missing.append("hbrq")
    query_ready = len(missing) == 0

    logger.info(
        "node slot finished | elapsed=%.3fs | query_ready=%s | missing=%s | cleared_fields=%s | time_clarify=%s | extracted=%s | merged=%s",
        time.perf_counter() - started,
        query_ready,
        missing,
        sorted(cleared_fields),
        time_clarify_message,
        slots,
        updated,
    )
    _log_state_event(
        state,
        event="slot_extracted",
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        intent="rate_query",
        query_ready=query_ready,
        missing_slots=missing,
        cleared_fields=sorted(cleared_fields),
        sfg=updated.get("sfg"),
        mdg=updated.get("mdg"),
        input_weight=updated.get("inputWeight"),
        input_vol=updated.get("inputVol"),
        hbrq=updated.get("hbrq"),
        hbrq_begin=updated.get("hbrqBegin"),
        hbrq_end=updated.get("hbrqEnd"),
        package_type=updated.get("packageType"),
        cargo_type=updated.get("cargoType"),
        flight_type=updated.get("flightType"),
        pending_action_type="hbrq" if time_clarify_message else validation_clarify_slot,
        message_text=last_message,
    )

    return {
        **state,
        **updated,
        "missing_slots": missing,
        "query_ready": query_ready,
        "query_completed": False,
        "query_subtype": state.get("query_subtype") or "quote_update",
        "response_mode": None,
        "quantity_mode": None,
        "result_display_mode": result_display_mode,
        "time_clarify_message": time_clarify_message or validation_clarify_message,
        # 待澄清状态需要回传给前端并跨请求保留，
        # 这样用户下一轮只回复“这周六 / 下周六”时，intent_node 才能识别成补槽位回答。
        "pending_clarify_slot": "hbrq" if time_clarify_message else validation_clarify_slot,
        "pending_clarify_message": time_clarify_message or validation_clarify_message,
        "pending_clarify_context": None,
        "pending_action_type": "hbrq" if time_clarify_message else validation_clarify_slot,
        "pending_action_prompt": time_clarify_message or validation_clarify_message,
        "pending_action_payload": None,
        "pending_action_retry_count": 0,
        "pending_reuse_confirmation": False,
        "pending_reuse_message": None,
        "reuse_candidate_context": None,
        "reuse_confirmation_decision": None,
        # 一旦用户开始修改查询条件或补充参数，上一批报价结果不再作为活跃分析结果使用。
        "quote_result_active": False,
        "latest_quote_result": None,
        "result_analysis_intent": None,
        "result_analysis_filters": None,
        "result_reference_field": None,
        "result_reference_request": None,
        "support_info_kind": None,
    }


def ask_node(state: AgentState) -> AgentState:
    """缺参时一次性告诉用户当前还缺哪些必填字段。"""
    started = time.perf_counter()
    # 如果时间表达本身存在歧义，优先使用定向追问文案，而不是通用缺参提示。
    message = (
        state.get("pending_action_prompt")
        or
        state.get("pending_reuse_message")
        or state.get("time_clarify_message")
        or state.get("pending_clarify_message")
        or _build_missing_fields_message(state["missing_slots"])
    )

    logger.info(
        "node ask finished | elapsed=%.3fs | missing_fields=%s",
        time.perf_counter() - started,
        state["missing_slots"],
    )

    return {
        **state,
        "messages": state["messages"] + [AIMessage(content=message)],
    }


def tool_node(state: AgentState) -> AgentState:
    """调用运价接口，先精确查询，再按既定规则做类似日期查询。"""
    started = time.perf_counter()
    result = search_air_freight_rate.invoke(
        {
            "sfg": state["sfg"],
            "mdg": state["mdg"],
            "inputWeight": state["inputWeight"],
            "inputVol": state["inputVol"],
            "hbrq": state["hbrq"],
            "hbrqBegin": state.get("hbrqBegin"),
            "hbrqEnd": state.get("hbrqEnd"),
            "flightType": state.get("flightType"),
            "packageType": state.get("packageType"),
            "cargoType": state.get("cargoType"),
            "twoCode": state.get("twoCode"),
            "gid": state.get("gid"),
        }
    )

    if not result.get("success"):
        error = result.get("error", "UNKNOWN")
        msg = FALLBACK_RESPONSES["api_timeout"] if error == "TIMEOUT" else FALLBACK_RESPONSES["api_error"]

        logger.info(
            "node tool finished | elapsed=%.3fs | success=false | error=%s",
            time.perf_counter() - started,
            error,
        )
        _log_state_event(
            state,
            level=logging.ERROR,
            event="tool_failed",
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
            tool_name="search_air_freight_rate",
            tool_status="failed",
            error_stage="tool_node",
            error_type=error,
            error_message=msg,
            sfg=state.get("sfg"),
            mdg=state.get("mdg"),
            input_weight=state.get("inputWeight"),
            input_vol=state.get("inputVol"),
            package_type=state.get("packageType"),
            cargo_type=state.get("cargoType"),
        )

        return {
            **state,
            "api_result": None,
            "api_error": msg,
            "query_completed": False,
            "query_subtype": None,
            "response_mode": None,
            "quantity_mode": None,
            "time_clarify_message": None,
            "pending_clarify_slot": None,
            "pending_clarify_message": None,
            "pending_clarify_context": None,
            "pending_action_type": None,
            "pending_action_prompt": None,
            "pending_action_payload": None,
            "pending_action_retry_count": 0,
            "pending_reuse_confirmation": False,
            "pending_reuse_message": None,
            "reuse_candidate_context": None,
            "reuse_confirmation_decision": None,
            "quote_result_active": False,
            "latest_quote_result": None,
            "result_reference_field": None,
            "result_reference_request": None,
            "support_info_kind": None,
            "messages": state["messages"] + [AIMessage(content=msg)],
        }

    logger.info(
        "node tool finished | elapsed=%.3fs | success=true | search_mode=%s | exact_quotes=%s | similar_quotes=%s",
        time.perf_counter() - started,
        result.get("search_mode"),
        len(result.get("exact_quotes", [])),
        len(result.get("similar_quotes", [])),
    )
    # packageType 已经升级为必填，这里把接口结果再次按当前包装类型收口，
    # 避免后续展示链和结果分析链继续消费到混合包装结果。
    filtered_result = _apply_package_type_filter_to_result(result, state.get("packageType"))
    _log_state_event(
        state,
        event="tool_succeeded",
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        tool_name="search_air_freight_rate",
        tool_status="success",
        sfg=state.get("sfg"),
        mdg=state.get("mdg"),
        package_type=state.get("packageType"),
        cargo_type=state.get("cargoType"),
        # 报价摘要里已经包含 search_mode / quote_count_* 等字段，
        # 这里不要再显式传一次，避免 **kwargs 展开时出现重复关键字。
        **summarize_latest_quote_result(build_standard_quote_result(filtered_result) if filtered_result.get("quotes") else None),
    )

    return {
        **state,
        "api_result": filtered_result,
        "api_error": None,
        "query_completed": True,
        "query_subtype": None,
        "response_mode": None,
        "quantity_mode": None,
        "time_clarify_message": None,
        "pending_clarify_slot": None,
        "pending_clarify_message": None,
        "pending_clarify_context": None,
        "pending_action_type": None,
        "pending_action_prompt": None,
        "pending_action_payload": None,
        "pending_action_retry_count": 0,
        "pending_reuse_confirmation": False,
        "pending_reuse_message": None,
        "reuse_candidate_context": None,
        "reuse_confirmation_decision": None,
        # 保存最近一次完整报价结果的标准结构，供后续“最便宜 / 直达有哪些”等继续分析。
        "quote_result_active": bool(filtered_result.get("quotes")),
        "latest_quote_result": build_standard_quote_result(filtered_result) if filtered_result.get("quotes") else None,
        "result_analysis_intent": None,
        "result_analysis_filters": None,
        "result_reference_field": None,
        "result_reference_request": None,
        "support_info_kind": None,
    }


def result_node(state: AgentState) -> AgentState:
    """将精确结果、类似结果和无结果稳定输出为 Markdown 文本。"""
    started = time.perf_counter()
    api_result = state["api_result"] or {}
    search_mode = api_result.get("search_mode")

    if search_mode == "exact" and api_result.get("quotes"):
        message = _build_exact_result_message(state, api_result)
    elif search_mode == "similar" and api_result.get("similar_quotes"):
        message = _build_similar_result_message(state, api_result)
    else:
        message = _build_no_result_message()

    logger.info(
        "node result finished | elapsed=%.3fs | search_mode=%s",
        time.perf_counter() - started,
        search_mode,
    )
    _log_state_event(
        state,
        event="quote_result_generated",
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        search_mode=search_mode,
        response_mode="summary_only",
        **summarize_latest_quote_result(build_standard_quote_result(api_result) if api_result.get("quotes") else None),
    )

    return {
        **state,
        "messages": state["messages"] + [AIMessage(content=message)],
    }


def result_analysis_node(state: AgentState) -> AgentState:
    """对最近一次完整报价结果做排序、筛选、分组和摘要，不重新查价。"""
    started = time.perf_counter()
    latest_quote_result = state.get("latest_quote_result")

    if not state.get("quote_result_active") or not latest_quote_result:
        message = "抱歉，当前没有可继续分析的报价结果。请先完成一次运价查询。"
    else:
        message = render_result_analysis_message(
            latest_quote_result=latest_quote_result,
            analysis_intent=state.get("result_analysis_intent") or "summary",
            filters=state.get("result_analysis_filters") or {},
            response_mode=state.get("response_mode") or "summary_plus_table",
            quantity_mode=state.get("quantity_mode") or "multi",
        )

    logger.info(
        "node result_analysis finished | elapsed=%.3fs | analysis_intent=%s | quantity_mode=%s | response_mode=%s",
        time.perf_counter() - started,
        state.get("result_analysis_intent"),
        state.get("quantity_mode"),
        state.get("response_mode"),
    )
    _log_state_event(
        state,
        event="quote_result_analysis_generated",
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        analysis_intent=state.get("result_analysis_intent"),
        quantity_mode=state.get("quantity_mode"),
        response_mode=state.get("response_mode"),
    )

    return {
        **state,
        "messages": state["messages"] + [AIMessage(content=message)],
    }


def result_reference_node(state: AgentState) -> AgentState:
    """
    结果引用解释节点。

    这条链路专门处理“这是多少号的 / 这个是哪个航司 / 这个包装是什么”这类问题，
    目标是优先解释当前结果，而不是误触发重查。
    """
    started = time.perf_counter()
    latest_quote_result = state.get("latest_quote_result")
    if not state.get("quote_result_active") or not latest_quote_result:
        message = "抱歉，当前没有可继续解释的报价结果。请先完成一次运价查询。"
    else:
        message = render_result_reference_message(
            latest_quote_result=latest_quote_result,
            result_reference_request=state.get("result_reference_request")
            or {"field": state.get("result_reference_field") or "date", "selector": "current"},
            result_display_mode=state.get("result_display_mode"),
        )

    logger.info(
        "node result_reference finished | elapsed=%.3fs | field=%s",
        time.perf_counter() - started,
        state.get("result_reference_field"),
    )
    _log_state_event(
        state,
        event="quote_result_reference_generated",
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        result_reference_field=state.get("result_reference_field"),
        result_reference_request=state.get("result_reference_request"),
    )

    return {
        **state,
        "messages": state["messages"] + [AIMessage(content=message)],
    }


def support_info_node(state: AgentState) -> AgentState:
    """
    业务服务信息与能力说明节点。

    这类问题不属于结果分析，也不属于报价工具调用。
    第一版先给稳定、简洁的文本答复，不出表格。
    """
    started = time.perf_counter()
    support_info_kind = state.get("support_info_kind")
    last_message = state["messages"][-1].content.strip()

    if support_info_kind == "greeting":
        message = (
            "您好！我是唯凯国际AI 小凯，可以作为空运报价与业务支持助手。"
            "您可以让我帮您快速查价，也可以帮您看最便宜方案、筛选直飞/中转、指定航司，"
            "或者查询业务资料和单证要求。"
        )
    elif support_info_kind == "smalltalk":
        if "谢谢" in last_message:
            message = "不客气。您要继续查空运报价或业务资料，直接把条件发给我就行。"
        elif any(token in last_message for token in ["你是谁", "你叫什么"]):
            message = (
                "我是唯凯国际AI 小凯，可以协助您查询空运报价、筛选最便宜方案，"
                "也可以回答部分业务资料和单证要求问题。"
            )
        else:
            message = "我在。您可以直接发始发港、目的港、重量、体积、日期和包装类型，我来帮您查价。"
    elif support_info_kind == "all_origin_scope":
        message = (
            f"目前“全部港口”会按分公司固定口岸一起查询，包括：{ALL_ORIGIN_SCOPE_TEXT}。"
            "如果您要直接查价，也可以直接告诉我“全部港口 + 目的港 + 重量 + 体积 + 日期 + 包装类型”。"
        )
    elif support_info_kind == "business_meta":
        if "始发港" in last_message or not state.get("sfg"):
            message = build_origin_clarify_message()
        elif "还缺什么" in last_message or "缺什么参数" in last_message:
            message = _build_missing_fields_message(state.get("missing_slots") or ["sfg"])
        else:
            message = (
                "可以。我会先按您的条件确认清楚，再决定是否查询。"
                "如果您要继续这票货，请直接告诉我还需要修改或补充哪一项条件。"
            )
    elif support_info_kind == "service_info":
        message = (
            f"您可以联系我司人工客服或销售团队获取进一步支持，邮箱：{RESULT_CONTACT_EMAIL}。"
            "如果您要继续查运价，我也可以继续帮您处理。"
        )
    else:
        message = (
            "我目前主要可以帮您做这些事："
            "1. 查询空运运价；"
            "2. 基于已查到的结果筛选直达、中转、航司、包装等条件；"
            "3. 解释结果里的日期、航司、包装、合计和最便宜原因；"
            "4. 按需要展开完整报价明细。"
        )

    logger.info(
        "node support_info finished | elapsed=%.3fs | kind=%s",
        time.perf_counter() - started,
        support_info_kind,
    )
    _log_state_event(
        state,
        event="support_info_selected",
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        support_info_kind=support_info_kind,
        message_text=last_message,
    )

    return {
        **state,
        "messages": state["messages"] + [AIMessage(content=message)],
    }


def fallback_node(state: AgentState) -> AgentState:
    """统一兜底节点。"""
    started = time.perf_counter()
    intent = state.get("intent", "unknown")
    msg = FALLBACK_RESPONSES.get(intent, FALLBACK_RESPONSES["unknown"])

    logger.info(
        "node fallback finished | elapsed=%.3fs | intent=%s",
        time.perf_counter() - started,
        intent,
    )
    _log_state_event(
        state,
        event="fallback_selected",
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        intent=intent,
    )

    return {
        **state,
        "messages": state["messages"] + [AIMessage(content=msg)],
    }


def rag_retrieve_node(state: AgentState) -> AgentState:
    """RAG 检索节点。"""
    started = time.perf_counter()
    question = state["messages"][-1].content.strip()
    analysis = analyze_query(question)
    docs = hybrid_retrieve(query=analysis.get("query", question), filters=analysis.get("filters"))

    logger.info(
        "node rag_retrieve finished | elapsed=%.3fs | filters=%s | docs=%s",
        time.perf_counter() - started,
        analysis.get("filters"),
        len(docs),
    )
    _log_state_event(
        state,
        event="rag_retrieve_completed",
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        rag_query=question,
        retrieval_query=analysis.get("query", question),
        retrieval_filters=analysis.get("filters"),
        **summarize_retrieved_docs(docs),
    )

    return {
        **state,
        "rag_query": question,
        "retrieval_query": analysis.get("query", question),
        "retrieval_filters": analysis.get("filters"),
        "retrieved_docs": docs,
    }


def rag_answer_node(state: AgentState) -> AgentState:
    """RAG 生成节点。"""
    started = time.perf_counter()
    question = state.get("rag_query") or state["messages"][-1].content
    answer = generate_answer(question=question, retrieved_docs=state.get("retrieved_docs") or [])

    logger.info(
        "node rag_answer finished | elapsed=%.3fs | docs=%s",
        time.perf_counter() - started,
        len(state.get("retrieved_docs") or []),
    )
    _log_state_event(
        state,
        event="rag_answer_generated",
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        generator_docs=len(state.get("retrieved_docs") or []),
        rag_answer_length=len(answer or ""),
        rag_answer_summary=summarize_text(answer, max_length=200),
    )

    return {
        **state,
        "rag_answer": answer,
        "messages": state["messages"] + [AIMessage(content=answer)],
    }
