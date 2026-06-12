# 1. 文档目标

这份文档不是 RAG 模块百科，也不是通用原理说明，而是一次沿着“典型用户问题”走完整调用链的代码审计式理解。重点是基于当前仓库里的真实代码，回答下面这些问题：

- 用户问题如何从 `/api/chat` 进入系统
- 它如何被识别成 RAG 请求
- 它如何进入 `query_analyzer`
- 检索 query 和 metadata filter 是怎么来的
- retriever 为什么现在是 `BM25 + 可选向量 + 可选 rerank 预留`
- generator 如何拼接检索结果并生成答案
- 最终答案如何回到接口层，再以 SSE 形式返回
- 去掉某一层后，线上最可能坏在哪里
- 出现“答非所问 / 没答到点上”时，应该按什么顺序排查

这篇文档严格以真实代码为准。凡是代码里没有体现的能力，我会明确标注“当前未启用”或“待确认”，不会把设计文档里的目标状态当成已实现事实。


# 2. 全链路 Mermaid 图

下面这张图对应当前代码中的真实链路，不是通用 RAG 模板图。

```mermaid
flowchart TD
    A[POST /api/chat<br/>main.py chat()] --> B[构造 AgentState<br/>messages/context/空的 RAG 中间态]
    B --> C[agent.invoke(initial_state)<br/>graph/agent.py]
    C --> D[intent_node<br/>graph/nodes.py]
    D --> E{route_intent}
    E -->|rate_query| F[运价链路<br/>slot -> ask/tool -> result]
    E -->|rag| G[rag_retrieve_node]
    E -->|unknown| H[fallback_node]

    G --> I[analyze_query(question)<br/>rag/query_analyzer.py]
    I --> J[hybrid_retrieve(query, filters)<br/>rag/retriever.py]
    J --> K[search_bm25<br/>rag/bm25_store.py]
    J --> L[similarity_search<br/>rag/vector_store.py]
    J --> M[rerank<br/>rag/reranker.py]
    J --> N[retrieved_docs 写回 state]
    N --> O[rag_answer_node]
    O --> P[generate_answer(question, retrieved_docs)<br/>rag/generator.py]
    P --> Q[AIMessage(answer) 写回 state]
    Q --> R[main.py 取最后一条 AIMessage]
    R --> S[按字符产出 SSE text 事件]
    S --> T[返回 context 事件]
    T --> U[返回 done 事件]

    subgraph Offline[离线建库链路]
        X[scripts/init_kb.py / rebuild_kb.py] --> Y[rag/indexer.py]
        Y --> Z1[load_document]
        Z1 --> Z2[clean_documents]
        Z2 --> Z3[split_documents]
        Z3 --> Z4[add_documents -> Chroma]
        Z3 --> Z5[build_bm25_index -> data/cache/bm25.pkl]
    end

    L -. 读取 .-> Z4
    K -. 读取 .-> Z5
```

这张图有两个非常关键的代码事实：

- 在线主链路不是经过 `rag/service.py`，而是 `graph/nodes.py` 直接调用 `analyze_query`、`hybrid_retrieve`、`generate_answer`
- `rag/service.py` 确实存在，但当前更像一个“脚本/测试可复用编排层”，不是 `/api/chat` 在线请求的必经路径


# 3. 选定一个典型用户问题

我选的典型问题是：

`锂电池货物需要什么声明文件？`

选择理由：

- 这是仓库里已有真实样例，不是我临时脑补出来的
- `tests/test_rag_query_analyzer.py` 直接用它验证危险品规则命中
- `scripts/test_rag.py` 也用它作为 RAG 调试输入
- 它会走当前系统最典型的一条 RAG 主路径：`intent -> query_analyzer(规则命中) -> hybrid_retrieve -> generator`

为什么它代表主要路径：

- 它属于明确的业务知识问答，不会误入报价工具链
- 它会命中 `dangerous_goods` 类别过滤，能把 metadata filter 的价值体现出来
- 它既能触发召回，也能暴露“召回不足”和“生成偏移”两类问题

如果把这个问题换成 `ACCOS 系统怎么录入分单件数`，本质链路类似，只是 `query_analyzer` 会给出 `operations` filter。两者共同说明：当前系统的主路径是“规则优先缩小搜索空间，再做检索和生成”。


# 4. 从入口开始逐层走读整条链路

## 4.1 API 入口层

### 这一层的代码入口在哪里

- `main.py` 中的 `chat(request: ChatRequest)`
- 实际流式输出逻辑在内部生成器 `generate()`

### 这一层的输入是什么

- HTTP 请求体里的：
  - `session_id`
  - `message`
  - `context`
- 业务语义上，它拿到的是“用户本轮问题”和“前端缓存的上一轮运价槽位状态”

### 这一层的输出是什么

- 不是一次性 JSON，而是 `text/event-stream`
- 输出事件顺序是：
  - 多个 `text` 事件
  - 一个 `context` 事件
  - 一个 `done` 事件
- 如果出错，则输出：
  - 一个 `error` 事件
  - 一个 `done` 事件

这个输出对下游前端有一个很强的约束：前端不是等一个完整 JSON，而是要消费 SSE 事件流。RAG 接入不能破坏这个协议。

### 这一层内部做了哪些关键决策

- 把 `request.message` 包成 `HumanMessage` 塞进 `AgentState["messages"]`
- 把 `context` 中已有的 `sfg/mdg/inputWeight/inputVol/hbrq` 注入 state
- 同时初始化 RAG 相关中间态：
  - `rag_query`
  - `retrieval_query`
  - `retrieval_filters`
  - `retrieved_docs`
  - `rag_answer`
