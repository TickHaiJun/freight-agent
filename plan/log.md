# 实施日志

## 2026-03-24 阶段 1：配置与 RAG 骨架初始化
- 新增 RAG 相关配置项到 `config.py`，但未改动 `/api/chat` 请求与 SSE 返回协议。
- 扩展 `graph/state.py`，补充 RAG 中间状态字段，便于后续检索与生成分阶段调试。
- 扩展 `requirements.txt`，补齐文档解析、向量库、BM25、切分等依赖声明。
- 按 AGENTS.md 目录约束创建 `rag/` 各模块文件，并将 RAG Prompt 独立放入 `rag/prompts.py`，没有混入现有 `graph/prompts.py`。
- 当前阶段只建立职责边界和导出接口，主流程尚未接入，避免在基础能力未落地前影响现有运价查询。

## 2026-03-24 阶段 2：离线入库与检索基础能力
- 在 `rag/metadata.py` 固化 8 份业务文件的 metadata，避免后续检索只能裸搜。
- 在 `rag/loaders.py` 实现 PDF、DOCX、PPTX 解析，并为旧版 `.doc` 增加 Windows Word COM 读取方案；这是因为实际资料中有 4 份 `.doc`，不用兜底解析就无法建库。
- 在 `rag/cleaner.py`、`rag/splitter.py` 实现轻量清洗与 `RecursiveCharacterTextSplitter` 切分，确保 chunk 带完整 metadata。
- 在 `rag/embeddings.py`、`rag/vector_store.py`、`rag/bm25_store.py`、`rag/indexer.py` 实现 embedding、Chroma、BM25、build/rebuild 闭环，离线知识库链路具备可执行能力。

## 2026-03-24 阶段 3：在线 RAG 链路接入
- 在 `rag/query_analyzer.py` 先实现规则优先，再以 LLM 作为补充，降低小样本知识库的误判成本。
- 在 `rag/retriever.py` 实现“向量 + BM25”混合检索和 filter 失败回退到无 filter 的兜底策略。
- 在 `rag/generator.py`、`rag/service.py` 实现基于检索片段的回答生成和中间状态回传。
- 在 `graph/agent.py`、`graph/nodes.py` 中增加 `rag_retrieve_node`、`rag_answer_node`，将 `intent=rag` 从兜底改为真实 RAG 流程。
- 在 `main.py` 仅补 RAG 状态初始化字段，没有修改 `/api/chat` 请求结构、SSE event 类型或 `context` 回传协议。

## 2026-03-24 阶段 4：脚本与测试补齐
- 新增 `scripts/init_kb.py`、`scripts/rebuild_kb.py`、`scripts/test_rag.py`，用于初始化、重建和本地调试知识库。
- 新增基础单元测试，优先覆盖 query analyzer、cleaner、service 编排这类不依赖外部接口的稳定逻辑。

## 2026-03-24 阶段 5：验证与清理
- 运行 `python -m compileall graph rag scripts tests main.py config.py`，通过静态编译检查，未发现语法错误。
- 运行 `python -m unittest tests.test_rag_query_analyzer tests.test_rag_cleaner tests.test_rag_service`，共 6 个测试全部通过。
- 未执行真实知识库构建与 `/api/chat` 联调，因为当前环境未确认已安装新增依赖、Microsoft Word、DashScope/DeepSeek 密钥与 Chroma 持久化条件。

## 2026-03-24 阶段 6：RAG 代码注释与说明文档
- 为 `rag/` 主要模块以及 `graph/` 中接入 RAG 的关键位置补充了解释性注释，重点说明 metadata、旧版 `.doc` 解析、chunk 设计、混合检索、filter 回退和 LangGraph 节点拆分原因。
- 新增 `RAG.md`，系统讲解离线建库链路、在线问答链路、模块职责、状态流转、配置项和已知风险，并补充 mermaid 图帮助理解模块关联。

## 2026-03-24 阶段 7：补充逐文件阅读顺序与调试手册
- 在 `RAG.md` 中新增逐文件阅读手册，按“边界/入口 -> 离线建库 -> 在线检索 -> 图接入”的顺序细化阅读路径。
- 在 `RAG.md` 中新增调试手册，覆盖建库失败、检索不准、回答偏差、未进入 RAG、`.doc` 解析失败等常见问题的定位思路和推荐命令。
