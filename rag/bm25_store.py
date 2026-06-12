import pickle
import re
from pathlib import Path
import logging

# 当前模块的日志对象。
# 后续构建索引、加载缓存、执行查询时，都会通过它打日志，方便排查问题。
logger = logging.getLogger(__name__)


def _cache_path() -> Path:
    """
    返回 BM25 缓存文件路径。

    这里统一收敛到 data/cache/bm25.pkl，
    目的是让“构建索引”和“加载索引”都走同一个固定位置，
    避免路径散落在业务代码里不好维护。
    """
    return Path("data/cache/bm25.pkl")


def _tokenize(text: str) -> list[str]:
    """
    对输入文本做一个非常轻量的分词。

    当前策略：
    1. 英文和数字按连续串切分，例如:
       "user_id 401 api" -> ["user", "id", "401", "api"] 中的连续匹配部分
       但注意这里的正则其实不会保留下划线，所以 "user_id" 会被拆成 "user" 和 "id"
    2. 中文按单字切分，例如:
       "请假制度" -> ["请", "假", "制", "度"]

    为什么这么做：
    - 第一版主要目标不是追求最优分词效果，而是先保证 BM25 这条链路能稳定跑起来。
    - 对英文、数字、错误码、短关键词，轻分词往往已经能起到兜底召回作用。
    - 中文按单字切虽然比较粗，但比完全不切要强，便于先做验证。

    风险和边界：
    - 中文按单字切，语义会比较碎，检索质量一般。
    - "user_id"、"/api/order/create" 这类带符号的术语，会被切坏。
    - 真正上线时，通常要替换成更合适的 tokenizer，或者做术语保护。

    如果正则没有匹配出任何内容，就退化成逐字符切分，
    保证返回值一定是 list[str]，不至于出现空结果导致后续异常。
    """
    parts = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text.lower())
    return parts or list(text.lower())


def _match_filters(metadata: dict, filters: dict | None) -> bool:
    """
    判断单条 metadata 是否满足过滤条件。

    参数：
    - metadata: 当前 chunk 对应的元数据
    - filters: 查询时传入的过滤条件，例如 {"kb_id": "hr", "doc_id": "doc_001"}

    逻辑：
    - 如果没有传 filters，默认认为全部命中
    - 如果传了 filters，则要求 metadata 中对应字段必须完全相等

    当前实现特点：
    - 只支持“等值匹配”
    - 不支持 in / range / contains / 多条件组合逻辑
    - 但好处是非常直接，排查起来简单

    这和你第一版 RAG 系统的思路是一致的：
    先要可控、可解释，再谈功能扩展。
    """
    if not filters:
        return True

    for key, value in filters.items():
        if metadata.get(key) != value:
            return False

    return True


def build_bm25_index(documents: list) -> dict:
    """
    基于传入的 LangChain Document 列表，构建 BM25 索引，并把基础数据落盘。

    参数：
    - documents: 一般是经过 load -> clean -> split 之后的 chunk 列表
      每个元素通常是 langchain_core.documents.Document

    这里做了几件事：
    1. 提取每个 chunk 的正文 page_content，作为 corpus
    2. 提取每个 chunk 的 metadata，作为 metadatas
    3. 对每段正文执行 _tokenize，得到 tokens
    4. 把 tokens / corpus / metadatas 落盘到 bm25.pkl
    5. 在内存里临时构建一个 BM25Okapi 对象并返回

    为什么落盘时不直接 dump BM25Okapi 对象，而是 dump 原始 payload？
    - 这样更稳，兼容性通常更好
    - 后续即便 BM25 实现细节变了，只要 tokens 还在，就可以重新构建
    - 对排查也更友好，因为磁盘里保存的是你能看懂的数据

    返回值：
    - count: 当前索引中的 chunk 数量
    - bm25: 内存中的 BM25Okapi 对象；如果 documents 为空，则返回 None
    """
    from rank_bm25 import BM25Okapi

    # 确保缓存目录存在，例如 data/cache/
    _cache_path().parent.mkdir(parents=True, exist_ok=True)

    # corpus: BM25 真正参与检索的原始文本列表
    corpus = [doc.page_content for doc in documents]

    # metadatas: 与 corpus 一一对应的元数据，用于后续过滤和回溯
    metadatas = [doc.metadata for doc in documents]

    # tokens: corpus 分词后的结果，BM25 的打分是基于这些 token 的
    tokens = [_tokenize(text) for text in corpus]

    # payload 是实际落盘的数据
    payload = {
        "tokens": tokens,
        "corpus": corpus,
        "metadatas": metadatas,
    }

    # 写入本地缓存文件，后续查询可直接重建 BM25
    with _cache_path().open("wb") as file:
        pickle.dump(payload, file)

    # 如果没有任何 token，说明索引为空，不再构建 BM25 对象
    if not tokens:
        return {"count": 0, "bm25": None}

    # 返回内存态 BM25 对象，供当前流程继续使用
    return {"count": len(corpus), "bm25": BM25Okapi(tokens)}


