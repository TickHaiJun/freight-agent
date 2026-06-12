# RAG 学习执行手册

## 0. 使用范围

本手册只服务当前项目 `freight-agent` 的 RAG 代码学习执行，不解释通用 RAG 原理。

本手册只围绕一个样例问题执行：

`锂电池货物需要什么声明文件？`

选择依据：

- `tests/test_rag_query_analyzer.py` 已直接使用这个问题
- `scripts/test_rag.py` 已直接使用这个问题
- 该问题会命中当前项目最典型的 RAG 主链路：
  - `/api/chat`
  - `intent_node`
  - `rag_retrieve_node`
  - `analyze_query`
  - `hybrid_retrieve`
  - `generate_answer`
  - SSE 返回

执行约束：

- 3 天内只使用这一个问题
- 所有观察、打印、实验都围绕这一个问题
- 不扩展到第二个问题，避免分散注意力


## 1. 先执行的准备动作

### 1.1 打开这些文件

- [main.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\main.py)
- [graph/agent.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\agent.py)
- [graph/nodes.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\nodes.py)
- [rag/query_analyzer.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\query_analyzer.py)
- [rag/retriever.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\retriever.py)
- [rag/generator.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\generator.py)
- [config.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\config.py)
- [scripts/test_rag.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\scripts\test_rag.py)
- [docs/rag_end_to_end_walkthrough.md](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\docs\rag_end_to_end_walkthrough.md)

### 1.2 执行环境准备

```cmd
cd D:\CompanyPlace\AIProject\AiFreightRate\freight-agent
AiEnv\Scripts\activate
```

### 1.3 启动服务

按 [use.md](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\use.md) 的当前启动方式执行：

```cmd
set NO_PROXY=192.168.0.186,127.0.0.1,localhost && python -m uvicorn main:app --host 127.0.0.1 --port 8082 --reload
```

### 1.4 健康检查

```cmd
curl http://127.0.0.1:8082/health
```

期望结果：

```json
{"status":"ok"}
```

### 1.5 RAG 调试脚本

打开第二个终端，执行：

```cmd
cd D:\CompanyPlace\AIProject\AiFreightRate\freight-agent
AiEnv\Scripts\activate
python scripts\test_rag.py
```

这个脚本走的是：

- `rag/__init__.py`
- `rag/service.py`
- `analyze_query`
- `hybrid_retrieve`
- `generate_answer`

它不经过 `/api/chat` 和 `graph`，只用于先单独观察 RAG 内部链路。


## 2. 执行总原则

执行顺序固定如下：

1. 先跑 `python scripts\test_rag.py`
2. 再跑 `/api/chat`
3. 再按 6 个站点逐站观察
4. 第二天只做 3 个实验
5. 第三天只整理决策卡片

记录约束：

- 每个站点必须记录“看到了什么”
- 每个实验必须记录“改了什么”和“现象是否出现”
- 每个待验证项必须单独标记，不允许混在已确认结论里


## 3. 学习站点 1：API 入口

### 3.1 代码入口

- [main.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\main.py)
- 函数：`chat(request: ChatRequest)`
- 内部函数：`generate()`

### 3.2 我应该打开哪些函数

- `chat`
- `generate`

### 3.3 我应该打印哪些变量

在 `generate()` 内临时打印：

- `request.session_id`
- `request.message`
- `request.context`
- `initial_state`
- `final_state.get("intent")`
- `final_state.get("retrieval_query")`
- `final_state.get("retrieval_filters")`
- `len(final_state.get("retrieved_docs") or [])`
- `final_state.get("rag_answer")`

建议打印位置：

- `initial_state` 构造完成后
- `final_state = await asyncio.to_thread(agent.invoke, initial_state)` 之后

### 3.4 我应该观察什么现象

执行：

```cmd
curl -X POST http://127.0.0.1:8082/api/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"session_id\":\"rag_exec_001\",\"message\":\"锂电池货物需要什么声明文件？\",\"context\":null}"
```

观察现象：

