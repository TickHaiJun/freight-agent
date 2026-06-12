# 这个文件本质上是你项目里的“建库编排层”。
# 它不负责底层怎么存向量，也不负责具体怎么分词、怎么切 chunk、怎么读 PDF，它负责的是把这些步骤按正确顺序串起来，让“建知识库”这件事稳定发生。


# 这个文件目前主要做了四件事。

# 第一件事是准备环境。_ensure_dirs() 负责把 Chroma 持久化目录、BM25 缓存目录、chunk 导出目录都提前建好。这个动作看起来小，但很工程化，因为它把“环境准备”从业务流程里提前抽掉了，避免你每次构建时因为目录不存在报错。

# 第二件事是单文件索引。index_document() 负责一份文件的完整链路：读取、清洗、切分、删旧、写新。这里最关键的设计点是“先删后加”。这意味着你现在的单文件重建策略不是增量 diff，而是按 source_file 粒度覆盖。这种方式不算高级，但第一版很稳，尤其适合你现在这个阶段。

# 第三件事是整库构建。build_knowledge_base() 会遍历整个文档目录，对每一个文件做同样的处理，然后把所有 chunk 汇总起来，再统一构建 BM25，并且导出 chunks.json。也就是说，这个函数不只是“写向量库”，而是在完成一次完整的“双索引建库”。

# 第四件事是全量重建。rebuild_knowledge_base() 采用的是最朴素但稳定的策略：删 Chroma 落盘目录、删 BM25 缓存、重置 collection，然后重新 build。这个选择很典型，说明你现在的设计倾向是“先把全链路稳定跑通，再考虑复杂增量更新”。这个方向是对的。

# 如果从职责边界看，这个文件不该承载太多底层细节。比如它不应该自己去实现 PDF 解析，也不应该自己去实现 Chroma 的 collection.add()，这些已经被 loaders、splitter、vector_store 各自承接掉了。它更像一个 orchestration 层，负责调度，而不是负责所有能力本身。

# 你可以把这个文件的链路记成这样：

# 这里还有几个你值得注意的点。

# 第一个点，这个文件现在的幂等策略主要依赖 delete_by_source_file()。也就是说，它假设每个 chunk 的 metadata 里都有足够稳定的 source_file 字段，否则删旧逻辑可能失效。所以从工程上说，你要确认 split_documents() 或 metadata 构建逻辑里，确实把 source_file 放进去了，而且是稳定值。

# 第二个点，BM25 构建是在所有文件处理完成之后统一做的。这意味着你的 BM25 当前不是“增量更新式”，而是“基于本次全量 chunk 重建”。这在小中型项目里没问题，逻辑也最简单。但以后如果文档变多、频繁单文件更新，这里可能会成为一个优化点。

# 第三个点，_export_chunks() 很有价值，它不是可有可无的调试代码。RAG 项目里，很多问题最后都要回到“chunk 切得对不对、metadata 继承对不对”。把切分结果导出来，其实是在给后面排查召回问题留抓手。

# 第四个点，rebuild_knowledge_base() 现在是“物理删除 + 重建”，这是稳定路线，但要清楚它的边界：一旦目录大了、索引大了、建库时间长了，你后面可能得往“按文档增量重建”迁移。不过你当前阶段先这样做是合理的，不用一开始就上复杂方案。



import json
import shutil
from pathlib import Path

from config import settings
from rag.bm25_store import build_bm25_index
from rag.cleaner import clean_documents
from rag.loaders import load_document
from rag.metadata import get_metadata, validate_metadata
from rag.splitter import split_documents
from rag.vector_store import add_documents, delete_by_source_file, reset_collection


def _doc_paths() -> list[Path]:
    """
    收集知识库目录下所有待处理文件的路径。

    这里约定：
    - settings.rag_docs_dir 是知识库原始文档目录
    - 只处理文件，不处理子目录
    - 返回结果按文件名排序，保证每次建库顺序稳定，便于排查问题和对比结果

    返回：
        list[Path]: 当前知识库目录下的文件路径列表
    """
    return sorted(path for path in Path(settings.rag_docs_dir).glob("*") if path.is_file())


def _ensure_dirs() -> None:
    """
    确保建库过程中依赖的目录都存在。

    主要包含三类目录：
    1. 向量库持久化目录：Chroma 的本地落盘目录
    2. 缓存目录：例如 BM25 的本地缓存文件
    3. 导出目录：例如导出 chunk 结果，方便人工排查

    这样做的目的是：
    - 避免第一次运行时目录不存在导致报错
    - 把“环境准备”放在建库入口统一处理
    """
    Path(settings.chroma_persist_dir).mkdir(parents=True, exist_ok=True)
    Path("data/cache").mkdir(parents=True, exist_ok=True)
    Path("data/exports").mkdir(parents=True, exist_ok=True)


