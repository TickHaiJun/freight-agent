# RAG 三天执行 Checklist

## 固定样例

- [ ] 本次三天执行只使用这一个问题：
  - `锂电池货物需要什么声明文件？`

## 固定文件

- [ ] 打开 [main.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\main.py)
- [ ] 打开 [graph/agent.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\agent.py)
- [ ] 打开 [graph/nodes.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\nodes.py)
- [ ] 打开 [rag/query_analyzer.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\query_analyzer.py)
- [ ] 打开 [rag/retriever.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\retriever.py)
- [ ] 打开 [rag/generator.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\generator.py)
- [ ] 打开 [config.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\config.py)
- [ ] 打开 [scripts/test_rag.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\scripts\test_rag.py)
- [ ] 打开 [docs/rag_end_to_end_walkthrough.md](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\docs\rag_end_to_end_walkthrough.md)
- [ ] 打开 [docs/rag_learning_execution.md](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\docs\rag_learning_execution.md)

## 固定命令

- [ ] 激活环境

```cmd
cd D:\CompanyPlace\AIProject\AiFreightRate\freight-agent
AiEnv\Scripts\activate
```

- [ ] 启动服务

```cmd
set NO_PROXY=192.168.0.186,127.0.0.1,localhost && python -m uvicorn main:app --host 127.0.0.1 --port 8082 --reload
```

- [ ] 健康检查

```cmd
curl http://127.0.0.1:8082/health
```

- [ ] 跑 RAG 调试脚本

```cmd
python scripts\test_rag.py
```

- [ ] 跑接口样例

```cmd
curl -X POST http://127.0.0.1:8082/api/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"session_id\":\"rag_day_exec\",\"message\":\"锂电池货物需要什么声明文件？\",\"context\":null}"
```


## 第一天 Checklist

### 目标

- [ ] 只走通主链路
- [ ] 不做实验
- [ ] 不整理结论卡片

### Step 1 基础确认

- [ ] 服务启动成功
- [ ] `/health` 返回 `{"status":"ok"}`
- [ ] `python scripts\test_rag.py` 可执行
- [ ] `/api/chat` 可返回 SSE

### Step 2 API 入口

- [ ] 在 [main.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\main.py) 的 `generate()` 临时打印以下变量：
  - [ ] `request.session_id`
  - [ ] `request.message`
  - [ ] `request.context`
  - [ ] `initial_state`
  - [ ] `final_state.get("intent")`
  - [ ] `final_state.get("retrieval_query")`
  - [ ] `final_state.get("retrieval_filters")`
  - [ ] `len(final_state.get("retrieved_docs") or [])`
  - [ ] `final_state.get("rag_answer")`

- [ ] 观察到：
  - [ ] `initial_state["messages"]` 含 `HumanMessage`
  - [ ] RAG 字段初始为 `None`
  - [ ] `final_state["intent"] == "rag"`
  - [ ] `final_state["messages"]` 最后一条是 `AIMessage`

### Step 3 graph / intent 路由

- [ ] 在 [graph/nodes.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\nodes.py) 临时打印：
  - [ ] `intent_node` 的 `last_message`
  - [ ] `intent_node` 的 `response.content`
  - [ ] `intent_node` 的 `intent`
  - [ ] `route_intent` 的 `intent`
  - [ ] `rag_retrieve_node` 的 `question`
  - [ ] `rag_retrieve_node` 的 `analysis`
  - [ ] `rag_retrieve_node` 的 `len(docs)`
  - [ ] `rag_answer_node` 的 `len(state.get("retrieved_docs") or [])`
  - [ ] `rag_answer_node` 的 `answer`

- [ ] 观察到日志顺序：
  - [ ] `node intent finished`
  - [ ] `node rag_retrieve finished`
  - [ ] `node rag_answer finished`

- [ ] 确认：
  - [ ] 没有走 `slot`
  - [ ] 没有走 `ask`
  - [ ] 没有走 `tool`
  - [ ] 没有走 `result`
  - [ ] `route_intent` 返回的是 `rag_retrieve`