- `initial_state["messages"]` 中应有一条 `HumanMessage`
- `initial_state` 中 RAG 字段初始应为 `None`
- `final_state["intent"]` 应为 `rag`
- `final_state["retrieval_filters"]` 应非空，且预期为 `{"category": "dangerous_goods"}`
- `final_state["messages"]` 的最后一条应为 `AIMessage`
- SSE 输出应包含：
  - 多条 `text`
  - 一条 `context`
  - 一条 `done`

### 3.5 如果现象不符合预期，优先怀疑什么

- `final_state["intent"]` 不是 `rag`
  - 先怀疑 `intent_node`
- `final_state["retrieved_docs"]` 为空
  - 先怀疑 `query_analyzer` 或 `retriever`
- `final_state` 有答案，但 SSE 不完整
  - 先怀疑 `main.py` 的事件组装
- 接口直接报错
  - 先检查 `.env`、模型 key、网络、日志异常栈


## 4. 学习站点 2：graph / intent 路由

### 4.1 代码入口

- [graph/agent.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\agent.py)
- [graph/nodes.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\nodes.py)
- 函数：
  - `build_agent`
  - `route_intent`
  - `intent_node`
  - `rag_retrieve_node`
  - `rag_answer_node`

### 4.2 我应该打开哪些函数

- `route_intent`
- `intent_node`
- `rag_retrieve_node`
- `rag_answer_node`

### 4.3 我应该打印哪些变量

在 `intent_node` 打印：

- `last_message`
- `response.content`
- `intent`

在 `route_intent` 打印：

- `intent`

在 `rag_retrieve_node` 打印：

- `question`
- `analysis`
- `len(docs)`

在 `rag_answer_node` 打印：

- `question`
- `len(state.get("retrieved_docs") or [])`
- `answer`

### 4.4 我应该观察什么现象

执行 `/api/chat` 后，观察日志顺序：

1. `node intent finished`
2. `node rag_retrieve finished`
3. `node rag_answer finished`

期望现象：

- `route_intent` 返回 `rag_retrieve`
- 不经过 `slot/ask/tool/result`
- `rag_retrieve_node` 能把 `retrieval_query / retrieval_filters / retrieved_docs` 写回 state
- `rag_answer_node` 能把 `rag_answer` 写回 state

### 4.5 如果现象不符合预期，优先怀疑什么

- 走到 `fallback`
  - 先怀疑 `intent_node` 分类结果
- 走到 `slot`
  - 说明被判成 `rate_query`
- 只进 `rag_retrieve_node`，没进 `rag_answer_node`
  - 先检查 graph 边是否被改动
- `rag_answer_node` 进了但 answer 为空
  - 先检查 `retrieved_docs`


## 5. 学习站点 3：query_analyzer

### 5.1 代码入口

- [rag/query_analyzer.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\query_analyzer.py)
- 函数：
  - `analyze_query`
  - `_rule_based_analysis`
  - `_normalize_query`
  - `_call_llm`

### 5.2 我应该打开哪些函数

- `analyze_query`
- `_rule_based_analysis`
- `_normalize_query`

第一轮不要先看 `_call_llm`，因为当前样例问题优先命中规则。

### 5.3 我应该打印哪些变量

在 `analyze_query` 打印：

- `question`
- `rule_result`
- `result`

在 `_rule_based_analysis` 打印：

- `q`
- 命中的规则分支标记，例如：
  - `dangerous_goods_rule_hit`

在 `_normalize_query` 打印：

- `tokens`
- 归一化结果

### 5.4 我应该观察什么现象

执行：

```cmd
python -m unittest tests.test_rag_query_analyzer
```

再执行：

```cmd
python scripts\test_rag.py
```

期望现象：

- 对 `锂电池货物需要什么声明文件？`
  - `_rule_based_analysis` 命中危险品规则
  - 不需要走 `_call_llm`
  - `filters` 为 `{"category": "dangerous_goods"}`
  - `query` 为轻量归一化后的结果，而不是完全重写后的新句子

### 5.5 如果现象不符合预期，优先怀疑什么

- `filters` 为空
  - 先怀疑规则未命中
- 进入了 `_call_llm`
  - 先怀疑规则条件被改坏
- `query` 丢了关键词
  - 先怀疑 `_normalize_query`


## 6. 学习站点 4：retriever

### 6.1 代码入口

