# AI 运价 Agent Windows 云服务器部署指南

## 1. 部署目标

本文档基于当前项目真实实现整理，目标是在 Windows 云服务器上部署一个可运行的 `FastAPI + LangGraph` 服务，并保持以下约束不变：

- 对外接口仍然只有 `GET /health` 和 `POST /api/chat`
- `/api/chat` 仍然返回 `text/event-stream` SSE
- 前端仍然依赖服务端返回的 `context` 做多轮追问
- 运价查询链路与 RAG 链路共用同一个接口，不改协议

当前代码入口见 [main.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\main.py)，路由编排见 [graph/agent.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\agent.py)，配置项见 [config.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\config.py)。

## 2. 部署前提

### 2.1 服务器基础要求

- 操作系统：Windows Server 2019 / 2022
- Python：3.11 及以上
- CPU / 内存：建议至少 2 核 4G，若要跑向量检索建议 4 核 8G
- 磁盘：至少预留 5G，知识库文件和 Chroma 索引会写入本地磁盘
- 网络：
  - 必须能访问 DeepSeek API
  - 如果开启向量检索，必须能访问阿里云百炼 Embedding 接口
  - 必须能访问运价接口 `FREIGHT_API_BASE`

### 2.2 关键风险先说明

部署到云服务器之前，先确认下面这件事，否则服务可能能启动，但运价查询一定失败：

- 当前项目默认运价接口是内网地址，例如 `http://192.168.0.186:9000`
- 如果你的 Windows 云服务器不在同一内网、专线或 VPN 中，这个地址无法访问
- 结果会表现为：
  - `/health` 正常
  - 闲聊和 RAG 可能正常
  - 运价查询请求在工具调用阶段超时或报错

建议在正式部署前，先单独验证云服务器是否能连通目标运价接口。

## 3. 项目结构和运行方式

当前项目已经具备以下运行要素：

- Web 服务入口：`main.py`
- 依赖清单：`requirements.txt`
- 配置入口：`config.py`
- RAG 建库脚本：
  - `scripts/init_kb.py`
  - `scripts/rebuild_kb.py`
- 知识库目录：
  - 原始文档：`data/docs`
  - Chroma 索引：`data/chroma`
  - BM25 缓存：`data/cache`
  - Chunk 导出：`data/exports`

生产环境推荐启动方式：

```bat
python -m uvicorn main:app --host 0.0.0.0 --port 8082
```

不要在生产环境使用 `--reload`。

## 4. 服务器初始化

### 4.1 创建部署目录

建议在服务器上统一放到一个固定目录，例如：

```text
D:\apps\freight-agent
```

### 4.2 安装 Python

安装 Python 3.11+，并确保以下命令可用：

```bat
python --version
pip --version
```

建议勾选：

- `Add python.exe to PATH`
- `Install for all users`

### 4.3 上传项目文件

将本项目完整上传到服务器，至少包含：

- `main.py`
- `config.py`
- `graph/`
- `tools/`
- `rag/`
- `scripts/`
- `requirements.txt`
- `data/docs/` 内的业务资料

如果你打算在服务器上重建知识库，可以不上传 `data/chroma/` 和 `data/cache/`，因为它们可以重新生成。

## 5. 创建虚拟环境并安装依赖

进入项目目录后执行：

```bat
cd /d D:\apps\freight-agent
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

当前项目依赖来自 [requirements.txt](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\requirements.txt)，包括：

- FastAPI / Uvicorn
- LangChain / LangGraph
- httpx / sse-starlette
- chromadb / rank-bm25
- python-docx / python-pptx / pypdf / pdfplumber

如果你直接复用仓库里已经存在的 `AiEnv`，理论上也能启动，但不建议这样做。部署环境应在服务器上独立创建虚拟环境，避免把本地开发环境一并带上去。

## 6. 配置环境变量

项目通过 [config.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\config.py) 从 `.env` 读取配置。你需要在服务器根目录创建 `.env` 文件。

### 6.1 推荐 `.env` 模板

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

FREIGHT_API_BASE=http://192.168.0.186:9000

NO_PROXY=192.168.0.0/16,127.0.0.1,localhost

DASHSCOPE_API_KEY=your_dashscope_api_key
EMBEDDING_MODEL=qwen3-vl-embedding

CHROMA_PERSIST_DIR=./data/chroma
CHROMA_COLLECTION_NAME=freight_knowledge

RAG_ENABLE_VECTOR_SEARCH=false
RAG_TOP_K_VECTOR=8
RAG_TOP_K_BM25=8
RAG_TOP_K_FINAL=4
RAG_CHUNK_SIZE=500
RAG_CHUNK_OVERLAP=100
RAG_ENABLE_RERANK=false
RAG_VECTOR_SEARCH_TIMEOUT_SECONDS=8
RAG_DOCS_DIR=./data/docs
```

