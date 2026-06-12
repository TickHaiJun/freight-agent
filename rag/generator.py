import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import settings
from logging_schema import log_event, summarize_text
from rag.prompts import RAG_ANSWER_SYSTEM, RAG_ANSWER_USER

logger = logging.getLogger(__name__)


def _format_docs(retrieved_docs: list[dict]) -> str:
    """把检索结果转成可直接给模型消费的上下文文本。"""
    sections = []
    for index, doc in enumerate(retrieved_docs, start=1):
        metadata = doc.get("metadata", {})
        source = metadata.get("source_file", "未知文件")
        position = metadata.get("page") or metadata.get("slide") or metadata.get("chunk_index")
        sections.append(f"[资料{index}] 来源={source} 位置={position}\n{doc.get('page_content', '')}")
    return "\n\n".join(sections)


def generate_answer(question: str, retrieved_docs: list[dict]) -> str:
    """根据用户问题和检索到的资料生成最终回答。"""
    started = time.perf_counter()

    if not retrieved_docs:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info("rag generator finished | elapsed=%.3fs | docs=0 | short_circuit=true", elapsed_ms / 1000)
        log_event(
            logger,
            event="rag_generator_finished",
            elapsed_ms=elapsed_ms,
            generator_docs=0,
            short_circuit=True,
        )
        return "当前资料中未检索到明确依据，建议联系业务同事进一步确认。"

    llm = ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=0.2,
    )
    response = llm.invoke(
        [
            SystemMessage(content=RAG_ANSWER_SYSTEM),
            HumanMessage(
                content=RAG_ANSWER_USER.format(
                    question=question,
                    context=_format_docs(retrieved_docs),
                )
            ),
        ]
    )

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "rag generator finished | elapsed=%.3fs | docs=%s",
        elapsed_ms / 1000,
        len(retrieved_docs),
    )
    log_event(
        logger,
        event="rag_generator_finished",
        elapsed_ms=elapsed_ms,
        generator_docs=len(retrieved_docs),
        rag_answer_length=len(response.content or ""),
        rag_answer_summary=summarize_text(response.content, max_length=200),
    )
    return response.content
