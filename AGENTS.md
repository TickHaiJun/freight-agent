# 工作语言
- 全程使用中文思考和回复 
- 执行前说明意图 
-  遇到决策说明理由 
-  完成后总结结果 
-  优先保持现有运价查询链路稳定，新增 RAG 时不能破坏现有 /api/chat SSE 协议与前端对接方式。现有项目文档已经明确这些约束。
---

## 项目概述
本项目用于为公司门户网站开发一个 AI 运价 Agent，用户通过官网聊天窗口完成两类能力：

1.  空运运价查询 
2.  物流业务知识问答 

其中，空运运价查询能力已经实现，采用 LangGraph 编排意图识别、槽位提取、追问补参、工具调用、结果语义化的完整流程；聊天接口通过 FastAPI 暴露，并以 SSE 逐字流式返回文本，同时在响应中返回 `context` 槽位状态供前端缓存并参与下一轮对话。

当前未完成部分是 RAG 知识问答。该模块将接入业务资料文件，支持围绕锂电池、危险品、普货委托、系统操作、报关清关等问题进行检索与回答。你已经明确了 RAG 的技术路线：Chroma 作为向量库，阿里云百炼 `qwen3-vl-embedding` 作为向量模型，DeepSeek 作为生成模型，文档切分使用 `RecursiveCharacterTextSplitter`，检索采用“向量 + BM25 混合”，必要时增加 reranker 做重排。





## 当前项目状态
### 已完成
1. `FastAPI` 服务入口已实现。 
2. `/health` 健康检查接口已实现。 
3. `/api/chat` 聊天接口已实现，返回格式为 `text/event-stream` SSE。 
4.  LangGraph 运价流程已实现，包括： 
    -  意图识别 
    -  槽位提取 
    -  缺失字段追问 
    -  空运运价工具调用 
    -  结果语义化输出 
    - `unknown` / `rag` 兜底回复 
5.  前端多轮对话依赖 `context` 回传机制，已在接口文档和调用文档中明确。

### 未完成
1. `rag` 知识库模块仍为占位实现。 
2.  业务文档入库脚本未实现。 
3.  向量检索、BM25 混合检索、metadata 过滤、知识回答生成未实现。 
4. `intent == "rag"` 目前仍走兜底提示“业务详情查询功能正在建设中”。这一点在现有 Agent 流程说明中已经明确。

---

## 项目目标
本阶段目标不是推翻现有架构，而是在不破坏现有运价查询能力的前提下，补齐 RAG 模块，实现一个统一的 AI Agent：

+  询价类问题走工具调用 
+  业务知识类问题走知识库检索 
+  闲聊或无关问题走兜底引导 

最终保持一个统一接口 `/api/chat`，由意图识别节点自动路由至不同子流程。这个路由思想已经存在于现有 `intent_node -> rate_query / rag / unknown` 设计中。

---

## 技术栈
### 已有技术栈
+  Python 3.11+ 
+  FastAPI 
+  LangGraph V1 
+  LangChain V1 
+  DeepSeek API 
+  uvicorn 
+  httpx 
+  sse-starlette 
+  pydantic-settings 

这些来自现有 `CLAUDE.md` 与接口文档。

### 本阶段新增技术栈
以下为建议补充项，用于实现 RAG：

+  Chroma：向量存储 
+  阿里云百炼 Embedding：`qwen3-vl-embedding`
+  BM25：关键词检索 
+  文档解析： 
    -  PDF：`pypdf` 或 `pdfplumber`
    -  DOCX：`python-docx`
    -  PPTX：`python-pptx`
+  文本切分：`RecursiveCharacterTextSplitter`
+  reranker：先预留接口，第一版可不开启，第二版再接 

这里的原则是：先把 RAG 跑通，再考虑重排优化；不要一上来把复杂度拉满。



## 总体架构
## 一、对外能力
系统对外只暴露两个 HTTP 接口：

```plain
GET  /health
POST /api/chat
```

+ `/health` 用于服务健康检查。 
+ `/api/chat` 用于所有用户对话，包括运价查询与知识问答。当前接口与请求结构已经确定，不建议在 RAG 接入阶段改动。

