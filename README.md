# AI Freight Agent

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-SSE%20API-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-Agent%20Workflow-121212)
![RAG](https://img.shields.io/badge/RAG-Hybrid%20Retrieval-5B6CFF)
![Logging](https://img.shields.io/badge/Logging-JSONL%20%2B%20Rotate-FF6B35)
![Status](https://img.shields.io/badge/Status-Active-2EA44F)

企业官网场景下的 AI 空运报价与业务知识助手。项目通过单一 `/api/chat` 接口，对外同时提供两类能力：

- 空运运价查询
- 物流业务知识问答

系统核心目标是把货代询价、参数追问、报价调用、结果解释、业务资料检索统一到一条稳定链路里，并保持前端对接方式简单可控。

## 项目定位

项目主要服务于公司官网或业务门户中的聊天窗口场景，适合承担以下角色：

- 作为空运报价助手，识别用户询价意图并自动追问缺失参数
- 作为业务知识助手，围绕公司资料、单证、操作规范做检索式回答
- 作为前端可集成服务，保持 SSE 流式输出和多轮 `context` 续聊协议
- 作为后续运维分析基础，输出结构化日志供前端监控平台和 AI 异常分析使用

## 当前能力

### 1. 空运运价查询

已实现一套完整的询价链路，覆盖：

- 意图识别
- 槽位提取
- 缺失参数追问
- 多轮上下文复用
- 空运报价工具调用
- 结果语义化输出
- 结果追问与结果解释

当前项目重点支持的典型询价字段包括：

- 始发港
- 目的港
- 重量
- 体积
- 航班日期
- 航班类型、包装类型、货物类型等扩展条件

### 2. RAG 知识问答

项目已经接入知识库链路，支持围绕内部业务资料进行检索与回答。整体路线为：

- 文档解析
- 文本清洗与切分
- Chroma 向量检索
- BM25 关键词检索
- 混合召回
- 基于检索结果生成回答

适合覆盖的资料类型包括：

- 锂电池 / 危险品说明
- 普货委托书与授权资料
- 报关清关资料
- 系统操作说明

### 3. SSE 流式接口

服务端保留单接口设计：

- `GET /health`
- `POST /api/chat`

`/api/chat` 返回 `text/event-stream`，前端可以逐字接收文本，并在每轮结束后拿到服务端回传的 `context`，继续发起多轮对话。

## 技术栈

### 后端框架

- Python 3.11+
- FastAPI
- Uvicorn
- SSE Starlette

### Agent 编排

- LangGraph
- LangChain
- DeepSeek API

### RAG 能力

- Chroma
- rank-bm25
- RecursiveCharacterTextSplitter
- DashScope Embedding

### 文档处理

- python-docx
- python-pptx
- pypdf
- pdfplumber

### 日志与数据处理

- 标准 logging
- JSONL 结构化日志
- 按天滚动日志文件
- orjson

## 整体架构

项目保持单入口、多链路路由的方式：

```text
用户输入
  -> intent_node
     -> rate_query        -> slot -> ask / tool -> result
     -> rag               -> rag_retrieve -> rag_answer
     -> result_analysis   -> result_analysis
     -> result_reference  -> result_reference
     -> support_info      -> support_info
     -> unknown           -> fallback
```

这种设计的特点是：

- 前端只需要维护一个聊天接口
- 业务能力和知识能力共用同一会话
- 可逐步扩展节点，不必推翻主链路

## 目录结构

当前仓库按照“主链路 + 工具 + RAG + 脚本 + 日志/文档”的方式组织：

```text
freight-agent/
├── main.py                # FastAPI 入口与 SSE 输出
├── config.py              # 统一配置入口
├── graph/                 # LangGraph 编排、状态、节点、Prompt
├── tools/                 # 报价工具与业务工具
├── rag/                   # RAG 文档入库、检索、生成
├── scripts/               # 知识库初始化与重建脚本
├── data/                  # 文档、Chroma、缓存、导出数据
├── docs/                  # 项目文档与日志目录
├── plan/                  # 方案与实施计划
└── tests/                 # 回归测试与模块测试
```

## 日志系统

项目已经接入配置化日志落盘，不再依赖终端重定向 `> history.log`。

### 日志输出方式

应用启动后会同时输出三类日志：

- `freight-agent-app.log`
- `freight-agent-app.jsonl`
- `freight-agent-error.log`

其中：

- `.log` 适合人工排查
- `.jsonl` 适合前端平台、批处理、可视化和 AI 分析
- `error.log` 只记录错误与异常事件

### 日志目录

日志目录通过配置项控制：

- 本地默认：`./docs/history`
- 服务器建议：`/data/logs/freight-agent`

对应环境变量：

- `APP_LOG_DIR`

### 日志轮转

日志按天滚动。当天活跃文件名固定，跨天后旧文件自动归档为带日期后缀的历史文件，便于：

- 按天回放会话
- 批量做异常分析
- 后续前端平台按天加载

### 日志用途

这套日志设计不仅用于开发排查，也为后续平台化预留了结构化数据基础，便于实现：

- UI 查询和筛选
- 会话回放
- 每日异常统计
- AI 总结和问题聚类

## 环境变量

项目通过 `.env` 管理核心配置。常用配置包括：

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`
- `FREIGHT_API_BASE`
- `DASHSCOPE_API_KEY`
- `EMBEDDING_MODEL`
- `CHROMA_PERSIST_DIR`
- `CHROMA_COLLECTION_NAME`
- `RAG_DOCS_DIR`
- `APP_LOG_DIR`
- `APP_LOG_LEVEL`

如果只想先跑主服务，至少应保证：

- DeepSeek 相关配置可用
- 报价接口地址可访问

如果要启用完整 RAG 检索，还需要准备：

- DashScope Embedding Key
- 文档目录
- 知识库索引目录

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 准备环境变量

在项目根目录创建 `.env`，填入必要配置。

### 3. 启动服务

本地开发建议：

```bash
uvicorn main:app --host 0.0.0.0 --port 8012 --reload
```

生产环境建议去掉 `--reload`：

```bash
uvicorn main:app --host 0.0.0.0 --port 8012
```

### 4. 健康检查

```bash
curl http://127.0.0.1:8012/health
```

### 5. 构建知识库

首次初始化：

```bash
python -m scripts.init_kb
```

全量重建：

```bash
python -m scripts.rebuild_kb
```

如果文档后缀、文件名或文档集合发生变化，更推荐使用 `rebuild_kb`。

## 知识库资料管理

新增或替换知识库文件时，建议遵循这条流程：

1. 把文档放入 `data/docs`
2. 在 `rag/metadata.py` 中补齐对应 metadata
3. 执行 `python -m scripts.rebuild_kb`

这样可以避免旧索引残留和来源文件不一致的问题。






## 说明

本仓库当前重点是稳定现有报价链路、补齐 RAG 能力、并为后续日志平台和运维分析提供基础设施。对接前端时，建议优先遵循现有 `/api/chat` SSE 协议和服务端回传的 `context` 机制，不要自行改造协议字段。