### 6.2 配置说明

- `DEEPSEEK_API_KEY`
  - 必填
  - 用于意图识别、槽位提取、追问、结果语义化和 RAG 生成
- `FREIGHT_API_BASE`
  - 必填
  - 指向运价查询后端接口
- `NO_PROXY`
  - 强烈建议配置
  - 当前代码在 [main.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\main.py) 中默认设置了 `192.168.0.0/16,127.0.0.1,localhost`
  - 如果服务器环境存在代理，不配置会导致本地地址和内网地址错误地走代理
- `DASHSCOPE_API_KEY`
  - 只有在启用向量检索时需要
- `RAG_ENABLE_VECTOR_SEARCH`
  - 当前默认建议先保持 `false`
  - 这样 RAG 可以先走 BM25，先保证部署稳定
  - 等你确认百炼 Embedding 可用后，再改为 `true`

## 7. 初始化 RAG 知识库

### 7.1 准备文档

将业务资料放到：

```text
data/docs/
```

当前代码会从 `RAG_DOCS_DIR` 指向的目录扫描文件，并根据 [rag/metadata.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\metadata.py) 中的配置做入库。

### 7.2 首次建库

激活虚拟环境后执行：

```bat
cd /d D:\apps\freight-agent
.venv\Scripts\activate
python scripts\init_kb.py
```

脚本入口见 [scripts/init_kb.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\scripts\init_kb.py)，最终会调用 `build_knowledge_base()`。

建库完成后，通常会生成：

- `data/chroma/`
- `data/cache/bm25.pkl`
- `data/exports/chunks.json`

### 7.3 重建知识库

如果你更新了 `data/docs/` 中的文件，建议直接全量重建：

```bat
python scripts\rebuild_kb.py
```

脚本入口见 [scripts/rebuild_kb.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\scripts\rebuild_kb.py)。

## 8. 启动服务

### 8.1 前台启动

在服务器上先用前台命令确认服务能正常启动：

```bat
cd /d D:\apps\freight-agent
.venv\Scripts\activate
python -m uvicorn main:app --host 0.0.0.0 --port 8082
```

说明：

- `0.0.0.0` 表示允许局域网或公网访问
- `8082` 是当前文档和示例里统一使用的端口
- 生产环境不要加 `--reload`

### 8.2 开放 Windows 防火墙端口

如果外部要访问 8082，需要放行入站规则。可以用图形界面添加，也可以执行：

```bat
netsh advfirewall firewall add rule name="freight-agent-8082" dir=in action=allow protocol=TCP localport=8082
```

### 8.3 健康检查

服务启动后先验证：

```bat
curl http://127.0.0.1:8082/health
```

预期返回：

```json
{"status":"ok"}
```

如果云厂商安全组也在拦截，还需要在云控制台额外放行 `8082/TCP`。

## 9. 验证聊天接口

### 9.1 本机验证

```bat
curl -X POST http://127.0.0.1:8082/api/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"session_id\":\"deploy-test-001\",\"message\":\"上海到洛杉矶空运多少钱\",\"context\":null}"
```

预期行为：

- 返回 `text/event-stream`
- `data:` 事件里先逐字返回文本
- 最后返回 `context`
- 最后返回 `done`

### 9.2 PowerShell 验证

如果服务器使用 PowerShell，更容易测试 JSON 请求：

```powershell
$body = @{
  session_id = "deploy-test-001"
  message = "上海到洛杉矶空运多少钱"
  context = $null
} | ConvertTo-Json -Depth 5

Invoke-WebRequest `
  -Uri "http://127.0.0.1:8082/api/chat" `
  -Method POST `
  -ContentType "application/json" `
  -Body $body
```

注意：`Invoke-WebRequest` 更适合验证能否返回内容，不适合完整观察 SSE 流式消费过程。前端联调时仍应以浏览器或实际客户端为准。

## 10. 配置开机自启

