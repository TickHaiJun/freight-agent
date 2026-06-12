# 日志标准化与平台化实施方案

## 1. 目标

这份方案只覆盖日志，不处理 RAG。

目标分 4 个阶段，与你确认的一致：

1. 先把日志字段标准化
2. 再把文本日志转成稳定 JSON
3. 再做 UI 查询、筛选、会话回放
4. 最后再加 AI 总结、异常聚类、原因建议

这次输出的重点是：

- 日志落盘方式
- 日志字段标准
- 日志事件分层
- 文本日志到 JSON 日志的处理方式
- 后续前端平台可消费的数据结构
- 真实实现时建议修改的技术点

---

## 2. 基于当前 `history.log` 的现状判断

### 2.1 现有日志的优点

当前日志已经有一些正确方向：

1. 已经有 `session_id`
2. 已经有节点级日志，例如 `intent / slot / tool / result / rag_retrieve / rag_answer`
3. 已经有耗时字段，例如 `elapsed`
4. 已经能看到关键业务状态，例如 `intent`、`query_ready`、`missing`、`filters`、`exact_quotes`

这些是后续做问题定位和前端可视化的基础。

### 2.2 现有日志的主要问题

基于 `history.log`，当前日志有 6 个结构性问题：

#### 问题 1：日志来源混杂

当前 `history.log` 混在一起了：

1. `uvicorn` 服务日志
2. `FastAPI` 请求访问日志
3. 应用层 `main` 日志
4. `graph.nodes` 节点日志
5. `tools.air_freight` 工具日志
6. `rag.*` 检索与生成日志

对人眼还能看，对 UI 和 JSON 化不友好。

#### 问题 2：日志格式不完全稳定

当前很多日志是：

```text
event text | key=value | key=value
```

这方向是对的，但不同模块字段名、字段顺序、事件名还不完全统一。

#### 问题 3：单条日志体积过大

`generate debug` 现在会把这些整段打进去：

1. `request.context`
2. `initial_state`
3. `latest_quote_result`
4. 整批 `quotes`
5. 整段 `rag_answer`

这会带来几个问题：

1. 日志文件膨胀很快
2. 一条日志过长，不适合前端按行展示
3. 不利于后续 JSON 化
4. 同一请求的核心结论被大段噪声淹没

#### 问题 4：事件层级还不够明确

虽然有 `intent_node rule hit`、`node slot finished` 这类日志，但还没有统一的事件类型，例如：

- `request_started`
- `intent_decided`
- `slot_extracted`
- `quote_api_called`
- `quote_api_succeeded`
- `rag_retrieval_finished`
- `request_completed`

后续做前端筛选时，如果没有稳定的 `event_name`，只能依赖文本模糊匹配。

#### 问题 5：缺少统一的结果摘要字段

例如报价结果现在经常把完整 `latest_quote_result` 打进去，但真正给 UI 和分析平台更有价值的其实是：

1. 报价模式
2. 命中条数
3. 最低价
4. 最低价对应航司/航线
5. 是否多始发港

而不是整批原始报价对象。

#### 问题 6：没有天然可直接消费的 JSON 日志

目前 `history.log` 更像“人工阅读型”日志，不是“系统消费型”日志。

---

## 3. 我们要采用的总体方案

### 3.1 总体原则

这次我建议采用“单次埋点，双份输出”的方案：

1. 业务代码内部先统一事件对象
2. 同一事件同时输出：
   - 人类可读文本日志 `.log`
   - 机器可读 JSON Line 日志 `.jsonl`

这样就能满足两类场景：

1. 终端和服务器排查时，直接看文本日志
2. 前端平台和后续 AI 分析时，直接消费 JSON Line

### 3.2 为什么不用“先纯文本，后脚本离线转 JSON”

离线转换不是不能做，但不建议作为主链路。

原因：

1. 一旦文本日志字段不一致，离线转换会越来越脆
2. 长文本字段、嵌套字典、异常堆栈很难稳定解析
3. 后续做实时 UI 时还要再做增量解析

所以更好的方式是：

- 第一阶段仍保留文本日志
- 但从实现那一刻开始，底层埋点就生成结构化事件
- 文本日志和 JSON 日志都从这个统一事件对象渲染出来

---

## 4. 日志落盘方式

### 4.1 目录策略

按你确认的双环境策略：

- 本地开发：`docs/history`
- 云服务器：`/data/logs/freight-agent/`

