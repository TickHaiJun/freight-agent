import hashlib

# 基于结构优先 + 控制大小的递归分块策略，它本质上是在做如下权衡：

# 不盲目按照固定长度切，而是尽量在语义自然边界（段落、句子等）处分割
# 保证每个 chunk 不超过一定 token/字符数，以兼容向量 embedding 和检索效率
# 使用 overlap 以缓和边界断点可能丢失关键信息的问题
def split_documents(documents: list, base_metadata: dict | None = None) -> list:
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    from config import settings

    # 优先按段落和中文标点切，尽量让“标题 + 说明”留在同一 chunk。
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.rag_chunk_size,
        chunk_overlap=settings.rag_chunk_overlap,
        separators=["\n\n", "\n", "。", "；", "，", " ", ""],
    )

    langchain_docs = []
    for item in documents:
        metadata = {**(base_metadata or {}), **item.get("metadata", {})}
        langchain_docs.append(Document(page_content=item["page_content"], metadata=metadata))

    chunks = splitter.split_documents(langchain_docs)
    result = []
    for index, chunk in enumerate(chunks):
        # 每个 chunk 都补齐检索和排障需要的元信息：
        # source_file / chunk_index 用于去重和追溯，
        # content_hash 用于后续增量更新或排查重复内容。
        enriched_metadata = {
            **chunk.metadata,
            "chunk_index": index,
            "chunk_size": len(chunk.page_content),
            "content_hash": hashlib.md5(chunk.page_content.encode("utf-8")).hexdigest(),
            "source_file": chunk.metadata.get("source_file"),
            "source_type": chunk.metadata.get("source_type"),
            "category": chunk.metadata.get("category"),
            "sub_category": chunk.metadata.get("sub_category"),
            "doc_type": chunk.metadata.get("doc_type"),
            "is_form": chunk.metadata.get("is_form"),
        }
        result.append(Document(page_content=chunk.page_content, metadata=enriched_metadata))
    return result