## 二、对内流程
```plain
用户输入
  ↓
intent_node
  ├── rate_query → slot_node → ask_node / tool_node → result_node
  ├── rag        → rag_retrieve_node → rag_answer_node
  └── unknown    → fallback_node
```

现有运价链路保留不动，只把现有 `rag -> fallback` 改为 `rag -> RAG 流程`。这与现有 Agent 流程说明是一致的扩展，而不是重做。

---

## 项目目录结构（完整建议版）
以下目录是在你当前目录基础上进行最小侵入式扩展，既保留现有结构，又让 RAG 能独立维护：

```plain
freight-agent/
├── CLAUDE.md                        # 项目主开发文档（本文件）
├── detail.md                        # 接口文档与使用说明（现有）
├── use.md                           # 启动与调用指南（现有）
├── main.py                          # FastAPI 入口
├── config.py                        # 环境变量配置
├── requirements.txt                 # 依赖清单
├── .env                             # 环境变量（不提交 git）
├── .gitignore
│
├── graph/
│   ├── __init__.py
│   ├── agent.py                     # LangGraph 主流程构建
│   ├── state.py                     # AgentState 定义
│   ├── nodes.py                     # 所有节点函数
│   └── prompts.py                   # 所有 Prompt 模板（集中管理）
│
├── tools/
│   ├── __init__.py
│   └── air_freight.py               # 空运运价工具
│
├── rag/
│   ├── __init__.py                  # 对外统一暴露 query_knowledge_base / build_knowledge_base
│   ├── metadata.py                  # 8 个业务文件的 DOCUMENT_METADATA 配置
│   ├── loaders.py                   # PDF/DOCX/PPTX 文档解析
│   ├── cleaner.py                   # 文本清洗
│   ├── splitter.py                  # 文档切分
│   ├── embeddings.py                # 百炼 embedding 封装
│   ├── vector_store.py              # Chroma 初始化与读写
│   ├── bm25_store.py                # BM25 索引构建与查询
│   ├── indexer.py                   # 文档入库主流程
│   ├── query_analyzer.py            # 用户问题分析，生成检索 query 和 metadata filter
│   ├── retriever.py                 # Hybrid Retrieval：向量 + BM25 + merge
│   ├── reranker.py                  # 预留重排模块，第一版可空实现
│   ├── generator.py                 # 基于检索结果生成最终回答
│   ├── prompts.py                   # RAG 相关 Prompt
│   └── service.py                   # RAG 对外服务编排
│
├── data/
│   ├── docs/                        # 原始业务文件
│   ├── chroma/                      # Chroma 持久化目录
│   ├── cache/                       # 解析缓存 / BM25 索引缓存
│   └── exports/                     # 入库调试产物
│
├── scripts/
│   ├── init_kb.py                   # 一键初始化知识库
│   ├── rebuild_kb.py                # 重建知识库
│   └── test_rag.py                  # RAG 本地调试脚本
│
└── tests/
    ├── test_air_freight.py
    ├── test_chat_api.py
    ├── test_rag_indexer.py
    ├── test_rag_retriever.py
    └── test_rag_generator.py
```

现有 `CLAUDE.md` 中只有 `rag/__init__.py` 作为占位；本方案是在保持现有主目录与 `graph/`、`tools/` 结构不变的基础上，把 `rag/` 扩为一个真正可维护的业务模块。





## 环境变量（.env）
现有环境变量如下：

```plain
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

FREIGHT_API_BASE=http://192.168.0.186:9000
```

这是现有运价查询模块必须的配置。

为了接入 RAG，建议补充：

```plain
# 百炼 Embedding
DASHSCOPE_API_KEY=your_dashscope_api_key
EMBEDDING_MODEL=qwen3-vl-embedding

# Chroma
CHROMA_PERSIST_DIR=./data/chroma
CHROMA_COLLECTION_NAME=freight_knowledge

# RAG 可选参数
RAG_TOP_K_VECTOR=8
RAG_TOP_K_BM25=8
RAG_TOP_K_FINAL=4
RAG_CHUNK_SIZE=500
RAG_CHUNK_OVERLAP=100
RAG_ENABLE_RERANK=false

# 文档目录
RAG_DOCS_DIR=./data/docs
```