### Step 4 query_analyzer

- [ ] 在 [rag/query_analyzer.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\query_analyzer.py) 临时打印：
  - [ ] `question`
  - [ ] `rule_result`
  - [ ] `result`
  - [ ] `_rule_based_analysis` 命中标记
  - [ ] `_normalize_query` 的 `tokens`

- [ ] 执行：

```cmd
python -m unittest tests.test_rag_query_analyzer
```

- [ ] 观察到：
  - [ ] 命中危险品规则
  - [ ] `filters == {"category": "dangerous_goods"}`
  - [ ] 当前样例问题不需要走 `_call_llm`

### Step 5 retriever

- [ ] 在 [rag/retriever.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\retriever.py) 临时打印：
  - [ ] `query`
  - [ ] `filters`
  - [ ] `len(vector_results)`
  - [ ] `len(bm25_results)`
  - [ ] `len(docs)`
  - [ ] `docs[:2]`

- [ ] 在 [rag/bm25_store.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\bm25_store.py) 临时打印：
  - [ ] top 3 `score`
  - [ ] top 3 `metadata["source_file"]`

- [ ] 观察到：
  - [ ] 当前默认 `rag_enable_vector_search == False`
  - [ ] 当前默认主要靠 BM25
  - [ ] `final_docs > 0`
  - [ ] top docs 偏向危险品相关文件

### Step 6 generator

- [ ] 在 [rag/generator.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\generator.py) 临时打印：
  - [ ] `question`
  - [ ] `len(retrieved_docs)`
  - [ ] `_format_docs(retrieved_docs)`
  - [ ] `response.content`

- [ ] 观察到：
  - [ ] 非空 docs 时不走短路兜底
  - [ ] context 中包含来源与位置
  - [ ] 最终回答基于资料，不是闲聊兜底

### Step 7 response / SSE

- [ ] 在 [main.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\main.py) 临时打印：
  - [ ] `len(ai_messages)`
  - [ ] `content`
  - [ ] `context_data`

- [ ] 观察到：
  - [ ] SSE 有 `text`
  - [ ] SSE 有 `context`
  - [ ] SSE 有 `done`
  - [ ] `context` 只包含运价槽位
  - [ ] `context` 不包含 RAG 中间字段

### 第一天通过条件

- [ ] `scripts/test_rag.py` 跑通
- [ ] `/api/chat` 跑通
- [ ] 6 个站点都完成观察
- [ ] 已形成一份主链路记录

### 第一天记录模板

```md
日期：
样例问题：锂电池货物需要什么声明文件？

API 入口：
graph / intent：
query_analyzer：
retriever：
generator：
response / SSE：

今天卡点：
今天结论：
```


## 第二天 Checklist

### 目标

- [ ] 只做实验
- [ ] 不扩展第二个问题
- [ ] 每个实验结束立即回滚

### 实验 1 关闭规则 filter

- [ ] 修改 [rag/query_analyzer.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\query_analyzer.py)
- [ ] 仅对当前样例问题临时让规则失效
- [ ] 执行：

```cmd
python scripts\test_rag.py
```

- [ ] 再执行：

```cmd
curl -X POST http://127.0.0.1:8082/api/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"session_id\":\"rag_day_exp1\",\"message\":\"锂电池货物需要什么声明文件？\",\"context\":null}"
```

- [ ] 记录：
  - [ ] `retrieval_filters`
  - [ ] `final_docs`
  - [ ] top 3 `source_file`
  - [ ] 最终回答摘要

- [ ] 回滚修改

### 实验 2 开启向量检索

- [ ] 修改 [config.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\config.py)
- [ ] 仅改 `rag_enable_vector_search = True`
- [ ] 不改 `rag_enable_rerank`
- [ ] 先记录默认状态
- [ ] 再开启后执行：

```cmd
python scripts\test_rag.py
```