- [rag/retriever.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\retriever.py)
- [rag/bm25_store.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\bm25_store.py)
- [rag/vector_store.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\vector_store.py)

关键函数：

- `hybrid_retrieve`
- `_dedupe_and_merge`
- `search_bm25`
- `similarity_search`

### 6.2 我应该打开哪些函数

- `hybrid_retrieve`
- `search_bm25`
- `_dedupe_and_merge`
- `similarity_search`
- `config.py` 中的：
  - `rag_enable_vector_search`
  - `rag_enable_rerank`

### 6.3 我应该打印哪些变量

在 `hybrid_retrieve` 打印：

- `query`
- `filters`
- `len(vector_results)`
- `len(bm25_results)`
- `len(docs)`
- `docs[:2]`

在 `search_bm25` 打印：

- `query`
- `filters`
- top 3 结果的：
  - `score`
  - `metadata["source_file"]`

在 `_dedupe_and_merge` 打印：

- merge 前数量
- merge 后数量

### 6.4 我应该观察什么现象

先执行：

```cmd
python scripts\test_rag.py
```

再观察：

- 当前默认配置下：
  - `rag_enable_vector_search = False`
  - 向量检索应被跳过
  - BM25 是主要召回路径
- `filters={"category":"dangerous_goods"}` 时应有命中
- `final_docs` 应大于 0
- top docs 的 `source_file` 应集中在危险品/锂电池相关文件

### 6.5 如果现象不符合预期，优先怀疑什么

- `final_docs=0`
  - 先怀疑 BM25 索引或过滤条件
- 命中了大量非危险品文件
  - 先怀疑 filter 没生效
- BM25 没结果
  - 先检查 `data/cache/bm25.pkl`
  - 再检查 `data/docs`
- 向量检索一直没跑
  - 先看配置，这在当前默认状态下是正常现象，不算 bug


## 7. 学习站点 5：generator

### 7.1 代码入口

- [rag/generator.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\generator.py)
- [rag/prompts.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\prompts.py)

关键函数：

- `_format_docs`
- `generate_answer`

### 7.2 我应该打开哪些函数

- `_format_docs`
- `generate_answer`
- `RAG_ANSWER_SYSTEM`
- `RAG_ANSWER_USER`

### 7.3 我应该打印哪些变量

在 `generate_answer` 打印：

- `question`
- `len(retrieved_docs)`
- `_format_docs(retrieved_docs)`
- `response.content`

### 7.4 我应该观察什么现象

期望现象：

- 当 `retrieved_docs` 非空时，不走短路兜底
- `_format_docs()` 输出中应包含：
  - `来源=source_file`
  - `位置=page/slide/chunk_index`
  - 片段正文
- `response.content` 应是基于资料的回答，不应是纯闲聊回复

### 7.5 如果现象不符合预期，优先怀疑什么

- 一直返回“当前资料中未检索到明确依据”
  - 先怀疑 `retrieved_docs` 为空，不先怀疑 prompt
- 有 docs，但答案仍偏
  - 先看 `_format_docs(retrieved_docs)` 的内容是不是就偏了
- context 内容对，但答案仍明显跑偏
  - 再去检查 `RAG_ANSWER_SYSTEM`


## 8. 学习站点 6：response / SSE

### 8.1 代码入口

- [main.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\main.py)
- 关注 `generate()` 中：
  - `ai_messages` 提取
  - `for char in content`
  - `context_data`
  - `done`

### 8.2 我应该打开哪些函数

- `generate`

### 8.3 我应该打印哪些变量

打印：

- `len(ai_messages)`
- `content`
- `context_data`
- 每次 `yield` 的对象类型

### 8.4 我应该观察什么现象

通过 `curl` 观察 SSE 响应：

- `text` 事件会逐字输出
- `context` 事件只包含运价槽位：
  - `sfg`
  - `mdg`
  - `inputWeight`
  - `inputVol`
  - `hbrq`
- `context` 不包含：
  - `retrieval_query`
  - `retrieval_filters`
  - `retrieved_docs`
  - `rag_answer`

### 8.5 如果现象不符合预期，优先怀疑什么

- 没有 `text`
  - 先检查 `ai_messages`