def _export_chunks(documents: list) -> None:
    """
    将切分后的 chunk 导出到本地 JSON 文件，方便人工检查。

    导出的内容包括：
    - page_content: chunk 的正文内容
    - metadata: 该 chunk 继承和补充后的元数据

    这个导出文件主要用于：
    - 检查 chunk 切分质量是否合理
    - 检查 metadata 是否正确继承
    - 排查“为什么召回结果不对”

    参数：
        documents (list): 切分后的 LangChain Document 列表
    """
    # 将 Document 对象转换成可序列化的普通字典
    payload = [{"page_content": doc.page_content, "metadata": doc.metadata} for doc in documents]

    # 写入本地 JSON 文件，保留中文并格式化输出，方便直接打开查看
    Path("data/exports/chunks.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def index_document(filepath: str, metadata: dict) -> int:
    """
    单文件建索引入口。

    处理链路是：
    读取文件 -> 文本清洗 -> chunk 切分 -> 删除旧 chunk -> 写入新 chunk

    这里采用“同 source_file 先删后加”的策略，避免同一个文件重复入库。
    这种方式比较直接，适合第一版工程实现，逻辑也更稳定。

    参数：
        filepath (str): 待索引文件路径
        metadata (dict): 当前文件对应的基础 metadata

    返回：
        int: 本次成功写入的 chunk 数量
    """
    # 1) 读取原始文档，返回统一格式的文档对象列表
    raw_docs = load_document(filepath)

    # 2) 对原始文档做基础清洗，例如去掉明显噪声、空白、无意义字符等
    cleaned_docs = clean_documents(raw_docs)

    # 3) 将清洗后的文档切成 chunk，并把基础 metadata 传进去
    chunks = split_documents(cleaned_docs, base_metadata=metadata)

    # 如果没有切出任何 chunk，直接返回 0，表示该文件没有实际写入内容
    if not chunks:
        return 0

    # 4) 删除当前 source_file 之前写入过的旧 chunk
    #    这样同一个文件重复索引时，不会在向量库里产生重复数据
    delete_by_source_file(Path(filepath).name)

    # 5) 将新的 chunk 批量写入向量库
    add_documents(chunks)

    # 返回当前文件写入的 chunk 数量
    return len(chunks)


def build_knowledge_base() -> dict:
    """
    构建整个知识库。

    这是一个“全目录扫描 + 逐文件建索引”的流程，核心步骤是：
    1. 准备目录
    2. 校验 metadata
    3. 遍历知识库目录下所有文件
    4. 对每个文件执行：加载 -> 清洗 -> 切分 -> 删除旧数据 -> 写入向量库
    5. 基于所有 chunk 构建 BM25 索引
    6. 导出 chunk 结果，方便人工检查
    7. 返回构建摘要信息

    返回：
        dict: 本次建库统计信息，例如处理了多少文档、写入了多少 chunk
    """
    # 准备本地依赖目录
    _ensure_dirs()

    # 校验 metadata 配置是否完整
    # 一般会检查：知识库目录中的文件是否都有对应 metadata、格式是否正确等
    validate_metadata(settings.rag_docs_dir)

    # all_chunks 用来收集本次所有切出的 chunk
    # 后面 BM25 建索引和导出 chunks.json 都会用到
    all_chunks = []

    # 用于记录本次建库的摘要信息
    summary = {"documents": 0, "chunks": 0}

    # 遍历知识库目录下所有文件
    for path in _doc_paths():
        # 读取当前文件对应的 metadata
        metadata = get_metadata(path.name)

        # 1) 加载原始文档
        raw_docs = load_document(str(path))

        # 2) 清洗文档内容
        cleaned_docs = clean_documents(raw_docs)

        # 3) 切分 chunk，并附加基础 metadata
        chunks = split_documents(cleaned_docs, base_metadata=metadata)

        # 如果当前文件没有产生有效 chunk，则跳过
        if not chunks:
            continue

        # 4) 先删后加，避免同一个 source_file 重复导入
        #    这是当前版本里比较稳的一种幂等策略
        delete_by_source_file(path.name)

        # 5) 把 chunk 写入向量库
        add_documents(chunks)

        # 6) 汇总本次建库生成的所有 chunk，供 BM25 和导出使用
        all_chunks.extend(chunks)

        # 7) 更新统计信息
        summary["documents"] += 1
        summary["chunks"] += len(chunks)

    # 基于本次所有 chunk 构建 BM25 索引
    # 这样后续就可以支持“关键词检索 + 向量检索”的混合召回
    build_bm25_index(all_chunks)

    # 将所有 chunk 导出为 JSON，方便人工检查质量
    _export_chunks(all_chunks)

    # 返回本次建库摘要
    return summary


def rebuild_knowledge_base() -> dict:
    """
    全量重建知识库。

    当前实现采用的是“全量清空后重建”的策略，特点是：
    - 实现简单
    - 行为明确
    - 稳定性优先
    - 不需要先处理复杂的增量更新逻辑

    重建步骤：
    1. 准备目录
    2. 删除 Chroma 本地持久化目录
    3. 删除 BM25 缓存文件
    4. 重置向量库 collection
    5. 重新执行 build_knowledge_base()

    返回：
        dict: 重建后的统计摘要
    """
    _ensure_dirs()

    # rebuild 采用“全量清空后重建”，第一版优先保证流程清晰和结果稳定
    chroma_dir = Path(settings.chroma_persist_dir)

    # 如果 Chroma 持久化目录存在，直接删除整个目录
    if chroma_dir.exists():
        shutil.rmtree(chroma_dir)

    # 删除 BM25 的本地缓存文件
    bm25_path = Path("data/cache/bm25.pkl")
    if bm25_path.exists():
        bm25_path.unlink()

    # 重置向量库 collection，确保内存态 / 客户端态也回到干净状态
    reset_collection()

    # 基于当前文档目录重新构建整个知识库
    return build_knowledge_base()