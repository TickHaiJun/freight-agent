import json
import logging
import re
import time

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import settings
from logging_schema import log_event
from rag.prompts import QUERY_ANALYZER_SYSTEM, QUERY_ANALYZER_USER


# 在 RAG（Retrieval-Augmented Generation）系统中，query_analyzer.py 通常位于查询处理层，介于用户原始输入与检索器之间。它的核心职责是对用户问题进行分析、改写和结构化，以提升后续检索的精准度和召回率。


# 用户问一句话进来后，系统先试着用规则判断，这个问题大概属于哪个业务域；如果能判断出来，
# 就直接把原问题清洗一下作为检索 query，同时加上类别 filter，
# 让后面的检索只在那个类别下找；如果规则看不准，再交给 LLM 去理解用户意图，
# 产出一个更适合检索的 query 和可能的 filters；如果连 LLM 都挂了，
# 那至少也别让系统报错，退回到一个最基础的“清洗后的原问题”。

# 模块级 logger，用于记录 query 分析耗时、走了哪条分支、提取到了什么 filters
logger = logging.getLogger(__name__)

# 罗马数字字符集，用于兼容类似 PI Ⅰ / Ⅱ / Ⅲ 这类问题里的特殊字符
ROMAN_NUMERALS = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ"


def _normalize_query(question: str) -> str:
    """
    对用户原始问题做轻量标准化，生成更适合检索的 query 文本。

    这里做的事情比较简单：
    1. 只保留英文、数字、中文、罗马数字；
    2. 去掉大部分标点符号；
    3. 把提取出来的 token 用空格拼接。

    这样做的目的不是“改写语义”，而是让检索 query 更干净，
    便于关键词匹配、向量检索或 hybrid retrieval 使用。

    示例：
    原始问题: "PI967 Section II 的包装说明是什么？"
    归一化后: "PI967 Section II 的包装说明是什么"
    """
    roman_pattern = re.escape(ROMAN_NUMERALS)

    # 提取 token：
    # [A-Za-z0-9]+      -> 英文和数字
    # [{roman_pattern}]+ -> 罗马数字
    # [\u4e00-\u9fff]+  -> 中文
    tokens = re.findall(
        rf"[A-Za-z0-9]+|[{roman_pattern}]+|[\u4e00-\u9fff]+",
        question
    )

    # 如果提取到了 token，就用空格拼起来，形成更规整的 query；
    # 否则退化为原问题去掉首尾空格。
    return " ".join(tokens) if tokens else question.strip()


def _rule_based_analysis(question: str) -> dict | None:
    """
    先走规则判断，识别用户问题属于哪个知识类别，并尽量生成 metadata filters。

    设计意图：
    - 小知识库、领域术语比较稳定时，规则往往比 LLM 更稳；
    - 如果规则已经能明确判断分类，就直接返回，不再调用 LLM；
    - 只有规则覆盖不到时，才让 LLM 做兜底分析。

    返回格式示例：
    {
        "query": "锂电池 PI967 包装说明",
        "filters": {"category": "dangerous_goods"}
    }

    如果规则无法命中，则返回 None，交给后续 LLM 处理。
    """
    q = question.lower()

    # 小知识库先规则优先，尽量把 metadata filter 用起来；
    # 只有规则无法稳定判断时，才让 LLM 补充。
    if any(token in q for token in ["锂电池", "危险品", "pi967", "pi968", "包装说明"]):
        return {
            "query": _normalize_query(question),
            "filters": {"category": "dangerous_goods"}
        }

    if any(token in q for token in ["accos", "分单", "件数", "录入"]):
        return {
            "query": _normalize_query(question),
            "filters": {"category": "operations"}
        }

    # 这里专门排除了“危险品”“锂电池”，避免“普货”相关词误判到 general_cargo
    if any(token in q for token in ["普货", "不带电", "委托书"]) and "危险品" not in q and "锂电池" not in q:
        return {
            "query": _normalize_query(question),
            "filters": {"category": "general_cargo"}
        }

    if any(token in q for token in ["报关", "品名清单", "上海口岸", "清关"]):
        return {
            "query": _normalize_query(question),
            "filters": {"category": "customs"}
        }

    return None


def _call_llm(question: str) -> dict:
    """
    调用 LLM 分析用户问题，返回结构化结果。

    LLM 的职责大概率是：
    1. 生成更适合检索的 query；
    2. 尝试抽取 filters；
    3. 用统一 JSON 格式返回。

    这里 temperature=0，说明作者希望输出尽可能稳定、可复现，
    不希望 query 分析每次都飘。
    """
    started = time.perf_counter()

    llm = ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0,
    )

    # 给 LLM 两段消息：
    # - SystemMessage: 约束它扮演“query analyzer”
    # - HumanMessage: 传入当前用户问题
    response = llm.invoke([
        SystemMessage(content=QUERY_ANALYZER_SYSTEM),
        HumanMessage(content=QUERY_ANALYZER_USER.format(question=question)),
    ])

    logger.info(
        "rag query_analyzer llm finished | elapsed=%.3fs",
        time.perf_counter() - started
    )
    log_event(
        logger,
        event="rag_query_analyzer_llm_finished",
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
    )

    content = response.content.strip()

    try:
        # 理想情况：LLM 直接返回标准 JSON
        return json.loads(content)
    except json.JSONDecodeError:
        # 轻容错：
        # 有些模型会输出
        # “这是结果：{...}”
        # 或者前后包一层解释文本，这里尝试只截取最外层 JSON。
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
        raise


def analyze_query(question: str) -> dict:
    """
    对外暴露的统一入口。

    处理流程：
    1. 空字符串直接返回；
    2. 优先走规则分析；
    3. 规则命不中时，调用 LLM；
    4. 如果 LLM 异常，则退化为仅做 query 归一化；
    5. 最终统一返回：
       {
           "query": "...",
           "filters": {...} 或 None
       }

    这是一个非常典型的“规则优先 + LLM 兜底 + 失败可降级”的工程写法。
    """
    started = time.perf_counter()

    # 空问题直接返回，避免后面无意义处理
    if not question.strip():
        return {"query": "", "filters": None}

    # 第一层：规则优先
    rule_result = _rule_based_analysis(question)
    if rule_result is not None:
        logger.info(
            "rag query_analyzer finished | elapsed=%.3fs | mode=rule | filters=%s",
            time.perf_counter() - started,
            rule_result.get("filters"),
        )
        log_event(
            logger,
            event="rag_query_analyzed",
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
            retrieval_mode="rule",
            retrieval_filters=rule_result.get("filters"),
            retrieval_query=rule_result.get("query"),
        )
        return rule_result

    # 第二层：规则命不中，才走 LLM
    try:
        llm_result = _call_llm(question)
    except Exception:
        # LLM 调用失败时，不让整个 RAG 挂掉，降级为空结果
        llm_result = {}

    # 统一兜底：
    # - query 没取到时，就用归一化后的原问题
    # - filters 没取到时，设为 None

    # 输出的结果只有两样：一个 query，一个 filters。query 是给检索器用的文本查询，filters 是给 metadata filter 用的结构化约束。
    result = {
        "query": llm_result.get("query") or _normalize_query(question),
        "filters": llm_result.get("filters") or None,
    }

    logger.info(
        "rag query_analyzer finished | elapsed=%.3fs | mode=llm_fallback | filters=%s",
        time.perf_counter() - started,
        result.get("filters"),
    )
    log_event(
        logger,
        event="rag_query_analyzed",
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        retrieval_mode="llm_fallback",
        retrieval_filters=result.get("filters"),
        retrieval_query=result.get("query"),
    )

    return result