- 通过 `await asyncio.to_thread(agent.invoke, initial_state)` 执行 LangGraph，同步图放到线程里跑
- 图跑完后，才从最终 state 中取最后一条 AIMessage，再“按字符模拟流式输出”

这里有个容易忽略的事实：当前 SSE 不是模型 token 级流式，而是图执行完成后，服务端把最终答案按字符拆开再发。也就是说，RAG 检索和生成没结束之前，前端收不到任何 `text` 字符。

### 这一层为什么必须放在这里做

- `AgentState` 的初始化只能在接口层做，因为它同时依赖请求体和前端回传 context
- SSE 协议的组装也应该在接口层做，不能下沉到 graph 或 rag 模块，否则业务逻辑会和传输协议耦合

### 如果把这一层去掉，最可能发生什么问题

- 没有统一入口组装 state，图拿不到 `messages`，整个 LangGraph 无法起步
- 没有 SSE 包装，前端现有消费方式会直接失效
- 不初始化 RAG 中间态，后续调试时 state 可观测性会明显变差

### 这一层的降级 / fallback 逻辑是什么

- 所有未捕获异常都会进入 `except`，回一个 `error` 事件和 `done`
- 没有细分 RAG 错误码；接口层只做总兜底，不理解 query_analyzer、retriever、generator 的内部差异

### 这一层有哪些可观测点

- `chat request started`
- `chat agent finished`
- `chat request done`
- `chat request failed`
- 记录了：
  - `session_id`
  - 用户 `message`
  - 总耗时
  - 最终 `intent`

当前缺少的可观测点：

- 没有把 `retrieval_query / retrieval_filters / retrieved_docs` 打到接口层日志
- 没有区分“图执行慢”是慢在检索还是慢在生成

### 调试这层时，第一眼应该看什么

- 先看接口日志里最终 `intent` 是不是 `rag`
- 再确认前端看到的是不是完整的 `text/context/done` 三段式 SSE
- 如果前端一直没字返回，先别急着怀疑 SSE，本质更可能是图内部某层慢或阻塞


## 4.2 intent / graph 路由层

### 这一层的代码入口在哪里

- `graph/agent.py`:
  - `build_agent()`
  - `route_intent()`
- `graph/nodes.py`:
  - `intent_node(state)`

### 这一层的输入是什么

- 输入是 `AgentState`
- 业务语义上最关键的是 `state["messages"][-1].content`，也就是用户最新一句话

### 这一层的输出是什么

- `intent_node` 输出 `intent`
- `route_intent` 决定下一个节点：
  - `rate_query -> slot`
  - `rag -> rag_retrieve`
  - 其他 -> `fallback`

这个输出对下游的约束非常强：一旦这里判成 `rate_query` 或 `unknown`，RAG 后续所有层都不会执行。

### 这一层内部做了哪些关键决策

- `intent_node` 使用 DeepSeek 调 `INTENT_SYSTEM/INTENT_USER`
- 模型返回值只允许三类：
  - `rate_query`
  - `rag`
  - `unknown`
- 如果模型返回了别的字符串，代码直接归一成 `unknown`

这是一个典型的“LLM 分类 + 代码侧强约束”写法。模型负责理解，代码负责把输出收敛到有限集合。

### 这一层为什么必须放在这里做

- 路由决策应该发生在 graph 层，而不是 retriever 层
- 如果把“是不是 RAG”放到 retriever 再判断，说明请求已经走错层了，系统边界会变糊
- graph 层的职责就是决定走哪条业务子流程，而不是实现子流程细节

### 如果把这一层去掉，最可能发生什么问题

- 所有请求都得强行走同一链路，要么报价问题被拿去检索知识库，要么知识问答被拿去抽槽位
- 最直接的坏法是：
  - `锂电池货物需要什么声明文件` 这类问题被当成运价查询，开始追问重量体积
  - `上海到洛杉矶多少钱` 被错误送进 RAG，最后答一堆无关知识

### 这一层的降级 / fallback 逻辑是什么

- 模型输出非预期值时，强制归为 `unknown`
- `unknown` 统一走 `fallback_node`

注意一个真实代码细节：

- `graph/prompts.py` 里仍保留了 `FALLBACK_RESPONSES["rag"]`
- 但现在 `graph/agent.py` 已经把 `intent == "rag"` 显式路由到 `rag_retrieve`
- 所以这个 `rag` fallback 文案从在线主链路看，已经基本不是实际生效路径了，属于遗留兼容内容

### 这一层有哪些可观测点

- `node intent finished | intent=...`

当前缺少的可观测点：

- 没有打印 LLM 原始分类回复
- 没有记录分类 prompt 或上下文

### 调试这层时，第一眼应该看什么

- 第一眼看最终 `intent`
- 如果用户明明在问知识问题但没走 RAG，先不要看 retriever，先看分类
- 如果分类频繁漂移，再去看 `graph/prompts.py` 的 `INTENT_SYSTEM`


## 4.3 RAG 检索入口层

### 这一层的代码入口在哪里

- `graph/nodes.py` 中的 `rag_retrieve_node(state)`

### 这一层的输入是什么

- 当前 state
- 核心业务输入是用户最后一句问题，即 `state["messages"][-1].content.strip()`

### 这一层的输出是什么

- 把这些字段写回 state：
  - `rag_query`
  - `retrieval_query`
  - `retrieval_filters`
  - `retrieved_docs`

这一步的最大价值不是“做完检索”，而是把检索中间态显式保留在 state 中。这样 `rag_answer_node` 不需要重新推断，也便于排障时判断问题出在分析还是召回。

### 这一层内部做了哪些关键决策

- 先调用 `analyze_query(question)`
- 再把分析结果传给 `hybrid_retrieve`
- `query` 用 `analysis.get("query", question)`
- `filters` 用 `analysis.get("filters")`

