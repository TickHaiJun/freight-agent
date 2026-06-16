import importlib
import logging
import time

from config import settings

# 当前模块的日志对象，用来记录 embedding 调用过程中的关键日志
logger = logging.getLogger(__name__)


def _get_dashscope_module():
    """
    Lazily import and configure the native DashScope SDK.

    We intentionally avoid the OpenAI compatible mode here, because
    `qwen3-vl-embedding` is not supported by DashScope's compatible
    `/embeddings` route. The native SDK path is the long-term stable
    solution for the project's chosen embedding model.
    """
    if not settings.dashscope_api_key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY，无法调用 embedding 接口。")

    try:
        dashscope = importlib.import_module("dashscope")
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 dashscope 依赖，无法调用百炼原生 embedding 接口。") from exc

    dashscope.api_key = settings.dashscope_api_key
    return dashscope


def _is_multimodal_embedding_model(model_name: str) -> bool:
    """
    Route VL / vision-style models to the multimodal embedding API.

    The current project target is `qwen3-vl-embedding`, but keeping this
    check model-driven avoids hard-coding exactly one model name and makes
    later model switching safer.
    """
    lowered = model_name.lower()
    return "vl-embedding" in lowered or "vision" in lowered


def _response_to_dict(response) -> dict:
    """Normalize SDK responses to a plain dict for robust parsing and logging."""
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if hasattr(response, "output"):
        return {
            "status_code": getattr(response, "status_code", None),
            "code": getattr(response, "code", None),
            "message": getattr(response, "message", None),
            "output": getattr(response, "output", None),
        }
    raise RuntimeError(f"无法解析 DashScope embedding 响应: {type(response)!r}")


def _extract_vectors(response_dict: dict) -> list[list[float]]:
    """
    Extract embedding vectors from the normalized DashScope response.

    Native DashScope embedding responses are expected to provide vectors
    under `output.embeddings[*].embedding`.
    """
    output = response_dict.get("output") or {}
    embeddings = output.get("embeddings") or []

    vectors = []
    for item in embeddings:
        if not isinstance(item, dict):
            continue
        vector = item.get("embedding")
        if vector:
            vectors.append(vector)

    if not vectors:
        raise RuntimeError(f"embedding 返回为空: {response_dict}")

    return vectors


def _call_native_embedding_api(texts: list[str]):
    """
    Dispatch embedding requests to the correct DashScope native API.

    - `qwen3-vl-embedding` / vision-style models use `MultiModalEmbedding`
    - text embedding models use `TextEmbedding`
    """
    dashscope = _get_dashscope_module()

    if _is_multimodal_embedding_model(settings.embedding_model):
        # Official native usage for qwen3-vl-embedding accepts a list of
        # multimodal content items. Our current RAG chunks are text-only, so
        # each chunk is wrapped into {"text": "..."} while keeping the route
        # compatible with future image/mixed inputs.
        request_input = [{"text": text} for text in texts]
        return dashscope.MultiModalEmbedding.call(
            model=settings.embedding_model,
            input=request_input,
        )

    return dashscope.TextEmbedding.call(
        model=settings.embedding_model,
        input=texts,
    )


def _embed(texts: list[str]) -> list[list[float]]:
    """
    embedding 的底层通用函数。

    输入：
        texts: 一个字符串列表，每个字符串代表一段需要向量化的文本

    输出：
        一个二维列表：
        [
            [0.12, -0.03, ...],   # 第 1 段文本的向量
            [0.08,  0.44, ...],   # 第 2 段文本的向量
            ...
        ]

    说明：
        这是统一的底层实现，既可以给“离线文档向量化”用，
        也可以给“在线 query 向量化”用。
    """
    started = time.perf_counter()

    # 如果输入为空，直接返回空列表，不发请求
    if not texts:
        logger.info(
            "rag embeddings skipped | elapsed=%.3fs | texts=0",
            time.perf_counter() - started
        )
        return []

    request_mode = "multimodal" if _is_multimodal_embedding_model(settings.embedding_model) else "text"

    logger.info(
        "rag embeddings request start | texts=%s | model=%s | mode=%s",
        len(texts),
        settings.embedding_model,
        request_mode,
    )

    response = _call_native_embedding_api(texts)
    response_dict = _response_to_dict(response)

    logger.info(
        "rag embeddings response received | elapsed=%.3fs | texts=%s | status_code=%s | code=%s",
        time.perf_counter() - started,
        len(texts),
        response_dict.get("status_code"),
        response_dict.get("code"),
    )

    if response_dict.get("status_code") not in (None, 200):
        raise RuntimeError(f"embedding 调用失败: {response_dict}")

    vectors = _extract_vectors(response_dict)

    logger.info(
        "rag embeddings parsed | elapsed=%.3fs | texts=%s | vectors=%s",
        time.perf_counter() - started,
        len(texts),
        len(vectors),
    )

    return vectors


def embed_documents(texts: list[str]) -> list[list[float]]:
    """
    给多段文档文本做 embedding。

    典型使用场景：
    - 离线建仓时，对切分后的 chunk 批量向量化
    - 把结果写入向量数据库
    """
    return _embed(texts)


def embed_query(text: str) -> list[float]:
    """
    给单条查询问题做 embedding。

    典型使用场景：
    - 在线问答时，把用户问题转成 query vector
    - 用于向量检索 / dense retrieval
    """
    vectors = _embed([text])

    if not vectors:
        raise RuntimeError("embedding 查询结果为空。")

    return vectors[0]


class DashScopeEmbeddings:
    """
    一个适配器类，用来兼容 Chroma / LangChain 所要求的 embedding 接口形式。

    上层向量库只关心 `embed_documents / embed_query`，不需要知道底层
    走的是 DashScope 原生文本 embedding 还是多模态 embedding。
    """

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return embed_query(text)