### 配置原则
1.  现有运价接口地址、DeepSeek Key 不改名，避免破坏已实现代码。 
2.  RAG 所有参数独立命名，方便后续在不同环境调优。 
3.  Chroma 持久化目录必须显式配置，避免不同机器运行时索引写到未知位置。 

---

## requirements.txt（建议完整版）
现有依赖如下：

```plain
fastapi
uvicorn
python-dotenv
pydantic-settings
langchain
langchain-openai
langgraph
httpx
sse-starlette
```

这些来自现有项目。

建议补充为：

```plain
fastapi
uvicorn
python-dotenv
pydantic-settings
langchain
langchain-openai
langgraph
httpx
sse-starlette

chromadb
rank-bm25
python-docx
python-pptx
pypdf
pdfplumber
tiktoken
orjson
```

### 说明
+ `chromadb`：向量库 
+ `rank-bm25`：BM25 检索 
+ `python-docx` / `python-pptx` / `pypdf` / `pdfplumber`：文档解析 
+ `tiktoken`：后续如需按 token 控制 chunk 可使用 
+ `orjson`：可选，提升 JSON 处理效率 

---

## config.py
现有 `config.py` 已能读取 DeepSeek 与运价接口配置。

建议扩展为统一配置中心：

```plain
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # LLM
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # Quote API
    freight_api_base: str

    # Embedding
    dashscope_api_key: str | None = None
    embedding_model: str = "qwen3-vl-embedding"

    # Chroma
    chroma_persist_dir: str = "./data/chroma"
    chroma_collection_name: str = "freight_knowledge"

    # RAG Params
    rag_top_k_vector: int = 8
    rag_top_k_bm25: int = 8
    rag_top_k_final: int = 4
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 100
    rag_enable_rerank: bool = False

    # Docs
    rag_docs_dir: str = "./data/docs"

    class Config:
        env_file = ".env"

settings = Settings()
```

### 职责说明
`config.py` 的职责不是保存业务逻辑，而是唯一配置入口。所有模型名、路径、阈值、TopK、开关都从这里读取，禁止在 `graph/`、`rag/`、`tools/` 中硬编码。





## 现有运价模块说明
### graph/state.py
现有 `AgentState` 已包含：

+ `messages`
+ `intent`
+ `sfg`
+ `mdg`
+ `inputWeight`
+ `inputVol`
+ `hbrq`
+ `missing_slots`
+ `query_ready`
+ `api_result`
+ `api_error`
+ `rag_query`

这一结构已足以支撑运价查询，并为 RAG 留了一个 `rag_query` 占位字段。

为了让 RAG 流程更清晰，建议增加以下状态字段：

```plain
retrieval_query: str | None
retrieval_filters: dict | None
retrieved_docs: list | None
rag_answer: str | None
```

### graph/prompts.py
现有 Prompt 文件已经集中管理了：

1.  意图识别 Prompt 
2.  槽位提取 Prompt 
3.  追问 Prompt 
4.  结果语义化 Prompt 
5.  兜底回复 

这个设计方向是正确的：Prompt 必须集中管理，节点函数只负责编排，不要把大段提示词散落在代码里。

RAG 接入后，仍保持同一原则：

+  运价 Prompt 放在 `graph/prompts.py`
+  RAG Prompt 放在 `rag/prompts.py`

不要把两类 Prompt 混在一起。

### tools/air_freight.py
现有工具已经完成：

+  参数 schema 定义 
+  城市到机场语义推断描述 
+  重量单位换算描述 
+  体积输入说明 
+  航班日期说明 
+  计费重计算 
+  运价接口调用 
+  超时 / HTTP / 未知异常处理 

其中“计费重 = max(实重, 体积重)”这一核心业务规则已经在 Python 工具中实现，而不是交给模型自由发挥，这是正确的做法，应保持不变。

### main.py
现有 `main.py` 已明确以下职责：

1.  定义 `FastAPI` 应用 
2.  暴露 `/api/chat`
3.  初始化 `AgentState`
4.  调用 `agent.invoke`
5.  按字符模拟流式返回 
6.  返回 `context`
7.  返回 `done`
8.  提供 `/health`

这一接口行为已经被 `detail.md` 与 `use.md` 固化，RAG 接入时不能改变响应事件协议





## RAG 模块设计
## 一、设计目标
RAG 模块的职责不是替代运价工具，而是处理业务知识类问答，例如：

