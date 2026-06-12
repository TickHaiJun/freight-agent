# AI 运价 Agent 项目配置说明

## 1. 结论先说

DeepSeek Key 和向量模型 Key 这类敏感信息，应该写在 `.env`，不应该写死在 `config.py`。

职责边界如下：

- `config.py`：定义配置项名称、类型、默认值、读取入口。
- `.env`：填写当前机器真实使用的密钥、接口地址、目录路径、开关参数。

原因很简单：

- API Key 属于敏感信息，放进 `config.py` 容易被提交到 Git。
- `config.py` 应该是“配置结构”，不是“配置内容”。
- `.env` 更适合不同环境切换，比如本地开发、测试机、生产机分别使用不同 Key。

## 2. 当前项目的配置读取方式

项目当前已经实现了统一配置入口，代码在 [config.py](/D:/CompanyPlace/AI/AiFreightRate/freight-agent/config.py)。

当前逻辑是：

```python
class Settings(BaseSettings):
    ...
    class Config:
        env_file = ".env"
```

这表示程序启动时会自动从根目录 `.env` 读取环境变量，然后映射到 `Settings` 字段中。

所以正确做法不是把 Key 写进 `config.py`，而是：

1. 在 `config.py` 中保留字段定义。
2. 在 `.env` 中填写真实值。

## 3. config.py 应该怎么理解

`config.py` 不负责保存真实密钥，只负责声明“系统需要哪些配置”。

当前项目已经有这些字段：

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    freight_api_base: str
    dashscope_api_key: str | None = None
    embedding_model: str = "qwen3-vl-embedding"
    chroma_persist_dir: str = "./data/chroma"
    chroma_collection_name: str = "freight_knowledge"
    rag_top_k_vector: int = 8
    rag_top_k_bm25: int = 8
    rag_top_k_final: int = 4
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 100
    rag_enable_rerank: bool = False
    rag_docs_dir: str = "./data/docs"

    class Config:
        env_file = ".env"


settings = Settings()
```

各字段含义如下：

- `deepseek_api_key`：DeepSeek 大模型调用 Key。
- `deepseek_base_url`：DeepSeek 接口地址，默认是官方地址。
- `deepseek_model`：DeepSeek 聊天模型名。
- `freight_api_base`：现有空运报价接口地址。
- `dashscope_api_key`：阿里云百炼 Key，用于 embedding。
- `embedding_model`：向量模型名称，当前默认是 `qwen3-vl-embedding`。
- `chroma_persist_dir`：Chroma 本地持久化目录。
- `chroma_collection_name`：知识库 Collection 名称。
- `rag_top_k_vector`：向量检索召回数量。
- `rag_top_k_bm25`：BM25 检索召回数量。
- `rag_top_k_final`：混合召回后的最终保留数量。
- `rag_chunk_size`：文档切分大小。
- `rag_chunk_overlap`：文档切分重叠长度。
- `rag_enable_rerank`：是否启用 rerank，当前建议默认关闭。
- `rag_docs_dir`：离线入库时扫描的原始文档目录。

## 4. .env 推荐写法

下面是推荐的 `.env` 示例。真实项目中，密钥写在 `.env`，不要提交到 Git。

```env
# =========================
# LLM 配置：DeepSeek
# =========================

# DeepSeek API Key
# 用于意图识别、槽位提取、结果语义化、RAG 回答生成
DEEPSEEK_API_KEY=你的_deepseek_key

# DeepSeek 接口地址
# 默认官方地址，一般不需要改
DEEPSEEK_BASE_URL=https://api.deepseek.com

# DeepSeek 模型名
# 当前项目默认使用 deepseek-chat
DEEPSEEK_MODEL=deepseek-chat


# =========================
# 运价接口配置
# =========================

# 空运报价后端接口地址
# 现有运价查询链路依赖该地址
FREIGHT_API_BASE=http://192.168.0.186:9000


# =========================
# Embedding 配置：阿里云百炼
# =========================

# 百炼 API Key
# 用于向量化业务文档和用户问题
DASHSCOPE_API_KEY=你的_dashscope_key

# 向量模型名称
# 当前计划使用 qwen3-vl-embedding
EMBEDDING_MODEL=qwen3-vl-embedding


# =========================
# Chroma 向量库配置
# =========================

# Chroma 本地持久化目录
# 离线入库后会在这里保存向量索引
CHROMA_PERSIST_DIR=./data/chroma

# Chroma Collection 名称
# 当前项目建议统一使用一个 collection
CHROMA_COLLECTION_NAME=freight_knowledge


# =========================
# RAG 检索参数
# =========================

# 向量检索召回数量
RAG_TOP_K_VECTOR=8

# BM25 检索召回数量
RAG_TOP_K_BM25=8

# 混合检索后最终保留数量
RAG_TOP_K_FINAL=4

# 文档切分大小
RAG_CHUNK_SIZE=500

# 文档切分重叠长度
RAG_CHUNK_OVERLAP=100

# 是否启用 rerank
# 第一版建议 false，先把主流程跑通
RAG_ENABLE_RERANK=false