这里故意把“query 分析”和“检索执行”拆开，说明作者希望把“用户怎么被改写成检索请求”和“检索器怎么查”分成两个可观察步骤。

### 这一层为什么必须放在这里做

- graph 节点负责把跨模块调用串起来，并把结果写回 state
- 如果把 `analyze_query + hybrid_retrieve` 直接塞进 generator，检索和生成就耦合了，排障时看不见中间产物
- 如果完全交给 `rag/service.py`，也能工作，但在线链路会少掉显式 state 写回，调试颗粒度更粗

### 如果把这一层去掉，最可能发生什么问题

- `rag_answer_node` 拿不到 `retrieved_docs`
- 中间态无法沉淀到 state，排障只能靠日志猜
- 更具体地说，用户说“答错了”时，你没法第一时间知道是 `query/filter` 错了，还是召回空了

### 这一层的降级 / fallback 逻辑是什么

- 这一层自身不处理异常，异常会往上抛到接口层
- 具体降级发生在它调用的 `analyze_query` 和 `hybrid_retrieve` 内部

### 这一层有哪些可观测点

- `node rag_retrieve finished | filters=... | docs=...`

当前缺少的可观测点：

- 日志里没打出 `retrieval_query`
- 也没把召回到的 `source_file` 列表打出来

### 调试这层时，第一眼应该看什么

- 先看 `retrieval_filters` 有没有命中预期类别
- 再看 `retrieved_docs` 数量是不是 0
- 如果 docs=0，不要直接怪生成层，先沿着 `query_analyzer -> retriever` 往前查


## 4.4 query analyzer 层

### 这一层的代码入口在哪里

- `rag/query_analyzer.py` 中的 `analyze_query(question)`

### 这一层的输入是什么

- 一个原始用户问题字符串
- 业务语义上是“自然语言问题”，还不是检索系统能直接消费的结构化请求

### 这一层的输出是什么

- 统一返回：

```json
{
  "query": "...",
  "filters": {...} 或 null
}
```

它给下游带来的约束是：

- retriever 不再面对原始问题，而是面对一个“规范化后的 query”
- metadata filter 也不由 retriever 自己猜，而是由 analyzer 先给出来

### 这一层内部做了哪些关键决策

当前实现是非常明确的三段式：

1. 空字符串直接返回空 query
2. 规则优先 `_rule_based_analysis()`
3. 规则命不中再调用 LLM `_call_llm()`
4. 如果 LLM 异常，再退化到 `_normalize_query(question)`

规则层目前覆盖四类：

- `锂电池/危险品/pi967/pi968/包装说明` -> `dangerous_goods`
- `accos/分单/件数/录入` -> `operations`
- `普货/不带电/委托书` 且不含危险品词 -> `general_cargo`
- `报关/品名清单/上海口岸/清关` -> `customs`

`_normalize_query()` 的作用也很克制：

- 只做轻量标准化，不做语义重写
- 保留英文、数字、中文、罗马数字
- 去掉大部分标点

这说明当前 query analyzer 的目标不是“把问题润色得更像搜索词”，而是“先保证 query 可检索、可回放、可解释”。

### 这一层为什么必须放在这里做

- query 改写不该塞进 retriever，因为 retriever 的职责是“查”，不是“理解问题”
- filter 提取也不该在 vector_store / bm25_store 里做，否则底层存储层就开始理解业务类别了，边界会乱
- 规则优先放在 analyzer 层，可以在最靠近用户问题的位置做收敛，减少后面所有层的噪音

### 如果把这一层去掉，最可能发生什么问题

- retriever 只能拿原始自然语言裸搜
- 最直接的坏法是 filter 丢失，召回空间变散
- 对当前这 8 份业务文档来说，一旦不做 `category` 约束，危险品、普货、操作规范可能互相污染

### 这一层的降级 / fallback 逻辑是什么

- 规则优先
- 规则命不中才走 LLM
- LLM 异常时，不中断主链路，退回：
  - `query = _normalize_query(question)`
  - `filters = None`

这是当前系统非常重要的一层降级。它保证了“理解不够准”时最多是检索范围变宽，而不是整个 RAG 直接报错。

### 这一层有哪些可观测点

- `rag query_analyzer finished | mode=rule | filters=...`
- `rag query_analyzer llm finished`
- `rag query_analyzer finished | mode=llm_fallback | filters=...`

当前缺少的可观测点：

- 没打出最终 `query`
- 没记录规则命中了哪条具体规则
- LLM 返回的原始 JSON 没落日志

### 调试这层时，第一眼应该看什么

- 第一眼看最终产出的 `filters`
- 第二眼看最终 `query` 是否保留了关键术语
- 如果用户问的是明确领域词却没带出 filter，优先怀疑规则覆盖不足，而不是先怀疑向量库


## 4.5 retriever 层

### 这一层的代码入口在哪里

- `rag/retriever.py` 中的 `hybrid_retrieve(query, filters=None)`

### 这一层的输入是什么

- `query_analyzer` 产出的 `query`
- 可选的 `filters`

业务语义上，它拿到的是“已经结构化过的检索请求”，而不是原始对话。

### 这一层的输出是什么

- `list[dict]`
- 每个元素大致长这样：

```json
{
  "page_content": "...",
  "metadata": {...},
  "score": 1.23
}
```

这个输出对下游 generator 的约束是：

- generator 不自己查库，只消费已经选好的候选片段
- generator 依赖其中的 `page_content` 和 `metadata.source_file/page/slide/chunk_index`

### 这一层内部做了哪些关键决策

