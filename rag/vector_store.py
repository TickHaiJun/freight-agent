from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import logging
from threading import Lock
import time

from config import settings
from rag.embeddings import DashScopeEmbeddings

logger = logging.getLogger(__name__)
_VECTOR_STORE = None
_VECTOR_STORE_LOCK = Lock()
_VECTOR_SEARCH_DISABLED = False


def get_vector_store():
    from langchain_chroma import Chroma

    global _VECTOR_STORE
    if _VECTOR_STORE is not None:
        return _VECTOR_STORE

    with _VECTOR_STORE_LOCK:
        if _VECTOR_STORE is not None:
            return _VECTOR_STORE

        started = time.perf_counter()
        logger.info(
            "rag vector store init start | persist_directory=%s | collection=%s",
            settings.chroma_persist_dir,
            settings.chroma_collection_name,
        )
        # 持久化目录在配置层统一定义，避免不同环境把索引写到未知位置。
        Path(settings.chroma_persist_dir).mkdir(parents=True, exist_ok=True)
        logger.info(
            "rag vector store directory ready | elapsed=%.3fs | persist_directory=%s",
            time.perf_counter() - started,
            settings.chroma_persist_dir,
        )
        chroma_started = time.perf_counter()
        _VECTOR_STORE = Chroma(
            collection_name=settings.chroma_collection_name,
            embedding_function=DashScopeEmbeddings(),
            persist_directory=settings.chroma_persist_dir,
        )
        logger.info(
            "rag vector store init finished | total_elapsed=%.3fs | chroma_elapsed=%.3fs | collection=%s",
            time.perf_counter() - started,
            time.perf_counter() - chroma_started,
            settings.chroma_collection_name,
        )
    return _VECTOR_STORE


def _query_similarity_search(store, query: str, kwargs: dict):
    return store.similarity_search_with_score(query, **kwargs)


def _query_with_timeout(store, query: str, kwargs: dict, timeout_seconds: float):
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_query_similarity_search, store, query, kwargs)
    try:
        return future.result(timeout=timeout_seconds)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def add_documents(documents: list) -> None:
    if not documents:
        return
    store = get_vector_store()
    # 用 source_file + chunk_index 作为稳定主键，方便后续“先删后加”。
    ids = [
        f"{doc.metadata.get('source_file')}::{doc.metadata.get('chunk_index')}"
        for doc in documents
    ]
    store.add_documents(documents=documents, ids=ids)


def delete_by_source_file(source_file: str) -> None:
    store = get_vector_store()
    store.delete(where={"source_file": source_file})


def reset_collection() -> None:
    global _VECTOR_STORE
    store = get_vector_store()
    store.reset_collection()
    _VECTOR_STORE = None


def similarity_search(query: str, k: int, filters: dict | None = None) -> list:
    global _VECTOR_SEARCH_DISABLED
    started = time.perf_counter()
    if _VECTOR_SEARCH_DISABLED:
        logger.warning(
            "rag vector similarity_search skipped | reason=disabled_after_previous_failure | filters=%s | query=%s",
            filters,
            query,
        )
        return []
    store = get_vector_store()
    query_mode = "filtered" if filters else "unfiltered"
    logger.info(
        "rag vector similarity_search start | mode=%s | k=%s | filters=%s | query=%s",
        query_mode,
        k,
        filters,
        query,
    )
    kwargs = {"k": k}
    if filters:
        kwargs["filter"] = filters
    # 返回时统一包成 document + score 结构，方便后面和 BM25 结果合并。
    chroma_started = time.perf_counter()
    try:
        results = _query_with_timeout(
            store=store,
            query=query,
            kwargs=kwargs,
            timeout_seconds=settings.rag_vector_search_timeout_seconds,
        )
    except FutureTimeoutError:
        _VECTOR_SEARCH_DISABLED = True
        logger.error(
            "rag vector similarity_search timeout | mode=%s | elapsed=%.3fs | timeout=%.3fs | filters=%s | query=%s | action=disable_vector_search",
            query_mode,
            time.perf_counter() - chroma_started,
            settings.rag_vector_search_timeout_seconds,
            filters,
            query,
        )
        return []
    except Exception:
        _VECTOR_SEARCH_DISABLED = True
        logger.exception(
            "rag vector similarity_search failed | mode=%s | elapsed=%.3fs | filters=%s | query=%s | action=disable_vector_search",
            query_mode,
            time.perf_counter() - chroma_started,
            filters,
            query,
        )
        return []
    logger.info(
        "rag vector chroma returned | mode=%s | elapsed=%.3fs | hits=%s",
        query_mode,
        time.perf_counter() - chroma_started,
        len(results),
    )
    logger.info(
        "rag vector similarity_search finished | mode=%s | elapsed=%.3fs | k=%s | filters=%s | hits=%s",
        query_mode,
        time.perf_counter() - started,
        k,
        filters,
        len(results),
    )
    return [{"document": doc, "score": score} for doc, score in results]