Windows 上可选几种方式，这里给出最稳妥的思路。

### 10.1 推荐方式：NSSM 注册为 Windows 服务

如果你允许在服务器上安装一个很轻量的服务管理工具，推荐使用 NSSM。

示例思路：

- `Application path` 指向：`D:\apps\freight-agent\.venv\Scripts\python.exe`
- `Arguments` 填：`-m uvicorn main:app --host 0.0.0.0 --port 8082`
- `Startup directory` 填：`D:\apps\freight-agent`

环境变量里补上：

```text
NO_PROXY=192.168.0.0/16,127.0.0.1,localhost
```

这样做的好处：

- 开机自动拉起
- 崩溃后便于自动重启
- 不依赖登录用户手工启动

### 10.2 备选方式：任务计划程序

如果你不想额外装 NSSM，可以用“任务计划程序”创建一个“开机时执行”的任务，执行内容类似：

```bat
D:\apps\freight-agent\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8082
```

启动目录设置为：

```text
D:\apps\freight-agent
```

这一方式能用，但进程守护和故障恢复能力比 Windows 服务弱。

## 11. 反向代理建议

如果要正式对公网开放，建议不要直接裸露 Uvicorn 端口。更稳妥的方式是：

- 云安全组只开放 `80/443`
- 用 IIS + ARR 或 Nginx for Windows 做反向代理
- 后端 Uvicorn 继续监听 `127.0.0.1:8082` 或内网地址

注意两点：

- 反向代理必须允许 `text/event-stream`
- 不能缓冲 SSE 响应，否则前端会感觉“卡住不返回”

如果你只是内网试运行，直接放行 `8082` 也可以。

## 12. 日志与排障

当前项目在 [main.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\main.py) 和多个节点里已经用了 `logging`。默认日志会输出到控制台。

建议生产环境至少做两件事：

- 启动命令重定向标准输出和错误输出到日志文件
- 保留最近几天的日志，便于排查运价接口超时、RAG 建库失败或模型调用失败

如果先用任务计划程序，可以把输出重定向到文件，例如：

```bat
python -m uvicorn main:app --host 0.0.0.0 --port 8082 >> logs\server.log 2>&1
```

前提是先创建 `logs/` 目录。

## 13. 上线后建议验证清单

按顺序验证，不要跳步：

1. `python --version`
2. `pip install -r requirements.txt`
3. `.env` 是否填写完整
4. `curl http://127.0.0.1:8082/health`
5. 运价接口地址从服务器是否可达
6. `python scripts\init_kb.py`
7. `POST /api/chat` 是否能正常返回 SSE
8. 前端是否正确接收 `context`

## 14. 典型故障与处理

### 14.1 `/health` 正常，但运价查询失败

优先检查：

- `FREIGHT_API_BASE` 是否正确
- 云服务器是否能访问该地址
- 是否需要配置 `NO_PROXY`

### 14.2 RAG 问答总是答非所问

优先检查：

- `data/docs/` 是否上传完整
- 是否执行过 `python scripts\init_kb.py`
- `data/cache/bm25.pkl` 是否生成
- `data/exports/chunks.json` 是否有内容

### 14.3 开启向量检索后报错

优先检查：

- `DASHSCOPE_API_KEY` 是否配置
- 服务器是否能访问百炼接口
- `RAG_ENABLE_VECTOR_SEARCH` 是否已经设为 `true`

注意：当前实现里如果向量检索多次失败，会自动退化为不走向量检索。这种情况下服务未必会挂，但召回质量会下降。

### 14.4 前端收不到流式输出

优先检查：

- 代理层是否支持 SSE
- 是否错误地做了响应缓冲
- 前端是否按 `data:` 行解析事件

## 15. 推荐上线顺序

推荐按这个顺序推进，风险最低：

1. 先在服务器本机用前台命令跑通
2. 验证 `/health`
3. 验证运价接口连通
4. 初始化 RAG 知识库
5. 验证 `/api/chat` 返回 SSE
6. 再做开机自启
7. 最后再接反向代理和公网入口

## 16. 结论

这个项目在 Windows 云服务器上可以直接部署，核心依赖条件不是框架本身，而是外部依赖是否通：

- DeepSeek 必须可访问
- 运价接口必须可访问
- 如果启用向量检索，百炼 Embedding 必须可访问

只要这三类依赖链路打通，当前代码结构已经足够支撑上线试运行。