1. 先尝试向量检索
2. 再执行 BM25 检索
3. 如果两边都空且存在 filters，则去掉 filter 重试一次
4. `_dedupe_and_merge()` 按 `(source_file, chunk_index)` 去重
5. 采用简单融合分数：

`rank_value = bm25_score - vector_score`

6. 如果配置开关打开，再调用 `rerank`

这里有一个必须说清楚的真实代码事实：

- `config.py` 里 `rag_enable_vector_search = False`
- 所以默认配置下，向量检索根本不会跑
- 当前线上更准确地说是“BM25 主召回 + 向量检索预留 + rerank 预留”

这和设计文档里的“混合检索”方向一致，但和当前默认运行态并不完全一致。写审计文档必须把这个差别讲清楚。

### 这一层为什么必须放在这里做

- merge 去重和召回策略融合必须发生在 retriever 层，而不是 generator
- 如果把 BM25 和 vector 各查各的结果直接交给 generator，让模型自己挑，会把“召回排序”这个工程问题甩给生成模型，既不可控也不便排障
- filter 失败后的“退回无 filter 再查一次”也应该放在 retriever，因为这是召回策略，不是 analyzer 或 generator 的职责

### 如果把这一层去掉，最可能发生什么问题

- 没有统一召回器，query analyzer 输出的 `query/filter` 没地方被真正执行
- 更具体的坏法有三种：
  - 不做 filter fallback：metadata 一旦判错，直接 0 命中
  - 不做 BM25：术语型问题，例如 `ACCOS`、`PI967`，命中率会掉
  - 不做 dedupe merge：同一 chunk 可能重复进入上下文，污染生成 prompt

### 这一层的降级 / fallback 逻辑是什么

- 向量检索异常时：
  - 记异常日志
  - 返回空向量结果
- BM25 检索异常时：
  - 记异常日志
  - 返回空 BM25 结果
- 两边都空且原先带 filter 时：
  - 自动退回无 filter 再查一次
- rerank 只有 `settings.rag_enable_rerank` 为真时才执行

### 这一层有哪些可观测点

- `rag hybrid_retrieve start | filters=... | query=...`
- `rag hybrid_retrieve retry without filters`
- `rag hybrid_retrieve finished | vector_hits=... | bm25_hits=... | final_docs=...`

这是当前在线链路里最重要的一组召回日志。

### 调试这层时，第一眼应该看什么

- 先看 `vector_hits / bm25_hits / final_docs`
- 如果 `bm25_hits` 很高但答案仍然不对，下一步不是怪 analyzer，而是打开看看 top docs 内容
- 如果带 filter 为 0，但去掉 filter 后有结果，说明问题大概率在 filter 过严或规则误判


## 4.6 vector store 层

### 这一层的代码入口在哪里

- `rag/vector_store.py`
  - `get_vector_store()`
  - `similarity_search(query, k, filters=None)`
  - `add_documents(documents)`
  - `delete_by_source_file(source_file)`
  - `reset_collection()`

### 这一层的输入是什么

- 在线检索时：
  - `query`
  - `k`
  - `filters`
- 离线建库时：
  - 已切好的 `documents`

### 这一层的输出是什么

- 在线检索返回：

```json
[
  {"document": Document(...), "score": 0.12}
]
```

- 离线写库不返回业务结果，只执行副作用写入

### 这一层内部做了哪些关键决策

- Chroma 初始化被做成模块级单例 `_VECTOR_STORE`
- 持久化目录来自 `settings.chroma_persist_dir`
- 检索时支持 `filters` 直传给 Chroma
- 包了一层 `_query_with_timeout()`，用线程池对向量检索做超时保护
- 一旦超时或异常，会把 `_VECTOR_SEARCH_DISABLED = True`

这个“失败后全局禁用向量检索”的策略很重要。它说明当前系统更看重在线稳定性，而不是死扛向量检索。

### 这一层为什么必须放在这里做

- Chroma 初始化、超时控制、collection 操作都属于存储访问层职责
- 如果把这些逻辑塞进 retriever，retriever 会同时承担策略和存储细节，层次会混乱

### 如果把这一层去掉，最可能发生什么问题

- 向量检索完全不可用
- 离线建库也没法把 chunk 写入 Chroma
- “先删后加”的单文件重建策略会失效，因为删除动作就在这里封装

### 这一层的降级 / fallback 逻辑是什么

- 超时后直接返回空，并永久禁用当前进程内后续向量检索
- 异常后同样禁用
- 由于默认配置 `rag_enable_vector_search=False`，很多运行环境里这层事实上处于预留态

### 这一层有哪些可观测点

- vector store init start/finished
- similarity_search start/finished
- timeout / failed / disable_vector_search

当前缺少的可观测点：

- 没有记录命中的具体 `source_file`
- 没有暴露 `_VECTOR_SEARCH_DISABLED` 当前状态到健康检查

### 调试这层时，第一眼应该看什么

- 先看配置里 `rag_enable_vector_search` 是否启用
- 如果启用了但始终没结果，再看日志里有没有 `disable_vector_search`
- 如果出现一次 timeout，后续空结果可能不是 query 问题，而是这层已经被熔断掉了


## 4.7 BM25 层

### 这一层的代码入口在哪里

- `rag/bm25_store.py`
  - `build_bm25_index(documents)`
  - `search_bm25(query, k, filters=None)`

### 这一层的输入是什么

- 在线检索时：
  - `query`
  - `k`
  - `filters`
- 离线建库时：
  - 切好的 chunk 文档列表

### 这一层的输出是什么

- 返回值格式和向量检索保持一致：

```json
[
  {"document": Document(...), "score": 12.34}
]
```

### 这一层内部做了哪些关键决策