通过配置切换，不写死。

### 4.2 文件策略

建议输出 3 类文件：

1. `freight-agent-app.log`
2. `freight-agent-app.jsonl`
3. `freight-agent-error.log`

第一版不建议把日志拆太细，先控制在这 3 类。

含义：

- `app.log`：人工阅读主日志
- `app.jsonl`：前端平台与 AI 分析主数据源
- `error.log`：仅错误和异常事件

### 4.3 滚动策略

使用按天滚动：

- 每天一个逻辑日志周期
- 保留最近 `30` 天或配置化天数

实现层建议使用：

- `TimedRotatingFileHandler`

### 4.4 控制台策略

建议保留控制台输出，但不要再依赖：

```powershell
uvicorn ... > history.log
```

原因：

1. 这样会把 `uvicorn`、访问日志、应用日志全部混成一个文件
2. 会破坏结构化日志边界
3. 不适合后续日志平台

更合理的方式是：

1. 应用代码自己负责落盘
2. 控制台仅作运行时观察
3. 如需保留 access log，也单独处理

---

## 5. 基于真实 `history.log` 提炼出来的标准字段

下面这些字段不是拍脑袋设计的，而是基于当前 `history.log` 已经出现或明显需要出现的字段抽出来的。

### 5.1 通用字段

所有日志事件都应该统一带：

- `ts`
- `level`
- `logger`
- `event`
- `session_id`
- `request_id`
- `message_text`
- `elapsed_ms`
- `env`
- `service`
- `module`

说明：

- `event` 是后续 UI 和 AI 分析最关键的字段
- `request_id` 建议新增，区分同一个 `session_id` 下的多次请求

### 5.2 HTTP / 请求生命周期字段

适用于 `main.py` 级别事件：

- `client_ip`
- `http_method`
- `path`
- `reset_quote_context`
- `request_started_at`
- `request_completed_at`
- `stream_completed`
- `cancelled`
- `total_elapsed_ms`

### 5.3 对话理解字段

适用于 `intent`、`support_info`、`fallback` 等决策事件：

- `intent`
- `support_info_kind`
- `query_subtype`
- `response_mode`
- `quantity_mode`
- `decision_source`
- `rule_hit`
- `llm_used`

说明：

- `decision_source` 建议取值：`rule` / `llm` / `fallback`
- `rule_hit` 对应“命中了哪个规则”

### 5.4 槽位 / 业务上下文字段

适用于报价主链路：

- `sfg`
- `mdg`
- `input_weight`
- `input_vol`
- `hbrq`
- `hbrq_begin`
- `hbrq_end`
- `flight_type`
- `package_type`
- `cargo_type`
- `two_code`
- `gid`
- `query_ready`
- `query_completed`
- `missing_slots`
- `cleared_fields`

### 5.5 挂起与追问字段

这些字段当前项目里很关键，必须进入日志 schema：

- `pending_action_type`
- `pending_action_prompt`
- `pending_action_retry_count`
- `pending_clarify_slot`
- `pending_reuse_confirmation`
- `reuse_confirmation_decision`

说明：

后面你做异常定位时，“为什么没继续追问”“为什么直接查价”“为什么复用上轮参数”都要靠这些字段还原。

### 5.6 报价结果字段

不建议再整段记录 `latest_quote_result`，建议改成结果摘要字段：

- `search_mode`
- `quote_count_exact`
- `quote_count_similar`
- `quote_count_total`
- `best_price_total`
- `best_unit_price`
- `best_carrier`
- `best_route`
- `best_route_type`
- `best_origin`
- `multi_origin`
- `result_display_mode`

如果用户触发“全部数据”或结果分析，还建议记录：

- `result_analysis_intent`
- `result_analysis_filters`
- `result_reference_field`
- `result_reference_request`

### 5.7 工具调用字段

适用于 `tools.air_freight`：

- `tool_name`
- `tool_status`
- `api_base`
- `api_path`
- `api_status_success`
- `api_status_code`
- `tool_elapsed_ms`
- `request_params_summary`

注意：

- `request_params_summary` 记录业务参数摘要即可
- 不建议把下游完整响应原样长期打入主日志

### 5.8 RAG 字段

适用于后续 RAG 链路观测：

- `rag_query`
- `retrieval_query`
- `retrieval_filters`
- `retrieval_mode`
- `vector_search_enabled`
- `vector_hits`
- `bm25_hits`
- `final_docs`
- `generator_docs`
- `rag_answer_length`