- [ ] 如需接口链路，再执行：

```cmd
curl -X POST http://127.0.0.1:8082/api/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"session_id\":\"rag_day_exp2\",\"message\":\"锂电池货物需要什么声明文件？\",\"context\":null}"
```

- [ ] 记录：
  - [ ] 默认 `vector_hits`
  - [ ] 开启后 `vector_hits`
  - [ ] 默认 `bm25_hits`
  - [ ] 开启后 `bm25_hits`
  - [ ] 默认 top 3 `source_file`
  - [ ] 开启后 top 3 `source_file`
  - [ ] 回答差异

- [ ] 回滚修改

### 实验 3 打印 generator context

- [ ] 修改 [rag/generator.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\generator.py)
- [ ] 临时打印 `_format_docs(retrieved_docs)`
- [ ] 执行：

```cmd
python scripts\test_rag.py
```

- [ ] 再执行：

```cmd
curl -X POST http://127.0.0.1:8082/api/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"session_id\":\"rag_day_exp3\",\"message\":\"锂电池货物需要什么声明文件？\",\"context\":null}"
```

- [ ] 记录：
  - [ ] context 长度
  - [ ] top 3 来源
  - [ ] context 是否明显相关
  - [ ] 答案是否明显偏移

- [ ] 回滚修改

### 第二天通过条件

- [ ] 3 个实验都执行完
- [ ] 3 个实验都已回滚
- [ ] 每个实验都有记录

### 第二天记录模板

```md
日期：

实验 1：
修改点：
现象：
结论：

实验 2：
修改点：
现象：
结论：

实验 3：
修改点：
现象：
结论：
```


## 第三天 Checklist

### 目标

- [ ] 不改代码
- [ ] 不再重跑实验
- [ ] 只沉淀决策卡片

### 需要完成的 6 张卡片

- [ ] 卡片 1：为什么先看 `intent`
- [ ] 卡片 2：为什么先看 `retrieval_filters`
- [ ] 卡片 3：为什么当前默认更像 BM25 主召回
- [ ] 卡片 4：为什么 generator 问题前先看 context
- [ ] 卡片 5：为什么 `/api/chat` 与 `scripts/test_rag.py` 要分开看
- [ ] 卡片 6：为什么离线索引问题不能混成在线检索问题

### 卡片固定模板

```md
卡片标题：
结论：
证据文件：
证据函数：
使用场景：
```

### 第三天通过条件

- [ ] 6 张卡片全部完成
- [ ] 每张卡片都能指向真实文件和函数


## 待验证项 Checklist

### 待验证项 1 真实接口是否已稳定走 RAG

- [ ] 跑一次真实 `/api/chat`
- [ ] 记录最终 `intent`
- [ ] 记录是否进入 `rag_retrieve_node`
- [ ] 对照 [detail.md](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\detail.md)
- [ ] 对照 [use.md](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\use.md)
- [ ] 记录“代码与旧文档是否一致”

### 待验证项 2 向量检索能否稳定工作

- [ ] 实验 2 已执行
- [ ] 记录是否依赖 `DASHSCOPE_API_KEY`
- [ ] 记录是否出现 embedding 接口失败
- [ ] 记录是否出现 Chroma 问题
- [ ] 记录是否出现超时熔断

### 待验证项 3 top docs 是否都来自危险品资料

- [ ] 打印 top docs
- [ ] 记录 `source_file`
- [ ] 判断是否全部危险品相关

### 待验证项 4 generator context 是否足够支撑回答

- [ ] 打印 `_format_docs(retrieved_docs)`
- [ ] 判断 context 是否直接相关
- [ ] 判断 context 是否足以支撑最终回答


## 最终完成判定

- [ ] 已固定一个问题并全程只用它
- [ ] 第一天完成
- [ ] 第二天完成
- [ ] 第三天完成
- [ ] 待验证项全部有记录
- [ ] 所有实验都已回滚

如果上面任一项未完成，则本轮三天执行不算闭环完成。
