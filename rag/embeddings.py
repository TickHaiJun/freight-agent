import logging
import time

from openai import OpenAI

from config import settings

# 当前模块的日志对象，用来记录 embedding 调用过程中的关键日志
logger = logging.getLogger(__name__)


# “基础能力封装层”。
# 一条是离线建仓链路，也就是 chunk 切好之后，要做 embedding，写进向量库。这时候主要走的是 embed_documents()。

# 另一条是在线检索链路，也就是用户提了一个问题，要把 query 转成向量，拿去做 dense retrieval。这时候主要走的是 embed_query()。


def _get_client() -> OpenAI:
    """
    创建并返回一个 OpenAI 兼容客户端。

    这里虽然导入的是 openai.OpenAI，
    但实际上通过 base_url 指向了阿里云 DashScope 的兼容接口，
    所以本质上是在“用 OpenAI 兼容协议调用 DashScope embedding 服务”。

    这里先做一次配置校验：
    如果没有配置 dashscope_api_key，就直接报错，避免后面请求时才失败。
    """
    if not settings.dashscope_api_key:
        raise RuntimeError("缺少 DASHSCOPE_API_KEY，无法调用 embedding 接口。")

    return OpenAI(
        api_key=settings.dashscope_api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
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
    # 这是一个很实用的短路逻辑，避免无意义的外部调用
    if not texts:
        logger.info(
            "rag embeddings skipped | elapsed=%.3fs | texts=0",
            time.perf_counter() - started
        )
        return []

    # 获取 embedding 客户端
    client = _get_client()

    # 记录请求开始日志，方便排查性能问题或请求量问题
    logger.info(
        "rag embeddings request start | texts=%s | model=%s",
        len(texts),
        settings.embedding_model
    )

    # 调用 embedding 接口
    # input 可以一次传多段文本，因此这里支持批量 embedding
    response = client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )

    # 记录响应返回日志
    logger.info(
        "rag embeddings response received | elapsed=%.3fs | texts=%s | response_items=%s",
        time.perf_counter() - started,
        len(texts),
        len(response.data or []),
    )

    # 如果接口返回里没有 data，认为这是异常情况，直接报错
    # 这样比静默返回空结果更安全，不容易把问题掩盖掉
    if not response.data:
        raise RuntimeError(f"embedding 返回为空: {response.model_dump()}")

    # 从接口响应中提取每一条 embedding 向量
    vectors = [item.embedding for item in response.data]

    # 记录解析完成日志
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

    输入：
        texts = ["文档片段1", "文档片段2", ...]

    输出：
        [
            [向量1...],
            [向量2...],
            ...
        ]
    """
    return _embed(texts)


def embed_query(text: str) -> list[float]:
    """
    给单条查询问题做 embedding。

    典型使用场景：
    - 在线问答时，把用户问题转成 query vector
    - 用于向量检索 / dense retrieval

    输入：
        text = "订单超时取消后，优惠券会自动退回吗？"

    输出：
        [查询向量...]

    说明：
        底层仍然复用 _embed，只是把单条字符串包装成一个长度为 1 的列表，
        最后再取回第一条向量。
    """
    vectors = _embed([text])

    # 理论上 _embed 成功返回后，这里应该至少有一条结果
    # 如果没有，说明接口行为异常，直接报错
    if not vectors:
        raise RuntimeError("embedding 查询结果为空。")

    return vectors[0]


class DashScopeEmbeddings:
    """
    一个适配器类，用来兼容 Chroma / LangChain 所要求的 embedding 接口形式。

    很多向量库或框架不会直接接收一个函数，
    而是要求你传入一个“具备 embed_documents / embed_query 方法的对象”。

    这里的作用就是把我们自己的封装，适配成框架能识别的对象。
    """

    # Chroma / LangChain 在“文档入库”时会调用这个方法
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return embed_documents(texts)

    # Chroma / LangChain 在“查询检索”时会调用这个方法
    def embed_query(self, text: str) -> list[float]:
        return embed_query(text)