+  锂电池货物需要什么声明文件 
+  ACCOS 系统如何录入分单件数 
+  普货交运授权委托书怎么填写 
+  上海口岸空运出口报关品名清单如何使用 
+  危险品授权委托书适用哪些货物 

这些问题不需要调用报价接口，而需要检索文档并生成可读答案。你已经明确这部分由单一 Collection + metadata 过滤来完成。

## 二、知识库范围
当前业务文件共 8 个，分为四类：

1.  危险品 / 锂电池类：5 个 
2.  系统操作类：1 个 
3.  普货类：1 个 
4.  报关清关类：1 个 

现阶段文档量很小，因此只使用一个 Collection：`freight_knowledge`，不拆多个 Collection。这个判断来自你给出的约束，本方案保持不变。

## 三、Collection 设计
```plain
freight_knowledge
├── 危险品/锂电池类
├── 系统操作类
├── 普货类
└── 报关清关类
```

### 原则
1.  现阶段只建一个 Collection，控制复杂度。 
2.  区分文档依赖 metadata，而不是 collection 拆分。 
3.  后续如果业务线快速增长，再考虑按 `business_line` / `tenant` / `department` 拆 Collection。 

---

## 业务文件清单
8 个文件统一放在data/docs/这里了，这些文件类型覆盖 PDF、Word、PPT。





## metadata 设计
你已经提供了 `DOCUMENT_METADATA` 的初版设计，这部分是当前 RAG 精度的核心，应直接固化到 `rag/metadata.py` 中。其主要字段包括：

+ `business_line`
+ `category`
+ `sub_category`
+ `doc_type`
+ `applicable_to`
+ `keywords`
+ `is_form`
+ `port`
+ `version`

现有分类包括：

+ `dangerous_goods`
+ `operations`
+ `general_cargo`
+ `customs`

这是合理且足够的第一版抽象。

### metadata.py 职责
`rag/metadata.py` 只做一件事：维护所有业务文件的元信息配置与校验函数。

建议结构：

```plain
DOCUMENT_METADATA = {...}

def get_metadata(filename: str) -> dict:
    ...

def validate_metadata() -> None:
    ...
```

### 元数据使用原则
1.  每个原始文件必须有且仅有一份 metadata。 
2.  所有 chunk 继承其所属文件的 metadata。 
3.  每个 chunk 额外补充： 
    - `source_file`
    - `chunk_index`
    - `source_type`
    - `content_hash`

### 为什么 metadata 是核心
你已经给出很典型的检索示例：

+  问锂电池声明文件时，只查危险品类 
+  问 ACCOS 时，只查操作类 
+  问普货委托书时，限制为 `general_cargo + is_form=True`

这个方向完全正确，因为你当前文档量虽小，但文档类型差异很大，如果不做过滤，检索结果会很容易互相污染







## rag/loaders.py
### 职责
统一解析 PDF / DOCX / PPTX，输出标准化的文档对象列表。

### 输入
+  文件绝对路径 
+  文件名 
+  文件扩展名 

### 输出
建议统一为：

```plain
[
    {
        "page_content": "...",
        "metadata": {
            "source_file": "...",
            "page": 1,
            "slide": None,
            ...
        }
    }
]
```

### 解析规则
#### PDF
+  优先按页提取文本 
+  记录页码 
+  去掉过多空行 
+  尽量保留段落顺序 

#### DOCX
+  读取段落 
+  表格内容如能读取则拼成文本 
+  保留标题与正文顺序 

#### PPTX
+  逐页读取文本框内容 
+  保留 slide 编号 
+  一页 PPT 作为一个逻辑块再进入后续 splitter 

### 设计原则
1.  loader 只负责“读”，不负责切分。 
2.  loader 不做业务判断，不决定 metadata filter。 
3.  所有解析错误必须抛出可定位异常，不允许静默失败。 

---

## rag/cleaner.py
### 职责
把 loader 读出来的原始文本做轻量清洗，避免噪声影响 embedding 与 BM25。

### 建议清洗内容
+  合并连续空白符 
+  去掉纯空行 
+  去掉明显页眉页脚重复文本 
+  统一中英文括号和冒号的空格格式 
+  去掉明显的页码占位文本 