- tokenization 很轻量：
  - 英文数字按连续串
  - 中文按单字切
- 缓存文件固定落到 `data/cache/bm25.pkl`
- 如果缓存缺失，`search_bm25()` 会自动触发 `_build_bm25_index_from_docs()`
- 当前过滤策略是：
  - 先对全量 chunk 打分
  - 再按 metadata 过滤

这说明当前 BM25 设计优先级是：

- 先可跑
- 先可恢复
- 先可解释

而不是先做最优性能。

### 这一层为什么必须放在这里做

- 分词、缓存、恢复、过滤都属于关键词召回子系统，不应该散落到 retriever 或 indexer
- 尤其是“缓存缺失时自动从 docs 重建”这件事，只有 BM25 自己最清楚该怎么恢复

### 如果把这一层去掉，最可能发生什么问题

- 当前默认配置下，在线 RAG 基本失去主召回能力
- 因为向量检索默认是关的，BM25 实际上是默认路径上的主要召回器
- 最直接的坏法是：
  - `ACCOS`
  - `PI967`
  - `报关品名清单`
  这些强关键词问题会显著退化

### 这一层的降级 / fallback 逻辑是什么

- 缓存不存在时，自动从 `data/docs` 走一遍：
  - `validate_metadata`
  - `load_document`
  - `clean_documents`
  - `split_documents`
  - `build_bm25_index`
- 如果最终索引为空，则警告并返回 `[]`

### 这一层有哪些可观测点

- `rag bm25 search start/finished`
- `rag bm25 cache missing | action=rebuild_from_docs`
- `rag bm25 rebuild_from_docs finished | docs=... | skipped_files=...`
- `rag bm25 skip source file`

这些日志对排查非常有用，因为它们能把“在线查不到”和“底层索引根本没建好”区分开。

### 调试这层时，第一眼应该看什么

- 先看 `data/cache/bm25.pkl` 是否存在
- 再看日志里有没有 `cache missing` 或 `skip source file`
- 如果某个 `.doc` 文件没装 Word/没装 `pywin32`，它可能在重建时被跳过，这会直接导致相关知识永远召回不到


## 4.8 reranker 层

### 这一层的代码入口在哪里

- `rag/reranker.py` 中的 `rerank(query, docs)`

### 这一层的输入是什么

- query
- 已融合排序后的 docs

### 这一层的输出是什么

- 还是 docs 列表

### 这一层内部做了哪些关键决策

当前没有真正决策。

真实代码只有一行：

- `return docs`

再结合配置：

- `settings.rag_enable_rerank = False`

所以当前 reranker 是明确的接口预留，不是已启用能力。

### 这一层为什么必须放在这里做

- 即使第一版不启用，接口先放在 retriever 之后是合理的
- rerank 的职责本来就是“对召回候选再排序”，不该放进 generator

### 如果把这一层去掉，最可能发生什么问题

- 现在几乎不会有行为变化，因为默认没启用
- 真正会坏的是后续扩展成本：以后想接重排模型时，需要改 retriever 接口和调用链

### 这一层的降级 / fallback 逻辑是什么

- 当前等价于永远降级为“不做 rerank”

### 这一层有哪些可观测点

- 当前没有独立日志

### 调试这层时，第一眼应该看什么

- 第一眼先确认它是不是启用了
- 当前项目里，如果有人怀疑“是不是 rerank 排坏了”，先看配置，你会发现大概率根本没进这层


## 4.9 generator 层

### 这一层的代码入口在哪里

- `rag/generator.py`
  - `_format_docs(retrieved_docs)`
  - `generate_answer(question, retrieved_docs)`

### 这一层的输入是什么

- 原始用户问题 `question`
- retriever 返回的 `retrieved_docs`

从业务角度说，它拿到的是“问题 + 候选依据片段”，而不是原始知识库。

### 这一层的输出是什么

- 一个最终中文答案字符串

这个输出对接口层的约束是：

- `main.py` 只负责把它包装成 SSE，不再修改内容

### 这一层内部做了哪些关键决策

- 如果 `retrieved_docs` 为空，直接短路返回：
  - `当前资料中未检索到明确依据，建议联系业务同事进一步确认。`
- 如果有 docs：
  - `_format_docs()` 会把每个片段组装成：
    - `来源=source_file`
    - `位置=page/slide/chunk_index`
    - 片段正文
  - 然后用 `RAG_ANSWER_SYSTEM` 强约束模型“只能依据检索结果回答”

这里有个很关键的设计点：

- generator 不再自己做检索
- 也不再自己猜 filter
- 它只做“基于给定上下文生成回答”

这使得“回答质量差”可以被拆成两类问题：

- 上下文本身不对
- 模型拿到对的上下文但仍生成偏了

### 这一层为什么必须放在这里做

- 生成回答本来就是这一层职责
- 如果 generator 里再偷偷做二次检索，问题会被隐藏，排障时无法知道它到底用了哪批上下文

### 如果把这一层去掉，最可能发生什么问题

- 系统最多只能把召回片段原样吐给用户
- 更实际的坏法是：你丢掉了“把多个片段整合成面向用户答案”的能力，用户体验会直接退成文档片段拼接

### 这一层的降级 / fallback 逻辑是什么

- docs 为空时短路兜底
- 没有对 LLM 调用异常做局部捕获；异常会继续往上冒，由接口层统一 error 处理

### 这一层有哪些可观测点

- `rag generator finished | docs=0 | short_circuit=true`
- `rag generator finished | docs=n`

当前缺少的可观测点：

- 没有记录实际喂给模型的 context 长度
- 没有记录每个 doc 的 `source_file`

### 调试这层时，第一眼应该看什么