def _load_bm25_index():
    """
    加载 BM25 索引缓存。

    加载策略：
    1. 如果缓存文件存在：
       - 从 bm25.pkl 中读取 payload
       - 再根据 payload["tokens"] 重新构建 BM25Okapi 对象
    2. 如果缓存文件不存在：
       - 打 warning 日志
       - 自动从原始文档目录重新构建索引
       - 再生成 BM25Okapi 对象

    这里体现的是“查询侧自恢复”思路：
    - 不要求调用方先显式执行 index
    - 没缓存时，search 也能尽量工作
    - 但代价是第一次查可能会比较慢

    返回值 payload 中最终会包含：
    - tokens
    - corpus
    - metadatas
    - bm25
    """
    from rank_bm25 import BM25Okapi

    path = _cache_path()

    if not path.exists():
        logger.warning(
            "rag bm25 cache missing | action=rebuild_from_docs | path=%s",
            path
        )

        payload = _build_bm25_index_from_docs()
        payload["bm25"] = BM25Okapi(payload["tokens"])
        return payload

    with path.open("rb") as file:
        payload = pickle.load(file)

    # 从落盘的 tokens 重建 BM25Okapi 对象
    payload["bm25"] = BM25Okapi(payload["tokens"]) if payload["tokens"] else None
    return payload


def _build_bm25_index_from_docs() -> dict:
    """
    当本地 bm25 缓存缺失时，从原始文档目录重新构建 BM25 索引。

    依赖的链路：
    - settings.rag_docs_dir: 原始文档目录
    - validate_metadata: 校验 metadata 配置是否合法
    - load_document: 加载文件内容
    - clean_documents: 清洗文本
    - split_documents: 切 chunk，变成检索单元

    整体流程：
    1. 校验文档目录的 metadata 配置
    2. 遍历 rag_docs_dir 目录下的所有文件
    3. 对每个文件执行：
       - 读取元数据
       - 加载原始文档
       - 文本清洗
       - 切 chunk
    4. 汇总成统一的 documents 列表
    5. 调用 build_bm25_index 落盘
    6. 再从缓存文件读取 payload 返回

    为什么最后不直接 return build_bm25_index(documents)？
    - 因为 build_bm25_index 返回的是 {"count": ..., "bm25": ...}
      不是完整 payload
    - 而这里后续查询需要的是 tokens/corpus/metadatas 这些真正的数据
    - 所以这里选择“写完再读回来”，虽然略绕，但能拿到统一结构

    skipped_files:
    - 某些文件加载失败、清洗失败、metadata 不合法时，不会中断整批构建
    - 只会记录 warning，并继续处理其他文件
    - 这是很典型的批处理容错思路
    """
    from config import settings
    from rag.cleaner import clean_documents
    from rag.loaders import load_document
    from rag.metadata import get_metadata, validate_metadata
    from rag.splitter import split_documents

    validate_metadata(settings.rag_docs_dir)

    documents = []
    skipped_files = []

    for path in sorted(Path(settings.rag_docs_dir).glob("*")):
        if not path.is_file():
            continue

        try:
            metadata = get_metadata(path.name)
            raw_docs = load_document(str(path))
            cleaned_docs = clean_documents(raw_docs)
            documents.extend(split_documents(cleaned_docs, base_metadata=metadata))
        except Exception as exc:
            skipped_files.append(path.name)
            logger.warning(
                "rag bm25 skip source file | file=%s | reason=%s",
                path.name,
                exc
            )

    logger.info(
        "rag bm25 rebuild_from_docs finished | docs=%s | skipped_files=%s",
        len(documents),
        skipped_files,
    )

    # 先调用统一的索引构建逻辑，把 payload 落到本地
    build_bm25_index(documents)

    # 再从缓存中读取完整 payload 返回
    with _cache_path().open("rb") as file:
        return pickle.load(file)


def search_bm25(query: str, k: int, filters: dict | None = None) -> list:
    """
    执行 BM25 检索。

    参数：
    - query: 用户查询文本
    - k: 返回前 k 条结果
    - filters: metadata 过滤条件，例如 {"kb_id": "finance"}

    流程：
    1. 加载 BM25 索引（必要时自动重建）
    2. 若索引为空，直接返回 []
    3. 对 query 做 _tokenize
    4. 调用 BM25Okapi.get_scores 对所有 chunk 打分
    5. 再按 metadata 做过滤
    6. 按 score 倒序排序
    7. 返回 top k 结果

    返回结果格式：
    [
        {
            "document": Document(page_content=..., metadata=...),
            "score": 12.34
        },
        ...
    ]

    这里有一个很重要的实现特点：
    - 当前是“先全量打分，再过滤”
    - 不是“先过滤，再打分”

    好处：
    - 实现简单
    - 逻辑直观
    - 便于排障和验证

    代价：
    - 数据量大时性能一般
    - 因为所有 chunk 都会先参与打分

    对你现在这个阶段，这个取舍是合理的。
    """
    from langchain_core.documents import Document

    logger.info(
        "rag bm25 search start | k=%s | filters=%s | query=%s",
        k,
        filters,
        query
    )

    payload = _load_bm25_index()

    if payload["bm25"] is None:
        logger.warning(
            "rag bm25 search skipped | reason=empty_index | query=%s | filters=%s",
            query,
            filters
        )
        return []

    # 对查询词分词，然后让 BM25 对全量 chunk 打分
    scores = payload["bm25"].get_scores(_tokenize(query))

    # 第一版实现：先全量打分，再按 metadata 过滤
    candidates = []

    for idx, score in enumerate(scores):
        metadata = payload["metadatas"][idx]

        if not _match_filters(metadata, filters):
            continue

        candidates.append({
            "document": Document(
                page_content=payload["corpus"][idx],
                metadata=metadata
            ),
            "score": float(score),
        })

    # 按 BM25 分数从高到低排序
    candidates.sort(key=lambda item: item["score"], reverse=True)

    # 只保留 top k
    results = candidates[:k]

    logger.info(
        "rag bm25 search finished | k=%s | filters=%s | hits=%s",
        k,
        filters,
        len(results)
    )

    return results