### 注意
不要在 cleaner 里做过度“改写”。尤其是表单、声明、授权委托书这类文件，文本的法律与业务表述要尽量原样保留。

---

## rag/splitter.py
### 职责
负责 chunk 切分，把清洗后的长文档转为适合 embedding 与检索的文档片段。

### 方案
使用你指定的 `RecursiveCharacterTextSplitter`。

建议参数：

```plain
chunk_size = 500
chunk_overlap = 100
```

### 原因
1.  当前文档是表单、说明、清单、制度类文档，不是长篇叙述文。 
2.  chunk 太大，会让一个 chunk 混入多个表单区域，检索不准。 
3.  chunk 太小，会丢失上下文，尤其是“标题 + 填写说明”会被拆开。 

### 输出要求
每个 chunk 必须补充：

+ `chunk_index`
+ `chunk_size`
+ `source_file`
+ `category`
+ `sub_category`
+ `doc_type`
+ `is_form`

---

## rag/embeddings.py
### 职责
封装百炼 embedding 调用，不让上层业务感知底层 SDK 细节。

### 对外接口建议
```plain
def embed_documents(texts: list[str]) -> list[list[float]]:
    ...

def embed_query(text: str) -> list[float]:
    ...
```

### 原则
1. `embed_query` 与 `embed_documents` 分开。 
2.  embedding 层不关心 metadata，不关心 Chroma。 
3.  所有调用失败要抛出明确异常，不能返回空向量。





## rag/vector_store.py
### 职责
负责 Chroma 持久化目录初始化、Collection 获取、文档写入、按 filter 检索。

### 关键方法建议
```plain
def get_vector_store():
    ...

def add_documents(documents: list[Document]) -> None:
    ...

def similarity_search(query: str, k: int, filters: dict | None = None) -> list[Document]:
    ...
```

### 设计原则
1.  Collection 名称固定为 `freight_knowledge`，与你现有设计一致。
2.  filter 来自 query analyzer，而不是 vector store 自己猜。 
3.  允许 `filters=None`，以支持兜底无过滤检索。 

---

## rag/bm25_store.py
### 职责
提供关键词检索能力，用于弥补向量检索对缩写、术语、文件名、表单名命中的不足。

### 为什么需要 BM25
你的资料里有大量术语和强关键词：

+  锂电池 
+  PI967 / PI968 
+  ACCOS 
+  分单件数 
+  授权委托书 
+  报关品名清单 

这类词很多时候 BM25 比纯向量更稳定，因此“向量 + BM25”是合理路线。这个混合方案来自你的既定技术决策。

### 实现建议
+  索引源直接复用切分后的 chunk 
+  索引落盘到 `data/cache/bm25.pkl`
+  检索返回 chunk 与简单分数 

---

## rag/indexer.py
### 职责
完成知识库初始化和重建，是 RAG 的离线入库主流程。

### 主流程
```plain
扫描 data/docs
  ↓
读取 filename 对应 metadata
  ↓
loaders 解析
  ↓
cleaner 清洗
  ↓
splitter 切分
  ↓
embedding
  ↓
写入 Chroma
  ↓
构建 BM25 索引
```

### 对外接口建议
```plain
def index_document(filepath: str, metadata: dict) -> int:
    ...

def build_knowledge_base() -> dict:
    ...

def rebuild_knowledge_base() -> dict:
    ...
```

### 入库原则
1.  入库前先校验 metadata 是否存在。 
2.  默认按“全量重建”实现，先求稳定。 
3.  后续再考虑“单文件增量更新”“先删后加”。 

### 更新策略建议
虽然当前只有 8 个文件，但为了以后扩展，建议从第一版开始就采用“同源文件先删后加”的思想：

+  用 `source_file` 作为主标识 
+  rebuild 时清空 Collection 后重新导入 
+  若后续做增量更新，则先删除 `source_file == xxx` 的所有 chunk，再重新写入 

这与你过往关注的“先删后加”更新逻辑是一致的工程思路。

---

## rag/query_analyzer.py
### 职责
把用户自然语言问题转成检索系统可执行的结构化检索请求。

### 输入
```plain
锂电池货物需要什么声明文件？
```

### 输出
```plain
{
  "query": "锂电池 声明 文件",
  "filters": {
    "category": "dangerous_goods",
    "sub_category": "lithium_battery"
  }
}
```