- 先看它收到的 docs 是否为空
- 如果不为空但答案还是偏，第一步不是改 prompt，而是先把 `_format_docs()` 真正拼出来的上下文拿出来看
- 如果上下文没问题，再去看 `RAG_ANSWER_SYSTEM`


## 4.10 response 返回层

### 这一层的代码入口在哪里

- `main.py` 中 `generate()` 后半段

### 这一层的输入是什么

- 图执行后的 `final_state`
- 最关键的是 `final_state["messages"]` 中最后一条 AIMessage

### 这一层的输出是什么

- 按字符拆成多个 SSE `text` 事件
- 然后返回一个只包含运价槽位的 `context`
- 最后返回 `done`

### 这一层内部做了哪些关键决策

- 只回传运价上下文：
  - `sfg`
  - `mdg`
  - `inputWeight`
  - `inputVol`
  - `hbrq`
- 不回传 `retrieval_query/retrieval_filters/retrieved_docs/rag_answer`

这说明当前前端上下文机制是围绕运价多轮对话设计的，RAG 第一版没有把检索中间态暴露给前端。

### 这一层为什么必须放在这里做

- 响应协议是接口层职责
- graph 和 rag 模块不应该知道 SSE 事件长什么样

### 如果把这一层去掉，最可能发生什么问题

- 前端没法消费答案
- 运价多轮对话上下文回传机制会断

### 这一层的降级 / fallback 逻辑是什么

- 如果上游抛异常，统一发 `error + done`

### 这一层有哪些可观测点

- 只有接口层总耗时日志
- 当前没有“发送了多少字符”“最后答案长度多少”的日志

### 调试这层时，第一眼应该看什么

- 如果最终 state 里已有正确 AIMessage，但前端没显示，问题就在这里或前端 SSE 消费侧
- 如果最终 state 本身就没有正确答案，那就不是返回层问题


# 5. 串起来讲：这一条请求从头到尾的数据是怎么流动的

这里不按模块，而按“数据对象”讲。

## 5.1 原始 request

进入系统时，请求体大致是：

```json
{
  "session_id": "xxx",
  "message": "锂电池货物需要什么声明文件？",
  "context": null
}
```

此时真正有业务意义的数据只有一句自然语言问题。

## 5.2 AgentState

在 `main.py` 里，它被转换成：

- `messages = [HumanMessage("锂电池货物需要什么声明文件？")]`
- 运价槽位字段全部为 `None`
- RAG 中间字段也先初始化为 `None`

这个变化很关键：

- 原始 HTTP 请求被变成了 LangGraph 能流转的统一状态对象

## 5.3 intent / route

`intent_node` 跑完后，state 新增：

- `intent = "rag"`

`route_intent()` 根据它决定进入 `rag_retrieve`

这一步新增的字段只有一个，但它决定了后面所有分支。

## 5.4 query analyzer 产物

`rag_retrieve_node` 调 `analyze_query()` 后，会把这些东西写回 state：

- `rag_query = "锂电池货物需要什么声明文件？"`
- `retrieval_query = "锂电池货物需要什么声明文件"`
- `retrieval_filters = {"category": "dangerous_goods"}`

这里最重要的不是 query 是否“漂亮”，而是：

- filter 首次把问题压缩到了危险品类资料

## 5.5 retriever 产物

`hybrid_retrieve()` 返回后，state 新增：

- `retrieved_docs = [...]`

里面的每个元素最关键的字段是：

- `page_content`
- `metadata.source_file`
- `metadata.page/slide/chunk_index`
- `score`

这里是整个排障链上最关键的对象之一。因为一旦 `retrieved_docs` 就不对，后面的 generator 再强也没法救。

## 5.6 generator 输入

`generate_answer()` 实际拿到的是：

- 原始问题 `question`
- 召回到的 `retrieved_docs`

然后它会把 docs 格式化成包含来源和位置的上下文文本，再喂给模型。

这一步对象变化的关键是：

- 检索结构化结果被压平为 prompt 文本

从这一刻开始，问题开始从“检索问题”转向“prompt 和生成问题”。

## 5.7 最终 response

`rag_answer_node` 把：

- `rag_answer = "..."`
- `AIMessage(content=rag_answer)`

写回 state。

之后 `main.py`：

- 只读取最后一条 AIMessage
- 逐字符发 SSE `text`
- 回传运价 `context`
- 发 `done`

排查时最关键的字段顺序，我建议记成：

1. `intent`
2. `retrieval_filters`
3. `retrieval_query`
4. `retrieved_docs`
5. `rag_answer`

这五个字段就是最小的 RAG 在线诊断闭环。


# 6. 这个项目的关键设计取舍

## 6.1 为什么这里是规则优先，而不是 LLM 优先

真实代码选择了规则优先。

证据：

- `rag/query_analyzer.py` 的 `analyze_query()` 先跑 `_rule_based_analysis()`
- 只有规则命不中，才 `_call_llm()`

这说明当前实现更偏向：

- 稳定性优先
- 可解释性优先
- 排障优先

而不是“尽可能让模型理解一切”。

对当前 8 个文件的小知识库，这是合理的，因为业务域相对稳定，术语边界也比较清楚。

## 6.2 为什么需要 metadata filter

因为当前文档异构得很明显：

- 危险品/锂电池
- 系统操作
- 普货表单
- 报关清单

如果不做 `category` 过滤，裸搜很容易把“委托书”“清单”“说明”等泛词召回到错误领域。当前 filter 做得不重，但已经足以把检索范围从“整个知识库”缩到“某一业务域”。

## 6.3 为什么需要 BM25

从真实代码看，BM25 不只是“需要”，而且当前默认是主力召回。

证据：