# =========================
# 文档目录配置
# =========================

# 原始业务文档目录
# 离线入库脚本会从这里读取 PDF / DOCX / PPTX
RAG_DOCS_DIR=./data/docs


# =========================
# 网络代理绕过配置
# =========================

# 避免访问本地服务和内网运价接口时走代理
NO_PROXY=192.168.0.186,127.0.0.1,localhost
```

## 5. 每个配置应该写在哪

可以直接按下面规则判断：

### 应该写在 `config.py` 的内容

- 配置字段名。
- 配置类型。
- 默认值。
- 配置文件读取方式。

例如：

- `deepseek_model` 默认 `deepseek-chat`
- `embedding_model` 默认 `qwen3-vl-embedding`
- `rag_top_k_final` 默认 `4`

### 应该写在 `.env` 的内容

- 所有真实 API Key。
- 不同环境可能变化的地址。
- 当前机器使用的目录路径。
- 运行参数开关。

例如：

- `DEEPSEEK_API_KEY`
- `DASHSCOPE_API_KEY`
- `FREIGHT_API_BASE`
- `CHROMA_PERSIST_DIR`

## 6. 启动前准备

### 6.1 进入项目目录

```cmd
cd /d D:\CompanyPlace\AI\AiFreightRate\freight-agent
```

### 6.2 激活虚拟环境

```cmd
AiEnv\Scripts\activate
```

### 6.3 安装依赖

如果是第一次启动，先安装依赖：

```cmd
pip install -r requirements.txt
```

当前 [requirements.txt](/D:/CompanyPlace/AI/AiFreightRate/freight-agent/requirements.txt) 已包含：

- FastAPI 与 SSE 服务依赖
- LangGraph / LangChain
- Chroma
- BM25
- PDF / DOCX / PPTX 解析依赖

### 6.4 准备 `.env`

根目录已存在 `.env`，但当前内容只包含 DeepSeek 与运价接口配置，缺少向量模型 Key。

你需要至少补齐：

```env
DASHSCOPE_API_KEY=你的_dashscope_key
EMBEDDING_MODEL=qwen3-vl-embedding
CHROMA_PERSIST_DIR=./data/chroma
CHROMA_COLLECTION_NAME=freight_knowledge
RAG_TOP_K_VECTOR=8
RAG_TOP_K_BM25=8
RAG_TOP_K_FINAL=4
RAG_CHUNK_SIZE=500
RAG_CHUNK_OVERLAP=100
RAG_ENABLE_RERANK=false
RAG_DOCS_DIR=./data/docs
NO_PROXY=192.168.0.186,127.0.0.1,localhost
```

### 6.5 准备业务文档

离线入库前，确认知识库源文件已经放到：

[`data/docs`](/D:/CompanyPlace/AI/AiFreightRate/freight-agent/data/docs)

支持的类型按当前设计为：

- PDF
- DOCX
- PPTX

## 7. 在线服务启动

### 7.1 Windows CMD 启动

```cmd
set NO_PROXY=192.168.0.186,127.0.0.1,localhost && uvicorn main:app --host 127.0.0.1 --port 8082 --reload
```

### 7.2 Windows PowerShell 启动

```powershell
$env:NO_PROXY="192.168.0.186,127.0.0.1,localhost"; uvicorn main:app --host 127.0.0.1 --port 8082 --reload
```

### 7.3 启动成功验证

```cmd
curl http://127.0.0.1:8082/health
```

期望返回：

```json
{"status":"ok"}
```

### 7.4 为什么还要写 `NO_PROXY`

虽然 [main.py](/D:/CompanyPlace/AI/AiFreightRate/freight-agent/main.py) 中已经有：

```python
os.environ.setdefault("NO_PROXY", "192.168.0.0/16,127.0.0.1,localhost")
```

但为了避免本机代理设置影响 `curl`、测试脚本、外部客户端，仍建议在启动命令或系统环境变量中显式设置 `NO_PROXY`。

## 8. 离线入库启动

当前项目已经有 3 个直接可用脚本：

- [scripts/init_kb.py](/D:/CompanyPlace/AI/AiFreightRate/freight-agent/scripts/init_kb.py)
- [scripts/rebuild_kb.py](/D:/CompanyPlace/AI/AiFreightRate/freight-agent/scripts/rebuild_kb.py)
- [scripts/test_rag.py](/D:/CompanyPlace/AI/AiFreightRate/freight-agent/scripts/test_rag.py)

### 8.1 首次初始化知识库

适用场景：

- 第一次做离线入库。
- `data/chroma` 目录还没有索引。

命令：

```cmd
python scripts\init_kb.py
```

这个脚本会调用：

```python
from rag import build_knowledge_base
```

也就是走 [rag\indexer.py](/D:/CompanyPlace/AI/AiFreightRate/freight-agent/rag/indexer.py) 的全量构建流程。

### 8.2 重建知识库

适用场景：

- 新增或替换了业务文档。
- 修改了 metadata。
- 调整了 chunk 参数。
- 需要重建 Chroma / BM25 索引。

命令：

```cmd
python scripts\rebuild_kb.py
```

这个脚本会调用：

```python
from rag import rebuild_knowledge_base
```

### 8.3 单独验证 RAG 问答链路

命令：

```cmd
python scripts\test_rag.py
```

当前脚本会直接执行：

```python
query_knowledge_base("锂电池货物需要什么声明文件？")
```

这个命令适合快速确认：

- embedding 配置是否生效
- 检索链路是否能跑通
- 生成回答是否返回正常文本

## 9. 测试命令

当前仓库里存在 3 个 `unittest` 测试文件：

- [tests\test_rag_cleaner.py](/D:/CompanyPlace/AI/AiFreightRate/freight-agent/tests/test_rag_cleaner.py)
- [tests\test_rag_query_analyzer.py](/D:/CompanyPlace/AI/AiFreightRate/freight-agent/tests/test_rag_query_analyzer.py)
- [tests\test_rag_service.py](/D:/CompanyPlace/AI/AiFreightRate/freight-agent/tests/test_rag_service.py)

### 9.1 跑单个测试

```cmd
python -m unittest tests.test_rag_cleaner
python -m unittest tests.test_rag_query_analyzer
python -m unittest tests.test_rag_service
```

### 9.2 一次性跑全部测试

```cmd
python -m unittest discover -s tests -p "test_*.py"
```

### 9.3 服务联调测试

启动服务后可以再手动验证接口：

```cmd
curl http://127.0.0.1:8082/health
```

```cmd
curl -X POST http://127.0.0.1:8082/api/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"session_id\":\"test001\",\"message\":\"上海到洛杉矶，500公斤，2个立方，明天发货，查空运价格\",\"context\":null}"
```

如果是 RAG 问题联调，可以发送：

```cmd
curl -X POST http://127.0.0.1:8082/api/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"session_id\":\"rag001\",\"message\":\"锂电池货物需要什么声明文件？\",\"context\":null}"
```

## 10. 推荐启动顺序

推荐按这个顺序操作：

1. 补齐 `.env` 中的 DeepSeek 与 DashScope 配置。
2. 确认业务文档已经放到 `data/docs`。
3. 激活虚拟环境并安装依赖。
4. 执行 `python scripts\init_kb.py` 做首次离线入库。
5. 执行 `python -m unittest discover -s tests -p "test_*.py"` 跑基础测试。
6. 启动服务 `uvicorn main:app --host 127.0.0.1 --port 8082 --reload`。
7. 用 `curl` 或前端页面联调 `/api/chat`。

## 11. 常见问题

### 11.1 为什么我已经在 `config.py` 写了 Key，程序还是不推荐这样做

因为这会导致：

- 代码泄露密钥风险变高。
- 不同环境切换困难。
- 后续提交代码时容易把敏感信息带进版本库。

正确做法仍然是：

- `config.py` 只声明字段。
- `.env` 填真实值。

### 11.2 `DASHSCOPE_API_KEY` 不填会怎样

当前 `config.py` 里 `dashscope_api_key` 虽然声明为可选，但只要你要运行 RAG 的 embedding、离线入库或检索，就必须提供真实 Key。否则 RAG 链路无法正常工作。

### 11.3 离线入库和在线服务能不能分开

可以，而且建议分开理解：

- 离线入库：负责构建知识库索引。
- 在线服务：负责接收 `/api/chat` 请求并执行 Agent 流程。

先做离线入库，再启动在线服务，是更稳妥的操作方式。

### 11.4 哪些配置改了以后必须重建知识库

以下配置变更后，建议执行 `python scripts\rebuild_kb.py`：

- `EMBEDDING_MODEL`
- `CHROMA_COLLECTION_NAME`
- `RAG_CHUNK_SIZE`
- `RAG_CHUNK_OVERLAP`
- 文档原始内容
- metadata 配置

## 12. 一份可直接参考的最小配置

如果你现在只是想尽快跑起来，至少保证 `.env` 包含以下内容：

```env
DEEPSEEK_API_KEY=你的_deepseek_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
FREIGHT_API_BASE=http://192.168.0.186:9000

DASHSCOPE_API_KEY=你的_dashscope_key
EMBEDDING_MODEL=qwen3-vl-embedding

CHROMA_PERSIST_DIR=./data/chroma
CHROMA_COLLECTION_NAME=freight_knowledge
RAG_TOP_K_VECTOR=8
RAG_TOP_K_BM25=8
RAG_TOP_K_FINAL=4
RAG_CHUNK_SIZE=500
RAG_CHUNK_OVERLAP=100
RAG_ENABLE_RERANK=false
RAG_DOCS_DIR=./data/docs

NO_PROXY=192.168.0.186,127.0.0.1,localhost
```

然后按下面顺序执行：

```cmd
cd /d D:\CompanyPlace\AI\AiFreightRate\freight-agent
AiEnv\Scripts\activate
pip install -r requirements.txt
python scripts\init_kb.py
python -m unittest discover -s tests -p "test_*.py"
set NO_PROXY=192.168.0.186,127.0.0.1,localhost && uvicorn main:app --host 127.0.0.1 --port 8082 --reload
```