### 5.9 错误与异常字段

所有 WARNING / ERROR / EXCEPTION 统一带：

- `error_type`
- `error_message`
- `error_stage`
- `stacktrace`
- `retryable`
- `degraded`

说明：

- `error_stage` 非常重要，建议取值例如：`intent` / `slot` / `tool` / `rag_retrieve` / `rag_answer` / `stream`

---

## 6. 哪些字段不应再直接进主日志

基于当前 `history.log`，以下内容不建议再整段打到主日志：

1. `initial_state` 全量字典
2. `request.context` 全量字典
3. `latest_quote_result` 全量对象
4. `quotes` 全量数组
5. `rag_answer` 全文
6. 用户长文本在多处重复打印

替代方案：

1. 主日志只打摘要字段
2. 需要深度排查时，再单独输出调试日志
3. 调试日志也要可控开关，例如 `APP_LOG_DEBUG_STATE=false`

---

## 7. 日志事件分层方案

为了让 UI 和 AI 分析真正可用，建议统一事件命名。

### 7.1 请求生命周期事件

- `request_started`
- `request_cancelled_before_invoke`
- `request_cancelled_during_stream`
- `request_completed`

### 7.2 对话路由事件

- `intent_reset_detected`
- `intent_decided`
- `support_info_selected`
- `fallback_selected`

### 7.3 报价链路事件

- `slot_extracted`
- `slot_validation_failed`
- `clarify_requested`
- `tool_invoked`
- `tool_succeeded`
- `tool_failed`
- `quote_result_generated`
- `quote_result_analysis_generated`

### 7.4 RAG 链路事件

- `rag_query_analyzed`
- `rag_retrieve_started`
- `rag_vector_skipped`
- `rag_retrieve_retry_without_filters`
- `rag_retrieve_completed`
- `rag_answer_generated`

### 7.5 异常与退化事件

- `degraded_to_fallback`
- `api_error_detected`
- `vector_search_disabled`
- `unexpected_exception`

---

## 8. 文本日志与 JSON 日志的关系

### 8.1 文本日志格式

文本日志建议仍保持人可读：

```text
2026-06-11 14:10:00,123 INFO [graph.nodes] event=slot_extracted session_id=... request_id=... intent=rate_query query_ready=true sfg=nkg,pvg mdg=lax input_weight=890 input_vol=9 package_type=托盘 missing_slots=[]
```

特点：

1. 一行一个事件
2. 结构稳定
3. 没有超长嵌套对象

### 8.2 JSON 日志格式

同一个事件同步输出到 `.jsonl`：

```json
{
  "ts": "2026-06-11T14:10:00.123+08:00",
  "level": "INFO",
  "logger": "graph.nodes",
  "event": "slot_extracted",
  "session_id": "web_xxx",
  "request_id": "req_xxx",
  "intent": "rate_query",
  "query_ready": true,
  "sfg": "nkg,pvg",
  "mdg": "lax",
  "input_weight": 890,
  "input_vol": 9,
  "package_type": "托盘",
  "missing_slots": []
}
```

### 8.3 结论

不是“先写文本，再离线转 JSON”，而是：

1. 先统一事件对象
2. 同时渲染文本和 JSON

这样最稳。

---

## 9. 前端平台如何消费这些日志

### 9.1 第一阶段 UI 能力

基于 `.jsonl`，前端先做最有价值的功能：

1. 按日期加载
2. 按 `session_id` 聚合查看
3. 按 `event` 筛选
4. 按 `intent`、`error_stage`、`tool_status` 筛选
5. 展示一次请求的完整事件时间线

### 9.2 第二阶段可视化指标

可以直接从 JSON 日志聚合：

1. 每日请求数
2. 问价请求占比 / RAG 请求占比 / support_info 占比
3. 追问率
4. fallback 率
5. 报价 API 失败率
6. 平均响应耗时
7. RAG 空召回率

### 9.3 第三阶段 AI 分析

AI 更适合做：

1. 异常聚类
2. 高频错因总结
3. 请求链路摘要
4. 风险模式识别

例如：

- 缺始发港却未触发追问
- 新询价被误判为结果分析
- RAG filter 错误导致反复无召回

---

## 10. 技术实现方案

### 10.1 新增独立日志模块