- `config.py` 中 `rag_enable_vector_search = False`
- `hybrid_retrieve()` 每次都会跑 `search_bm25()`

这说明当前系统更怕的是：

- 术语、缩写、表单名召回不到

而不是：

- 纯语义近义表达稍微丢一点

## 6.4 为什么还保留向量检索

因为设计方向仍然是 hybrid，只是当前默认不开。

保留原因很实际：

- 将来开启后，可提升纯语义问题的召回
- 接口先稳定下来，后续只改配置和索引即可

但当前必须认识到：它还是预留能力，不是默认运行事实。

## 6.5 为什么需要 reranker，或者为什么现在没有上

真实代码选择了“接口先放着，逻辑先不做”。

这说明当前优先级不是进一步优化排序，而是先把：

- 文档解析
- metadata
- query analyzer
- 主召回

这些基础层打稳。

这是合理的。因为小知识库里，最先出问题的往往不是“候选排序略差”，而是“根本没召回来”或“召回错类别”。

## 6.6 为什么 service / graph / generator 这样拆层

当前代码的真实拆法有一个值得点出来的地方：

- `rag/service.py` 存在，但在线链路没走它
- 在线链路是 graph 节点直接串 analyzer/retriever/generator

这反映出当前项目在两种诉求之间做了折中：

- graph 侧需要中间状态写回 state，便于调试
- service 侧需要一个可复用编排入口，便于脚本和测试调用

所以现在不是“二选一”，而是两条编排入口并存：

- 在线：`graph/nodes.py`
- 离线脚本/测试：`rag/service.py`

## 6.7 当前实现更偏向哪种优先级

结合配置和代码，我的判断是：

- 优先稳定性
- 优先简单
- 优先可排障

不是：

- 优先最强语义召回
- 优先最低延迟
- 优先最复杂的检索策略

证据包括：

- 规则优先
- BM25 默认主召回
- rerank 默认关闭
- 向量检索默认关闭
- filter 错了自动退回无 filter
- BM25 缓存缺失自动重建

## 6.8 这套设计适合什么场景，不适合什么场景

适合：

- 文档量小到中等
- 业务域明确
- 术语比较稳定
- 需要快速定位问题来源

不太适合：

- 文档规模很大
- 类别边界复杂且经常变化
- 很依赖纯语义召回
- 对检索延迟极其敏感


## 6.9 离线建库链路与在线检索链路的边界

这是当前项目特别值得单独拎出来的一点。

### 哪些是离线流程

- `scripts/init_kb.py`
- `scripts/rebuild_kb.py`
- `rag/indexer.py`
- `rag/loaders.py`
- `rag/cleaner.py`
- `rag/splitter.py`
- `rag/vector_store.add_documents()`
- `rag/bm25_store.build_bm25_index()`

### 哪些是在线流程

- `main.py`
- `graph/agent.py`
- `graph/nodes.py`
- `rag/query_analyzer.py`
- `rag/retriever.py`
- `rag/generator.py`
- `rag/vector_store.similarity_search()`
- `rag/bm25_store.search_bm25()`

### 两者通过什么数据结构或存储衔接

- 向量侧通过 `data/chroma` 下的 Chroma collection 衔接
- BM25 侧通过 `data/cache/bm25.pkl` 衔接
- 两边共同依赖的“检索单元定义”来自 `split_documents()` 产出的 chunk 结构和 metadata

### 为什么在线排障时不能把离线和在线问题混为一谈

因为这两类问题的表象很像，但根因完全不同。

例子：

- 用户问“锂电池声明文件”，返回空
- 这可能是在线 `query_analyzer` filter 错了
- 也可能是离线 `.doc` 文档解析失败，导致危险品资料根本没进索引

如果不先区分“索引里有没有”与“在线有没有查到”，排障会一直在错误层打转。


# 7. 如果我要最快建立整体认知，应该按什么顺序读这份代码

我建议按下面顺序读，不是按目录顺序。

1. `main.py`

先看这里，是为了先抓住整个系统对外长什么样：

- 请求体
- SSE 返回协议
- AgentState 如何初始化

不先看这里，后面很容易只盯着模块，忽略了系统实际入口。

2. `graph/agent.py`

第二步看路由图，是为了快速知道：

- 什么时候走 RAG
- RAG 在图里的位置
- 入口节点和终点节点是什么

3. `graph/nodes.py`

第三步必须看这个文件，因为在线主链路真正串起来的是它，不是 `rag/service.py`。

你会在这里直接看到：

- `rag_retrieve_node`
- `rag_answer_node`

以及中间状态怎么落回 state。

4. `rag/query_analyzer.py`

第四步看它，是为了补上第一个关键决策点：

- 用户一句自然语言是怎么变成 `query + filter` 的

5. `rag/retriever.py`

第五步看召回策略：

- 是否真的是 hybrid
- filter 错了怎么办
- rerank 现在有没有生效

6. `rag/generator.py`

第六步看回答生成，是为了确认：

- 生成层拿到的到底是什么上下文
- 空召回时怎么兜底

7. `config.py`

第七步专门看配置，因为很多“看上去实现了”的能力，其实默认没启用。

最关键的是这两个开关：

- `rag_enable_vector_search`
- `rag_enable_rerank`

8. `rag/indexer.py` + `rag/bm25_store.py` + `rag/vector_store.py`

最后再看离线和存储底层，因为这些文件更细、更偏基础设施。先看它们容易陷进实现细节，反而抓不住在线主线。

9. `rag/loaders.py`、`rag/cleaner.py`、`rag/splitter.py`、`rag/metadata.py`

这些最适合最后看。原因不是它们不重要，而是它们更像“索引质量来源层”。当你已经理解主链路后，再看它们，就会知道每个细节为什么会影响召回。