- `context` 里出现了 RAG 中间字段
  - 说明 `main.py` 被改过
- 没有 `done`
  - 先检查异常分支


## 9. 三个可执行实验

以下 3 个实验全部基于 [docs/rag_end_to_end_walkthrough.md](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\docs\rag_end_to_end_walkthrough.md) 中已有实验，不新增第四个实验。


## 9.1 实验一：关闭规则 filter，观察召回污染

### 修改点

修改文件：

- [rag/query_analyzer.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\query_analyzer.py)

执行方式二选一：

1. 临时让 `_rule_based_analysis()` 直接 `return None`
2. 或在 `analyze_query()` 中忽略 `rule_result`

推荐最小改法：

- 仅对当前问题临时返回 `None`
- 不改其他问题规则

### 运行方式

先保存改动后执行：

```cmd
python scripts\test_rag.py
```

然后执行接口调用：

```cmd
curl -X POST http://127.0.0.1:8082/api/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"session_id\":\"rag_exec_exp1\",\"message\":\"锂电池货物需要什么声明文件？\",\"context\":null}"
```

### 预期现象

- `retrieval_filters` 变为 `None`
- `final_docs` 可能仍大于 0
- 但 top docs 的来源文件更可能变杂
- generator 答案可能仍能输出，但依据会更散

### 结果记录模板

```md
实验名称：关闭规则 filter
修改文件：
修改位置：
运行命令：
retrieval_filters：
final_docs 数量：
top 3 source_file：
最终回答摘要：
是否出现召回污染：是 / 否
结论：
回滚是否完成：是 / 否
```


## 9.2 实验二：保持 BM25，对比开启向量检索

### 修改点

修改文件：

- [config.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\config.py)

修改项：

- `rag_enable_vector_search: bool = False` 改为 `True`

不要同时改 `rag_enable_rerank`。

### 运行方式

先执行默认配置：

```cmd
python scripts\test_rag.py
```

记录一次结果后，再打开向量检索，重启服务或重新运行脚本：

```cmd
python scripts\test_rag.py
```

如需走接口链路，再执行：

```cmd
curl -X POST http://127.0.0.1:8082/api/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"session_id\":\"rag_exec_exp2\",\"message\":\"锂电池货物需要什么声明文件？\",\"context\":null}"
```

### 预期现象

- 默认状态下：
  - 只有 BM25 主召回
- 开启后：
  - 日志中应出现向量检索相关记录
  - `vector_hits` 可能大于 0
  - 最终排序可能变化

### 结果记录模板

```md
实验名称：开启向量检索对比
修改文件：
修改位置：
运行命令：
默认状态 vector_hits：
开启后 vector_hits：
默认状态 bm25_hits：
开启后 bm25_hits：
默认状态 top 3 source_file：
开启后 top 3 source_file：
默认状态回答摘要：
开启后回答摘要：
是否出现明显差异：是 / 否
结论：
回滚是否完成：是 / 否
```

### 待验证项

- 当前仓库代码支持向量检索，但该实验是否能稳定跑通，依赖：
  - `DASHSCOPE_API_KEY`
  - Chroma 索引状态
  - embedding 接口可用性

该项必须在实验记录中明确写“已验证 / 未验证”。


## 9.3 实验三：打印 generator 真正拿到的 context

### 修改点

修改文件：

- [rag/generator.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\rag\generator.py)

临时打印：

- `_format_docs(retrieved_docs)`

### 运行方式

```cmd
python scripts\test_rag.py
```

然后再执行接口调用：

```cmd
curl -X POST http://127.0.0.1:8082/api/chat ^
  -H "Content-Type: application/json" ^
  -d "{\"session_id\":\"rag_exec_exp3\",\"message\":\"锂电池货物需要什么声明文件？\",\"context\":null}"
```

### 预期现象

- 能直接看到喂给模型的 context
- context 中应包含：
  - 来源文件
  - 位置
  - 文本片段
- 如果答案偏，但 context 本身已偏，问题在 generator 之前
- 如果 context 是对的，但答案仍偏，问题再下探到 prompt 或模型

### 结果记录模板