建议新增独立模块，例如：

- `logging_config.py`
- `logging_schema.py`

职责拆分：

#### `logging_schema.py`

负责：

1. 定义标准事件字段
2. 定义事件构造 helper
3. 统一脱敏与截断规则

#### `logging_config.py`

负责：

1. 初始化日志目录
2. 配置控制台、文本文件、JSON 文件 Handler
3. 配置按天滚动
4. 配置错误日志单独输出

### 10.2 埋点方式

不要继续直接在各处手写超长字符串。

建议逐步改成：

```python
logger.info("event=%s", event_name, extra={...})
```

或者封装：

```python
log_event(logger, event="slot_extracted", session_id=..., ...)
```

我更推荐第二种，原因：

1. 字段统一
2. 更容易补默认值
3. 更容易同时输出文本和 JSON

### 10.3 关键改动位置

如果后续实现，主要会影响这些位置：

- `config.py`
- `main.py`
- `graph/nodes.py`
- `tools/air_freight.py`
- `rag/query_analyzer.py`
- `rag/retriever.py`
- `rag/generator.py`
- 新增 `logging_config.py`
- 新增 `logging_schema.py`

### 10.4 配置项建议

建议增加：

```env
APP_LOG_DIR=./docs/history
APP_LOG_LEVEL=INFO
APP_LOG_BACKUP_DAYS=30
APP_LOG_JSON_ENABLED=true
APP_LOG_DEBUG_STATE=false
APP_LOG_ACCESS_ENABLED=true
APP_LOG_REDACT_USER_MESSAGE=false
```

### 10.5 脱敏与截断策略

后续平台化前必须提前做规则：

1. 用户 message 默认保留，但允许配置脱敏
2. `quotes` 全量数组不入主日志
3. `rag_answer` 只记录长度和摘要，不记录全文
4. 超长字段统一截断，例如 `max_len=500`

---

## 11. 推荐实施顺序

### 第一阶段：结构统一

目标：

1. 替换现在的超长 debug 日志
2. 给所有关键事件加 `event`
3. 补 `request_id`
4. 统一字段命名

### 第二阶段：双格式落盘

目标：

1. `app.log`
2. `app.jsonl`
3. `error.log`
4. 按天滚动

### 第三阶段：日志数据消费

目标：

1. 做日志读取脚本或接口
2. 支持按日期和 `session_id` 查询
3. 支持时间线回放

### 第四阶段：AI 分析

目标：

1. 从 `.jsonl` 提取异常模式
2. 自动输出错因摘要
3. 支持聚类和建议

---

## 12. 风险点

### 12.1 最大风险

如果继续沿用现在这种“日志里塞完整状态对象”的方式，后面前端平台一定很难做。

### 12.2 第二风险

如果文本日志和 JSON 日志不是从同一事件对象生成，后面两边会逐渐不一致。

### 12.3 第三风险

如果不先定义 `event` 和字段标准，后续 UI 只能做模糊搜索，分析价值会大幅下降。

---

## 13. 验证方案

真正实现后，建议至少验证这些点：

1. 本地运行后 `docs/history` 自动生成：
   - `freight-agent-app.log`
   - `freight-agent-app.jsonl`
   - `freight-agent-error.log`
2. 单次 `/api/chat` 请求在 JSON 日志中能按 `request_id` 查到完整事件链
3. 一次报价请求至少有：
   - `request_started`
   - `intent_decided`
   - `slot_extracted`
   - `tool_succeeded`
   - `quote_result_generated`
   - `request_completed`
4. 一次 RAG 请求至少有：
   - `request_started`
   - `intent_decided`
   - `rag_query_analyzed`
   - `rag_retrieve_completed`
   - `rag_answer_generated`
   - `request_completed`
5. `generate debug` 这类超长日志被替换为摘要型事件
6. 日志跨天自动滚动

---

## 14. 结论

这次日志方案我建议明确采用：

1. 统一事件对象
2. 双格式落盘：文本 `.log` + JSON Line `.jsonl`
3. 严格事件命名与字段标准化
4. 主日志只保留摘要，不保留整批大对象
5. 前端平台直接消费 `.jsonl`
6. AI 分析建立在结构化日志之上，而不是原始自由文本之上

这套方案比“先把终端输出重定向到一个大文本文件，后面再慢慢解析”更适合你现在这个 Agent 项目，也更适合后续做问题定位和产品化监控。