# 8. 最小排障闭环

如果用户说“这个 RAG 问题答得不对”，我建议第一轮排查严格按下面顺序走。

1. 先确认请求是否真的走到了 RAG 路径

- 看 `chat agent finished` 的 `intent`
- 看 `node rag_retrieve finished` 是否出现

如果根本没走 RAG，后面所有检索排查都不用做。

2. 看 `query_analyzer` 最终产出的 filter 对不对

- 先问自己：这句用户话本来应该落到哪个 `category`
- 再对照日志和 state 里的 `retrieval_filters`

因为当前系统强依赖规则 filter 来缩小范围，这一步错了，后面通常都会偏。

3. 看 `retrieval_query` 是否保留了关键术语

尤其是：

- `ACCOS`
- `PI967`
- `声明文件`
- `报关品名清单`

如果关键术语被清洗掉，召回必然变差。

4. 看 retriever 实际召回了什么

- 看 `bm25_hits`
- 看 `vector_hits`
- 看 `final_docs`

如果 `final_docs = 0`，先分清：

- 是真的没索引
- 还是 filter 过严
- 还是向量检索被禁用了

5. 直接抽查 top docs 内容

这是最实战的一步。

不要只看命中数量，要看前几条 chunk 的：

- `source_file`
- `page_content`

如果召回到的文本就和问题无关，那问题已经在生成前出现了。

6. 确认是不是离线建库缺失

如果某类问题始终查不到，重点检查：

- `data/cache/bm25.pkl` 是否存在
- 对应源文件是否在 `data/docs`
- `.doc` 文件是否因 Word/`pywin32` 缺失被跳过

7. 最后才看 generator / prompt

只有在“召回上下文已经对了”的前提下，才值得怀疑：

- `RAG_ANSWER_SYSTEM`
- 模型输出

否则改 prompt 只是掩盖检索问题。


# 9. 三个最值得做的小实验

## 实验 1：关闭规则 filter，观察召回污染

### 改动什么

- 临时让 `rag/query_analyzer.py` 的 `_rule_based_analysis()` 恒返回 `None`
- 或者在 `analyze_query()` 里忽略规则结果，强制只返回 `_normalize_query(question)` 和 `filters=None`

### 预期会看到什么现象

- `锂电池货物需要什么声明文件` 这类问题会更容易召回到其他类别资料
- `final_docs` 可能不变，但前几条 chunk 的业务域会变杂

### 它能帮助理解哪一层

- 帮你直观看到 `metadata filter` 不是“锦上添花”，而是当前系统控制噪音的关键层


## 实验 2：只保留 BM25，再和开启向量检索对比

### 改动什么

- 保持当前默认配置跑一遍
- 再把 `config.py` 或 `.env` 里的 `rag_enable_vector_search` 打开，重跑相同问题

### 预期会看到什么现象

- 术语型问题可能差异不大
- 语义表达更松散的问题，向量检索可能补到一些 BM25 没抓住的片段
- 也可能暴露向量检索超时后被熔断的问题

### 它能帮助理解哪一层

- 帮你验证当前项目到底是“BM25 主导”还是“真正 hybrid 主导”
- 也能顺手验证 `vector_store` 的超时保护是否生效


## 实验 3：打印 generator 真正拿到的 context

### 改动什么

- 在 `rag/generator.py` 临时打印 `_format_docs(retrieved_docs)` 的结果

### 预期会看到什么现象

- 你能直接看到模型是在什么上下文上作答
- 很多“模型答偏了”的问题，实际会暴露成“上下文本身就混了”或“关键片段根本没进 prompt”

### 它能帮助理解哪一层

- 帮你区分检索问题和生成问题
- 这是排障时最省时间的实验之一


# 10. 最后给一个“带着问题读代码”的版本

下面这组问题更适合边读边想，不是函数说明题。

- 为什么 query 改写放在 `query_analyzer`，而不是 `retriever`
- 为什么 filter 失败后要退到无 filter，而不是直接告诉用户“没找到”
- 当前系统更怕召回不足，还是更怕召回噪音
- 如果把 `rag_enable_vector_search` 打开，当前排序公式 `bm25_score - vector_score` 真的稳吗
- 为什么在线主链路没有直接走 `rag/service.py`
- 为什么 generator 不自己再做一次检索
- 如果 chunk 切得更大，最先感受到副作用的是 BM25、向量检索，还是 generator prompt
- 为什么 BM25 选择“先全量打分再过滤”，而不是“先过滤再打分”
- 为什么向量检索一旦超时，就直接全局禁用，而不是继续重试
- `.doc` 文件解析依赖 Word COM，这个选择对部署环境意味着什么
- 当前前端为什么拿不到 `retrieval_query` 和 `retrieved_docs`
- 如果用户说“这题昨天还能答，今天答不了了”，第一反应应该查在线链路还是离线建库产物
- `FALLBACK_RESPONSES["rag"]` 还留着，但 graph 已不再走这条路，这代表了什么样的演进痕迹
- 当前系统更像“检索优先，生成保守”还是“生成优先，检索宽松”
- 如果未来文档从 8 份涨到 800 份，最先扛不住的会是哪一层


## 附：基于真实代码的几条结论

- 当前在线 RAG 链路已经接通，不再是 `rag -> fallback`
- 当前默认运行态不是“完全体混合检索”，而是“BM25 主召回，向量检索和 rerank 都是配置预留”
- `rag/service.py` 是存在的，但在线请求并不直接经过它
- 离线建库质量会直接决定在线召回上限，尤其是 `.doc` 解析和 metadata 配置
- 如果要做第一轮排障，最省时间的不是改 prompt，而是先看 `intent -> filter -> retrieved_docs`