### 为什么必须有这一层
如果没有 query analyzer，RAG 只能“裸搜”，无法把 metadata 真正用起来。你给的示例已经说明 metadata 检索的价值，但示例里的 `filter={...}` 只是理想调用，工程上必须有一个模块去产生它。





## rag/vector_store.py
### 职责
负责 Chroma 持久化目录初始化、Collection 获取、文档写入、按 filter 检索。

### 关键方法建议
```plain
def get_vector_store():
    ...

def add_documents(documents: list[Document]) -> None:
    ...

def similarity_search(query: str, k: int, filters: dict | None = None) -> list[Document]:
    ...
```

### 设计原则
1.  Collection 名称固定为 `freight_knowledge`，与你现有设计一致。
2.  filter 来自 query analyzer，而不是 vector store 自己猜。 
3.  允许 `filters=None`，以支持兜底无过滤检索。 

---

## rag/bm25_store.py
### 职责
提供关键词检索能力，用于弥补向量检索对缩写、术语、文件名、表单名命中的不足。

### 为什么需要 BM25
你的资料里有大量术语和强关键词：

+  锂电池 
+  PI967 / PI968 
+  ACCOS 
+  分单件数 
+  授权委托书 
+  报关品名清单 

这类词很多时候 BM25 比纯向量更稳定，因此“向量 + BM25”是合理路线。这个混合方案来自你的既定技术决策。

### 实现建议
+  索引源直接复用切分后的 chunk 
+  索引落盘到 `data/cache/bm25.pkl`
+  检索返回 chunk 与简单分数 

---

## rag/indexer.py
### 职责
完成知识库初始化和重建，是 RAG 的离线入库主流程。

### 主流程
```plain
扫描 data/docs
  ↓
读取 filename 对应 metadata
  ↓
loaders 解析
  ↓
cleaner 清洗
  ↓
splitter 切分
  ↓
embedding
  ↓
写入 Chroma
  ↓
构建 BM25 索引
```

### 对外接口建议
```plain
def index_document(filepath: str, metadata: dict) -> int:
    ...

def build_knowledge_base() -> dict:
    ...

def rebuild_knowledge_base() -> dict:
    ...
```

### 入库原则
1.  入库前先校验 metadata 是否存在。 
2.  默认按“全量重建”实现，先求稳定。 
3.  后续再考虑“单文件增量更新”“先删后加”。 

### 更新策略建议
虽然当前只有 8 个文件，但为了以后扩展，建议从第一版开始就采用“同源文件先删后加”的思想：

+  用 `source_file` 作为主标识 
+  rebuild 时清空 Collection 后重新导入 
+  若后续做增量更新，则先删除 `source_file == xxx` 的所有 chunk，再重新写入 

这与你过往关注的“先删后加”更新逻辑是一致的工程思路。

---

## rag/query_analyzer.py
### 职责
把用户自然语言问题转成检索系统可执行的结构化检索请求。

### 输入
```plain
锂电池货物需要什么声明文件？
```

### 输出
```plain
{
  "query": "锂电池 声明 文件",
  "filters": {
    "category": "dangerous_goods",
    "sub_category": "lithium_battery"
  }
}
```

### 为什么必须有这一层
如果没有 query analyzer，RAG 只能“裸搜”，无法把 metadata 真正用起来。你给的示例已经说明 metadata 检索的价值，但示例里的 `filter={...}` 只是理想调用，工程上必须有一个模块去产生它。



### 第一版建议
第一版不要把这里做得太复杂，采用“两段式”：

#### 1. 规则优先
根据关键词快速产出 filter，例如：

+  包含“锂电池”“危险品” → `category=dangerous_goods`
+  包含“ACCOS”“分单” → `category=operations`
+  包含“普货”“不带电”“委托书” → `category=general_cargo`
+  包含“报关”“品名清单”“上海口岸” → `category=customs`

#### 2. LLM 补充
当规则无法确定或命中多个方向时，再用 LLM 生成 `query + filters`。

### 这样做的原因
+  更稳 
+  更可控 
+  更容易排查 
+  更适合当前 8 个文件的小规模知识库 

---

## rag/retriever.py
### 职责
实现 Hybrid Retrieval，把向量检索与 BM25 结果合并，必要时进入 reranker，再返回最终 TopK 文档。

