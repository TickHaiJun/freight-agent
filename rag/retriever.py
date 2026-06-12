import logging
import time

from config import settings
from logging_schema import log_event
from rag.bm25_store import search_bm25
from rag.reranker import rerank
from rag.vector_store import similarity_search

logger = logging.getLogger(__name__)


# 它负责把两路召回合成一个候选集。这里的设计意图很明确：同一个 chunk 只保留一份，但保留它在两路检索里的得分信息。
# 这个思路是对的，因为 hybrid retrieval 的重点不是“简单拼接两个列表”，而是“在统一候选集上做融合判断”。
def _dedupe_and_merge(vector_results: list[dict], bm25_results: list[dict]) -> list[dict]:
    """
    合并向量检索和 BM25 检索的结果，并按文档 chunk 去重。

    输入：
        vector_results: similarity_search 返回的结果列表，
                        每一项通常形如 {"document": doc, "score": xxx}
        bm25_results:   search_bm25 返回的结果列表，
                        每一项通常形如 {"document": doc, "score": xxx}

    输出：
        一个统一结构的结果列表：
        [
            {
                "page_content": "...",
                "metadata": {...},
                "score": xxx,   # 当前是一个简单融合后的分数
            }
        ]

    说明：
        这里用 (source_file, chunk_index) 作为同一个 chunk 的唯一键。
        也就是说，如果向量检索和 BM25 都命中了同一个 chunk，就合并成一条。
    """
    merged: dict[tuple, dict] = {}

    # 先放入向量检索结果
    for item in vector_results:
        doc = item["document"]

        # 用 source_file + chunk_index 标识一个 chunk
        # 假设同一个文件中的同一个 chunk_index 是唯一的
        key = (doc.metadata.get("source_file"), doc.metadata.get("chunk_index"))

        merged[key] = {
            "document": doc,
            "vector_score": float(item.get("score", 0.0)),
            "bm25_score": 0.0,
        }

    # 再处理 BM25 结果
    for item in bm25_results:
        doc = item["document"]
        key = (doc.metadata.get("source_file"), doc.metadata.get("chunk_index"))

        if key not in merged:
            # 如果这个 chunk 之前没有被向量检索命中，就新建一条
            merged[key] = {
                "document": doc,
                "vector_score": 0.0,
                "bm25_score": float(item.get("score", 0.0)),
            }
        else:
            # 如果这个 chunk 已经存在，说明两路召回都命中了同一个 chunk
            # 这里只补上 BM25 分数
            merged[key]["bm25_score"] = float(item.get("score", 0.0))

    def rank_value(item: dict) -> float:
        """
        计算一个简单的融合排序分数。

        当前假设：
        - Chroma / 向量检索返回的是“距离”，越小越相似
        - BM25 返回的是“相关度”，越大越相关

        所以这里直接用：
            bm25_score - vector_score

        这个写法的直觉是：
        - BM25 越高越加分
        - 向量距离越大越扣分

        注意：
        这只是一个“非常轻量”的启发式融合方式，
        因为两个分数通常不在同一个量纲上，严格来说应该做归一化后再融合。
        """
        return item["bm25_score"] - item["vector_score"]

    # 按融合分数从高到低排序
    ranked = sorted(merged.values(), key=rank_value, reverse=True)

    # 输出统一结构，并截断到最终 top_k
    return [
        {
            "page_content": item["document"].page_content,
            "metadata": item["document"].metadata,
            "score": rank_value(item),
        }
        for item in ranked[:settings.rag_top_k_final]
    ]