```md
实验名称：打印 generator context
修改文件：
修改位置：
运行命令：
context 长度：
context 中 top 3 来源：
最终回答摘要：
context 是否明显相关：是 / 否
答案是否明显偏移：是 / 否
结论：
回滚是否完成：是 / 否
```


## 10. 3 天执行闭环

## 第一天：只走通主链路

### 执行动作

1. 启动服务
2. 跑健康检查
3. 跑 `python scripts\test_rag.py`
4. 跑一次 `/api/chat`
5. 按 6 个学习站点逐个加打印并观察

### 第一天必须产出

- 一份站点观察记录
- 一份主链路字段流转记录

### 第一天记录模板

```md
样例问题：锂电池货物需要什么声明文件？

站点 1 API 入口：
观察结果：
异常点：

站点 2 graph / intent：
观察结果：
异常点：

站点 3 query_analyzer：
观察结果：
异常点：

站点 4 retriever：
观察结果：
异常点：

站点 5 generator：
观察结果：
异常点：

站点 6 response / SSE：
观察结果：
异常点：

主链路是否走通：是 / 否
卡点在哪一层：
```


## 第二天：只做实验

### 执行动作

1. 实验一：关闭规则 filter
2. 回滚
3. 实验二：开启向量检索
4. 回滚
5. 实验三：打印 generator context
6. 回滚

执行要求：

- 一次只做一个实验
- 每次实验结束立即回滚
- 不允许两个实验改动叠加

### 第二天必须产出

- 3 份实验记录
- 每个实验一条结论


## 第三天：只沉淀决策卡片

### 执行动作

只整理，不再改代码。

从前两天记录中提炼 6 张决策卡片：

1. 为什么当前项目先看 `intent` 再看其他层
2. 为什么当前项目的第一排查点是 `retrieval_filters`
3. 为什么当前项目默认更像 BM25 主召回
4. 为什么 generator 出问题前先看 context
5. 为什么 `/api/chat` 链路和 `scripts/test_rag.py` 链路要分开看
6. 为什么离线索引问题不能混成在线检索问题

### 第三天卡片模板

```md
卡片标题：
结论：
证据文件：
证据函数：
什么时候用这张卡片：
```


## 11. 待验证项清单

以下内容不能直接当成已验证事实，必须进入执行清单。

### 待验证项 1：`/api/chat` 线上实际返回是否已经稳定走 RAG，而不是旧文档中的 fallback

原因：

- 真实代码中：
  - [graph/agent.py](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\agent.py) 已将 `rag` 路由到 `rag_retrieve`
- 但旧文档中：
  - [detail.md](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\detail.md)
  - [use.md](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\use.md)
  仍保留旧描述

执行动作：

- 必须跑一次真实 `/api/chat`
- 必须记录最终 `intent`
- 必须记录是否进入 `rag_retrieve_node`

### 待验证项 2：开启向量检索后是否能稳定工作

原因：

- 代码路径存在
- 默认配置关闭
- 运行依赖外部 embedding 服务

执行动作：

- 实验二必须单独记录
- 若失败，记录失败层级：
  - 配置缺失
  - embedding 接口失败
  - Chroma 问题
  - 超时熔断

### 待验证项 3：当前样例问题的 top docs 是否全部来自危险品资料

原因：

- 这是 walkthrough 中的合理预期
- 但没有被现有自动化测试直接覆盖

执行动作：

- 在 retriever 站点打印 top docs
- 记录 `source_file`

### 待验证项 4：generator 拿到的 context 是否足够支撑最终回答

原因：

- 代码会把来源和正文拼进 prompt
- 但当前仓库没有自动化断言 prompt 内容质量

执行动作：

- 实验三必须打印 `_format_docs(retrieved_docs)`
- 手工判断 context 与问题是否直接相关


## 12. 执行完成判定

满足以下条件，才算本手册执行完成：

1. 已用唯一问题跑通 `scripts/test_rag.py`
2. 已用唯一问题跑通 `/api/chat`
3. 已完成 6 个学习站点观察记录
4. 已完成 3 个实验并回滚
5. 已完成 4 个待验证项记录
6. 已产出 6 张决策卡片

未满足以上任一项，不算闭环完成。