### 主流程
```plain
输入 question / retrieval_query / filters
  ↓
向量检索 TopK
  ↓
BM25 检索 TopK
  ↓
merge 去重
  ↓
按简单得分策略融合
  ↓
可选 rerank
  ↓
输出 final docs
```

### 对外接口建议
```plain
def hybrid_retrieve(query: str, filters: dict | None = None) -> list[dict]:
    ...
```

### 关键策略
#### 1. 向量检索
+ `k = rag_top_k_vector`
+  支持 filter 
+  filter 无结果时允许 fallback 到无 filter 再搜一轮 

#### 2. BM25 检索
+ `k = rag_top_k_bm25`
+  若有 filter，先在 filter 后的候选集中跑 BM25，或先 BM25 再在 merge 阶段过滤，第一版可选择实现成本更低的方式 

#### 3. merge 去重
推荐去重键：

```plain
(source_file, chunk_index)
```

#### 4. 兜底策略
如果带 filter 没结果，必须自动退化为无 filter 检索一次。否则 metadata 一旦判错，就会直接空回答。



## rag/reranker.py
### 职责
这是重排接口层，第一版可以是空实现，但接口必须先定义好，避免后续改动太大。

### 建议接口
```plain
def rerank(query: str, docs: list[dict]) -> list[dict]:
    return docs
```

### 第一版策略
+  默认关闭 
+  配置项 `RAG_ENABLE_RERANK=false`
+  保证先上线，再优化 

### 原因
当前 8 个文件的规模下，真正的瓶颈并不一定在 rerank，而更可能在文档解析、切分、metadata、query analyzer。先把召回与回答做稳，比先上重排更重要。

---

## rag/prompts.py
### 职责
存放所有 RAG 相关提示词。

建议至少包括三类 Prompt：

1. `QUERY_ANALYZER_SYSTEM`
2. `RAG_ANSWER_SYSTEM`
3. `RAG_ANSWER_USER`

### Prompt 原则
1.  Query Analyzer 只做结构化输出，不要顺手回答用户问题 
2.  Generator 只基于检索结果回答，不允许编造文档中不存在的内容 
3.  如果检索结果不足，明确告诉用户“当前资料中未检索到明确依据” 

---

## rag/generator.py
### 职责
根据 `question + retrieved_docs` 生成最终业务回答。

### 输入
+  用户原问题 
+  检索到的文档片段 
+  关联 metadata 

### 输出
+  面向用户的自然语言回答 

### 回答要求
1.  先直接回答问题 
2.  再给出依据说明 
3.  如涉及表单、声明、委托书，要说明适用对象 
4.  如有资料不足，明确边界 
5.  不编造未检索到的政策、流程、费用、限制条件 

### 是否返回引用
第一版建议在内部保留 `source_file`，但不一定要前端直接展示。先保证回答正确，再决定是否把文档来源展示给用户。

---

## rag/service.py
### 职责
作为 RAG 的对外服务编排层，把 query analyzer、retriever、generator 串起来，向 `graph/nodes.py` 提供一个统一调用方法。

### 建议接口
```plain
def query_knowledge_base(question: str) -> str:
    ...
```

### 内部流程
```plain
question
  ↓
analyze_query
  ↓
hybrid_retrieve
  ↓
generate_answer
  ↓
return answer
```

---

## rag/**init**.py
### 职责
对外暴露统一方法，供 `graph/nodes.py` 或脚本调用。

建议内容：

```plain
from .service import query_knowledge_base
from .indexer import build_knowledge_base, rebuild_knowledge_base
```

这样外部模块只需要：

```plain
from rag import query_knowledge_base
```

---

## graph/state.py（RAG 扩展版）
在现有字段基础上，建议扩展为：

```plain
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]

    intent: str | None

    # 运价槽位
    sfg: str | None
    mdg: str | None
    inputWeight: float | None
    inputVol: float | None
    hbrq: str | None

    missing_slots: list[str]
    query_ready: bool

    api_result: dict | None
    api_error: str | None

    # RAG
    rag_query: str | None
    retrieval_query: str | None
    retrieval_filters: dict | None
    retrieved_docs: list | None
    rag_answer: str | None
```