# 它是总控入口，负责把向量检索、BM25 检索、fallback、rerank 串起来。这里你做得比较好的地方，
# 是你没有把“某一路失败”当成整体失败。向量库挂了，BM25 还能兜底；BM25 出问题，向量库还能继续工作。
# 这在生产环境里很重要，因为 retriever 这一层最怕“全有或全无”。你现在这个写法是偏鲁棒的。
def hybrid_retrieve(query: str, filters: dict | None = None) -> list[dict]:
    """
    执行一轮混合检索（Hybrid Retrieval）。

    处理流程：
    1. 记录开始时间并打日志
    2. 先做向量检索（如果配置允许）
    3. 再做 BM25 检索
    4. 如果两路都没结果，而且传入了 filters，则退回无 filters 再重试一次
       这是为了避免 metadata filter 判错导致“明明有内容却查不到”
    5. 对两路结果去重、合并、粗排
    6. 如果开启 rerank，则交给 reranker 做精排
    7. 记录耗时和命中情况，返回最终结果
    """
    started = time.perf_counter()
    logger.info("rag hybrid_retrieve start | filters=%s | query=%s", filters, query)
    log_event(
        logger,
        event="rag_retrieve_started",
        retrieval_filters=filters,
        retrieval_query=query,
    )

    vector_results = []

    # 1) 向量检索：适合召回语义相近但字面不一致的内容
    if settings.rag_enable_vector_search:
        try:
            vector_results = similarity_search(
                query,
                settings.rag_top_k_vector,
                filters=filters,
            )
        except Exception:
            # 向量检索失败时，记录异常，但不要让整个检索流程崩掉
            logger.exception(
                "rag hybrid_retrieve vector search failed | filters=%s | query=%s",
                filters,
                query,
            )
            vector_results = []
    else:
        logger.warning(
            "rag hybrid_retrieve skip vector search | reason=config_disabled | filters=%s | query=%s",
            filters,
            query,
        )
        log_event(
            logger,
            level=logging.WARNING,
            event="rag_vector_skipped",
            retrieval_filters=filters,
            retrieval_query=query,
            reason="config_disabled",
        )

    # 2) BM25 检索：适合命中关键词、术语、错误码、专有名词
    try:
        bm25_results = search_bm25(query, settings.rag_top_k_bm25, filters=filters)
    except Exception:
        logger.exception(
            "rag hybrid_retrieve bm25 search failed | filters=%s | query=%s",
            filters,
            query,
        )
        bm25_results = []

    # 3) 如果两路都查不到，并且这次用了 filters，则退回无 filter 再查一次
    #    这么做的目的是提高鲁棒性：
    #    有时 metadata 抽取错了，或者 filter 条件太严，会导致误杀所有候选。
    if not vector_results and not bm25_results and filters:
        logger.info("rag hybrid_retrieve retry without filters | original_filters=%s", filters)
        log_event(
            logger,
            event="rag_retrieve_retry_without_filters",
            retrieval_filters=filters,
            retrieval_query=query,
        )

        if settings.rag_enable_vector_search:
            try:
                vector_results = similarity_search(
                    query,
                    settings.rag_top_k_vector,
                    filters=None,
                )
            except Exception:
                logger.exception("rag hybrid_retrieve vector retry failed | query=%s", query)
                vector_results = []

        try:
            bm25_results = search_bm25(query, settings.rag_top_k_bm25, filters=None)
        except Exception:
            logger.exception("rag hybrid_retrieve bm25 retry failed | query=%s", query)
            bm25_results = []

    # 4) 合并两路召回结果，并做一次简单粗排
    docs = _dedupe_and_merge(vector_results, bm25_results)

    # 5) 如果开启 rerank，则让 reranker 结合 query 再做一次精排
    #    一般这一步比简单分数融合更可靠，但会多一次模型调用或额外计算成本
    if settings.rag_enable_rerank:
        docs = rerank(query, docs)

    # 6) 记录整个检索流程耗时和命中数
    logger.info(
        "rag hybrid_retrieve finished | elapsed=%.3fs | filters=%s | vector_hits=%s | bm25_hits=%s | final_docs=%s",
        time.perf_counter() - started,
        filters,
        len(vector_results),
        len(bm25_results),
        len(docs),
    )
    log_event(
        logger,
        event="rag_retrieve_finished",
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        retrieval_filters=filters,
        retrieval_query=query,
        vector_hits=len(vector_results),
        bm25_hits=len(bm25_results),
        final_docs=len(docs),
    )

    return docs