### 原则
1.  运价槽位状态与 RAG 状态分开 
2.  不要让 `retrieved_docs` 覆盖 `api_result`
3.  RAG 流程的中间状态应可观察、可打印、可调试 





## graph/prompts.py（保持现有，不混入 RAG Prompt）
现有内容保留：

+ `INTENT_SYSTEM`
+ `SLOT_SYSTEM`
+ `ASK_SYSTEM`
+ `RESULT_SYSTEM`
+ `FALLBACK_RESPONSES`

其中 `rate_query / rag / unknown` 三分类已经满足现阶段需求。

不建议把 RAG 的 analyzer / generator prompt 放进这里，避免 Prompt 文件无限膨胀，后续不好维护。

---

## graph/nodes.py（RAG 接入设计）
### 现有节点
+ `intent_node`
+ `slot_node`
+ `ask_node`
+ `tool_node`
+ `result_node`
+ `fallback_node`

### 建议新增节点
+ `rag_retrieve_node`
+ `rag_answer_node`

### 
### 方案
显式增加两个节点，便于调试：

#### rag_retrieve_node
职责：

+  读取用户最新问题 
+  调用 `query_analyzer`
+  调用 `hybrid_retrieve`
+  把结果写入 state 

#### rag_answer_node
职责：

+  调用 `generator`
+  生成最终回答 
+  将回答 append 到 `messages`

### 为什么推荐拆开
1.  检索和生成是两个不同步骤 
2.  更方便打印 query、filters、docs 
3.  后续接引用展示更容易 
4.  出问题时更好定位是“没搜到”还是“生成错了” 

---

## graph/agent.py（RAG 路由改造）
当前逻辑是：

```plain
intent == rate_query → slot
intent != rate_query → fallback
```

建议改为：

```plain
intent == rate_query → slot
intent == rag        → rag_retrieve
intent == unknown    → fallback
```

### 路由设计
```plain
def route_intent(state: AgentState) -> str:
    intent = state.get("intent")
    if intent == "rate_query":
        return "slot"
    if intent == "rag":
        return "rag_retrieve"
    return "fallback"
```

后续：

```plain
rag_retrieve → rag_answer → END
```

---

## main.py（保持接口协议不变）
`main.py` 当前职责正确，不需要因为 RAG 接入而修改请求体和返回体协议。请求依旧是：

```plain
{
  "session_id": "...",
  "message": "...",
  "context": {...}
}
```

响应依旧是 SSE，支持：

+ `text`
+ `context`
+ `done`
+ `error`

### 需要注意的点
1. `context` 当前主要用于运价槽位记忆 
2.  RAG 第一版不要求把检索状态回传给前端 
3.  因此 `context` 机制保持不变，不要为了 RAG 增加复杂字段



## 知识库初始化脚本
建议新增：

```plain
scripts/init_kb.py
scripts/rebuild_kb.py
```

### init_kb.py 职责
+  读取 `data/docs/`
+  校验每个文件在 `DOCUMENT_METADATA` 中都有配置 
+  调用 `build_knowledge_base()`

### rebuild_kb.py 职责
+  删除旧 Chroma 数据 
+  删除旧 BM25 索引缓存 
+  重新执行全量入库 

### 典型命令
```plain
python scripts/init_kb.py
python scripts/rebuild_kb.py
```

---

## 测试
## 一、运价查询回归测试
RAG 接入前后，必须确保下面能力不退化：

1.  “上海到洛杉矶空运多少钱” → 追问重量 
2.  “500公斤” → 追问体积 
3.  “2个立方” → 追问日期 
4.  “越快越好” → 返回报价 
5.  一次性提供全部参数 → 直接返回报价 

## 二、RAG 功能测试
建议至少覆盖：

1.  锂电池货物需要什么声明文件 
2.  锂电池托运人和销售代理人使用的表单是否相同 
3.  ACCOS 系统怎么录入分单件数 
4.  普货不带电授权委托书怎么填写 
5.  上海口岸空运出口报关品名清单是做什么用的 
6.  危险品授权委托书适用于哪些货物 

## 三、异常测试
1.  metadata 缺失 
2.  文档文件不存在 
3.  Chroma 初始化失败 
4.  embedding 接口失败 
5.  DeepSeek 回答失败 
6.  检索为空 

