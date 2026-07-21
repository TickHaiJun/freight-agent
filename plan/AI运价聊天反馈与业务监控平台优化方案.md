# AI 运价聊天反馈与业务监控平台优化方案

## 1. 目标与结论

本期处于内部线上测试阶段，目标不是立刻建设完整工单系统或数据库，而是在**不影响既有 `/api/chat` SSE 协议和运价查询链路**的前提下，补上“用户觉得 AI 回复不好”的闭环：

```text
聊天窗口点“不满意”
  → 前端弹窗提交反馈
  → POST /api/chat-feedback
  → 服务端补充时间、反馈 ID、链路摘要
  → AI 结构化归类 / 打 Tag
  → 追加写入反馈 JSONL 文件
  → Next 日志平台读取、聚合、可视化与复盘
```

推荐本期采用“**独立反馈接口 + 独立 JSONL 文件 + AI 标签增强 + Next 后端读取**”。在预计只有 2,000～2,500 条内部测试反馈的规模下，文件存储完全可行，且迁移至数据库时可按 `feedback_id` 原样导入。

### 1.1 一个重要调整：不用单个 JSON 数组文件，改用 JSONL

用户提出“动态追加到 JSON 文件”的方向正确，但不建议存成下面这种持续改写的数组：

```json
[
  { "...": "..." },
  { "...": "..." }
]
```

原因是每提交一次都要读取整个文件、修改结尾逗号并重写文件；并发提交或进程中断时容易损坏整个文件。

推荐保存为 `chat-feedback.jsonl`：每行是一条完整 JSON 对象。例如：

```json
{"record_type":"feedback","feedback_id":"fb_...","created_at":"2026-07-15T10:30:00+08:00", "...":"..."}
{"record_type":"feedback","feedback_id":"fb_...","created_at":"2026-07-15T10:32:00+08:00", "...":"..."}
```

它仍然是 JSON 数据，优点是可以 `append` 追加写入、逐行容错解析、便于按天轮转，也与现有 `freight-agent-app.jsonl` 日志体系一致。Next 平台后端读取后，向页面返回普通 JSON 数组即可，前端无需感知 JSONL。

## 2. 现状与影响范围

已核对当前实现与原《AI运价日志监控平台方案》：

- `/api/chat` 是 SSE 接口；服务端在每次请求中生成 `request_id`，前端请求使用 `session_id`。
- 结构化日志已写入 `/data/logs/freight-agent/`，并记录 `request_started`、`agent_finished`、`request_completed`、`request_failed` 等事件。
- `request_id + session_id` 已是将反馈、单次请求、完整会话串联起来的可靠主键组合。
- 平台方案已经具备总览、请求、会话、异常、运价链路、RAG 监控等技术视图；本次新增的是“面向业务人员的反馈与质量运营视图”。

### 2.1 本期原则

1. **不改 `/api/chat` 的请求结构和事件类型。** 如需把当前轮 `request_id` 给前端，仅在既有 `context` 事件中增加可选字段 `request_id`，属于向后兼容的扩展。
2. **反馈与运行日志分文件保存。** 不把人工文字反馈混入应用 JSONL 日志，避免权限、检索、留存策略互相污染。
3. **用户选择的问题类型与 AI 标签分开保存。** 前者是用户主观感受，后者是模型的辅助判断；两者不能互相覆盖。
4. **先留痕，后分析。** 反馈的原始内容必须先稳定保存；AI 超时或失败不能导致反馈丢失。
5. **不引入新数据库或重型消息队列。** 仅新增项目内小模块、配置和 Next 平台读取接口。

## 3. 反馈接口设计

### 3.1 接口契约

```http
POST /api/chat-feedback
Content-Type: application/json
```

建议响应为普通 JSON，不使用 SSE：

```json
{
  "feedback_id": "fb_20260715_xxx",
  "status": "accepted",
  "ai_analysis_status": "completed"
}
```

接口失败不会影响已经完成的聊天回答；它是聊天主链路之外的独立能力。

### 3.2 前端请求字段

| 字段 | 必填 | 产生方 | 说明 |
|---|---:|---|---|
| `session_id` | 是 | 前端缓存 | 当前聊天窗口 ID，用于关联完整会话。 |
| `request_id` | 强烈建议 | `/api/chat` context | 被反馈的那一轮 AI 回复 ID，是最重要的关联字段。 |
| `feedback_text` | 是 | 用户填写 | 用户认为不满意的具体原因，建议 5～1,000 字。 |
| `dissatisfaction_types` | 是 | 用户多选 | 用户可感知的问题类型，见下方枚举。 |
| `user_question` | 是 | 前端当前轮缓存 | 当前轮用户问题快照，最多 2,000 字。 |
| `assistant_answer` | 是 | 前端当前轮缓存 | 被反馈的 AI 完整回答或截断快照，最多 6,000 字。 |
| `conversation_excerpt` | 否 | 前端 | 最近 2～3 轮必要上下文；最多 6,000 字。第一版可不传。 |
| `page_url` | 否 | 前端自动 | 便于区分门户页面 / 测试环境。 |
| `client_version` | 否 | 前端自动 | 前端发布版本或 Git SHA，定位展示与交互问题。 |
| `client_feedback_id` | 否 | 前端生成 | 防止双击或网络重试造成重复提交；UUID 即可。 |

不建议让前端提交 `created_at`、`feedback_id`、AI 标签、处理状态、严重等级等字段：这些应由服务端生成或维护，避免被篡改。

### 3.3 用户在弹窗中看到的字段

为了降低填写成本，弹窗只展示必要内容：

1. 标题：“这条回答哪里没有帮到你？”
2. 多选问题类型（至少选择一个）。
3. “具体说明”文本框。
4. 可选开关：“允许我们带上本轮问答内容用于排查”（内部测试建议默认开，但需明确提示）。
5. 提交按钮；成功后提示“反馈已提交，感谢帮助我们改进”。

推荐的 `dissatisfaction_types` 枚举：

```text
incorrect_answer          回答不正确 / 与业务不符
incomplete_answer         回答不完整
misunderstood_question    没理解我的问题
quote_result_issue        运价、航线或报价结果不符合预期
clarification_issue       追问不合理 / 重复追问
knowledge_issue           知识问答没有解决问题
slow_response             响应太慢
display_issue             页面展示或流式内容有问题
other                     其他
```

“不满意的点”应采用多选加文字补充，而不是只留一个自由文本框；这样业务统计有稳定口径，用户仍能表达细节。

## 4. 服务端落盘记录：字段分层

一条完整反馈记录建议由以下五层组成。字段不必全部前端填写。

### 4.1 身份、时间与幂等字段

```json
{
  "record_type": "feedback",
  "schema_version": 1,
  "feedback_id": "fb_01J...",
  "client_feedback_id": "uuid-from-client",
  "created_at": "2026-07-15T10:30:12+08:00",
  "source": "web_chat",
  "session_id": "session_xxx",
  "request_id": "req_xxx"
}
```

- `created_at` 必须由服务器按北京时间生成。
- `feedback_id` 必须由服务器生成，推荐 UUID/ULID，不采用易冲突的时间戳。
- `schema_version` 为以后迁移、字段扩展保留。
- `client_feedback_id` 用于接口幂等：同一个值再次提交时返回原结果，不重复追加。

### 4.2 用户反馈与问答快照

```json
{
  "user_feedback": {
    "dissatisfaction_types": ["misunderstood_question", "incomplete_answer"],
    "feedback_text": "我问的是含电池货物，回答却按普货给了建议。",
    "allow_context_for_review": true
  },
  "conversation_snapshot": {
    "user_question": "锂电池货物怎么订舱？",
    "assistant_answer": "……",
    "conversation_excerpt": []
  }
}
```

这部分应保留原文，但实施长度上限与简单脱敏：手机号、邮箱、身份证号、订单号等可先遮罩。若内部测试需要保留原始订单信息，应先明确权限与留存期限。

### 4.3 服务端关联的链路摘要

服务端根据 `request_id` 从内存或当日 JSONL 日志中提取可用信息，保存轻量快照，不复制整份原始日志：

```json
{
  "trace_snapshot": {
    "intent": "rate_query",
    "query_ready": true,
    "tool_status": "succeeded",
    "error_type": null,
    "total_elapsed_ms": 1840.23,
    "origin": "SHA",
    "destination": "LAX",
    "retrieved_docs_count": null
  }
}
```

这个快照让日志平台可直接聚合，同时仍能通过 `request_id` 跳转到完整请求详情。若查不到 `request_id`，记录 `trace_found=false`，但仍接受反馈，不能因此拒绝用户。

### 4.4 AI 分析结果

AI 的职责是**结构化归因和归类**，不是替代人工判定，也不应生成虚构结论。建议 JSON 结构：

```json
{
  "ai_analysis": {
    "status": "completed",
    "model": "deepseek-chat",
    "analyzed_at": "2026-07-15T10:30:15+08:00",
    "summary": "用户认为系统将含电池场景识别为普货，导致回答不匹配。",
    "quality_tags": ["intent_or_entity_misunderstanding", "cargo_type_recognition"],
    "business_domain": "dangerous_goods",
    "pipeline_stage": "slot_extraction",
    "root_cause_hypothesis": "需要复核货物属性抽取及提示词覆盖范围。",
    "severity": "medium",
    "confidence": 0.78,
    "recommended_action": "回放该 request_id，核对 cargo_type 和槽位提取日志。",
    "needs_human_review": true
  }
}
```

建议控制 AI 输出为 Pydantic/JSON Schema 允许的枚举，禁止自由扩散标签。第一版标签体系：

| 维度 | 推荐标签 |
|---|---|
| 业务域 | `rate_query`、`rag`、`support_info`、`unknown`、`mixed` |
| 链路阶段 | `intent_classification`、`slot_extraction`、`clarification`、`freight_tool`、`result_generation`、`rag_retrieval`、`rag_generation`、`frontend_display`、`unknown` |
| 问题性质 | `wrong_answer`、`missing_information`、`misunderstanding`、`tool_or_data_issue`、`knowledge_gap`、`latency`、`display_issue`、`policy_or_prompt_gap`、`not_reproducible` |
| 业务细分 | `origin_destination`、`weight_volume`、`cargo_type`、`battery_dangerous_goods`、`date_flight_type`、`quote_availability`、`price_explanation`、`document_process`、`other` |
| 严重度 | `low`、`medium`、`high`、`critical` |

### 4.5 人工闭环字段（为后续预留）

本期可不做页面编辑功能，但数据结构应预留：

```json
{
  "workflow": {
    "status": "new",
    "owner": null,
    "resolution_type": null,
    "resolution_note": null,
    "resolved_at": null
  }
}
```

状态可为 `new`、`triaged`、`in_progress`、`resolved`、`wont_fix`、`duplicate`。后续不应直接改旧 JSONL 行，而是追加 `record_type=feedback_update` 事件并按 `feedback_id` 聚合，以保持文件写入安全。

## 5. AI 分析流程与可靠性设计

### 5.1 推荐流程：先原始反馈落盘，再做 AI 增强

这是本需求最关键的可靠性设计：

```text
校验请求 / 幂等检查
  → 立即 append 一条 feedback（ai_analysis.status=pending）
  → 调用 AI 进行结构化标签分析（严格超时）
  → append 一条 feedback_enrichment（同 feedback_id）
  → 返回 accepted / completed / pending
```

Next 平台按 `feedback_id` 聚合这两类事件，最终展示一条反馈。

这样，即使 DeepSeek 超时、模型返回格式非法、网络抖动或服务重启，用户反馈也已经落地，不会因“AI 没分析成功”而丢失。AI 失败时保留 `status=failed` 与错误摘要，并可由平台提供“重新分析”按钮。

如果内部测试强烈希望接口响应中立即拿到 AI 标签，可在保存原始反馈后同步等待 5～8 秒；超时则返回 `pending`。但不要把“AI 成功”作为反馈保存的前置条件。

### 5.2 AI 的输入边界

AI 输入应仅包含：

- 用户填写的反馈类型和文字；
- 当前轮用户问题与 AI 回答；
- 最近必要对话摘要；
- `trace_snapshot` 的结构化字段；
- 明确的标签枚举与“证据不足时输出 unknown”的要求。

不要直接把全量 JSONL、API Key、完整堆栈、所有历史会话输入模型。这样能控制成本、降低敏感信息风险，也避免模型被无关噪声误导。

### 5.3 AI 输出约束

Prompt 要求：

1. 只返回指定 JSON Schema；
2. 基于已给内容归类，不确定时降低 `confidence` 并标记人工复核；
3. `root_cause_hypothesis` 必须使用“可能/需复核”，不能表述为事实；
4. 不复述敏感原文，不生成客户联系方式、价格或政策之外的事实；
5. 不将用户的主观不满自动认定为系统故障。

## 6. 文件目录、配置与并发写入

### 6.1 推荐目录

线上环境推荐将反馈文件放在与应用日志同一个受控父目录、但分开子目录：

```text
/data/logs/freight-agent/
  freight-agent-app.jsonl
  feedback/
    chat-feedback.jsonl
    chat-feedback.jsonl.2026-07-15   # 后续按日归档，可选
```

本地开发默认：

```text
./data/feedback/chat-feedback.jsonl
```

不要放在仓库根目录，也不要让浏览器以静态文件方式直接访问。生产路径通过配置控制，避免代码中硬编码服务器目录。

### 6.2 建议新增配置

```env
CHAT_FEEDBACK_ENABLED=true
CHAT_FEEDBACK_DIR=/data/logs/freight-agent/feedback
CHAT_FEEDBACK_FILE_PREFIX=chat-feedback
CHAT_FEEDBACK_MAX_TEXT_LENGTH=1000
CHAT_FEEDBACK_MAX_ANSWER_LENGTH=6000
CHAT_FEEDBACK_AI_ENABLED=true
CHAT_FEEDBACK_AI_TIMEOUT_SECONDS=8
CHAT_FEEDBACK_RETENTION_DAYS=180
```

### 6.3 并发与文件完整性

单进程内部使用异步锁或线程锁；多 worker / 多容器部署时使用系统文件锁（Linux `flock`）或改为“按进程/日期分片文件”，避免两次写入互相穿插。每次写入：

1. `json.dumps(..., ensure_ascii=False)` 生成单行；
2. 追加换行；
3. flush，必要时 `fsync`；
4. 捕获写入异常并返回明确的 5xx；
5. 记录 `chat_feedback_received`、`chat_feedback_ai_completed`、`chat_feedback_ai_failed` 应用事件，但日志中只记录 ID 与摘要，不重复记录用户全文。

2,500 条记录通常只有数 MB 到数十 MB，文件读取和聚合无压力；当接近 10,000 条、需要多人编辑/检索、或部署多实例时，应迁移 SQLite/PostgreSQL。

## 7. 为关联 request_id 需要的最小改动

当前 `request_id` 在 `/api/chat` 内部生成并写日志，前端无法可靠获得它。要使反馈精确回链，推荐在现有 SSE 的 `context` 事件中新增：

```json
{
  "type": "context",
  "context": {
    "...existing fields": "...",
    "request_id": "req_xxx"
  }
}
```

这是向已有 `context` 对象添加可选字段，不改变 `text`、`context`、`done`、`error` 事件类型，也不改变其他字段含义。旧前端忽略该字段仍能正常工作；新前端将它与本轮“用户问题 + AI 最终回答”一起缓存，点击反馈时提交。

若暂时完全不能修改 `/api/chat` 返回内容，反馈接口可只接收 `session_id` 与问答快照，但会失去对单次请求的精确定位；不建议作为正式方案。

## 8. Next 日志平台的优化方向

原日志方案定位为“AI 运价 Agent 排障工作台”，主要面向技术人员。新增反馈后，应在保留技术页的基础上，新增**业务质量运营层**，让非技术人员不必理解 `request_id`、`HTTP_ERROR`、槽位、RAG 检索等术语，也能看懂系统的服务质量和待处理事项。

### 8.1 两层视图，而不是一套页面满足所有人

| 层级 | 目标用户 | 主要问题 | 页面语言 |
|---|---|---|---|
| 业务质量层 | 客服、运营、业务负责人 | 今天客户是否满意？哪些问题影响最大？需要谁跟进？ | 业务语言、结论优先 |
| 技术排障层 | 开发、算法、运维 | 哪次请求在哪里失败？字段和时间线是什么？ | 链路、字段、原始日志 |

业务质量层中的每个数字都应能“下钻”到反馈列表、再下钻至请求详情；技术层仍沿用已有 `/requests`、`/sessions`、`/errors`、`/quote-monitor`、`/rag-monitor` 设计。

### 8.2 新增页面与接口

建议新增：

```text
页面
/quality                 质量总览（默认非技术首页）
/feedback                反馈工作台
/feedback/[feedbackId]   单条反馈详情与关联链路
/insights                AI 日报 / 周报 / 月报

Next Route Handlers
GET /api/feedback-summary?range=today|7d|30d
GET /api/feedback?date=...&tag=...&status=...&severity=...
GET /api/feedback/[feedbackId]
GET /api/quality-trends?range=...
GET /api/ai-insights?period=daily|weekly|monthly
```

Next 后端应读取配置的反馈目录，解析 `.jsonl`、按 `feedback_id` 合并原始记录与 AI 增强/人工更新事件；浏览器绝不直接读取服务器文件路径。

### 8.3 业务质量首页 `/quality`

页面首屏应回答“今天情况怎么样”，建议展示：

- 今日会话数、回答轮次、收到反馈数、反馈率；
- 不满意反馈数和趋势（与昨日、上周同日对比）；
- 高严重度待处理数；
- 已解决数与平均解决时长（人工流程启用后）；
- Top 5 用户不满意类型；
- Top 5 AI 标签 / 业务域；
- 受影响最多的航线、货物类型、知识主题（只有样本量达到阈值才展示）；
- “今日值得关注的 3 件事”AI 摘要；
- 最近高优先级反馈列表。

指标应同时展示分母。例如“8 条不满意反馈 / 160 次有效回复 = 5.0%”，避免仅看反馈绝对数量造成误判。

### 8.4 反馈工作台 `/feedback`

一行一条用户反馈，字段使用业务语言：

- 提交时间；
- 用户选择的问题类型；
- AI 判断的业务域、问题阶段与严重度；
- 用户反馈摘要；
- 当前处理状态；
- 是否能关联到原始请求；
- 负责人（后续）；
- “查看原对话 / 查看技术链路 / 重新 AI 分析”操作。

筛选项：时间范围、用户问题类型、AI 标签、业务域、严重度、处理状态、是否关联成功、航线/货物类型（有数据时）。不要让业务人员在默认表格中看到堆栈、原始 JSON、`request_id` 等技术字段；将其放入详情页“技术信息”折叠区。

### 8.5 反馈详情页：一条反馈的三段解释

```text
用户感受：用户认为哪里不好（原文、类型）
AI 初判：可能属于什么问题、影响级别、建议动作、置信度
事实证据：本轮问答、关联请求摘要、可跳转的完整技术链路
```

这能防止“AI 标签替代事实”。业务人员先看结论；需要时，技术人员可继续跳到已有请求时间线与原始日志。

### 8.6 报表与可视化建议

| 周期 | 适合的核心指标 | AI 应输出的结论 |
|---|---|---|
| 当天 | 反馈率、高严重度、异常陡增、Top 标签 | 今天是否需要立即处理、最值得看的样本 |
| 近 7 天 | 趋势、重复问题、状态分布、业务域分布 | 哪些问题持续出现、是否有版本/知识更新后的变化 |
| 近 30 天 | 满意度代理指标、解决率、问题 Pareto、主题演变 | 优先改什么能覆盖最多反馈、哪些问题应进入产品计划 |

图表优先级：

1. 反馈率趋势（折线）；
2. 问题类型与 AI 标签 Top N（条形图）；
3. 严重度 × 处理状态（堆叠柱）；
4. 业务域/链路阶段热力图；
5. 反馈到解决的时长分布（有人工闭环后再启用）。

不要在业务首页堆叠饼图、原始日志行数、错误堆栈等技术信息。

## 9. AI 在日志平台中的正确作用

AI 应是“解释、归并、提示优先级”的助手，而不是指标计算的唯一来源。准确的请求数、反馈数、耗时、状态分布必须由确定性聚合代码计算；AI 对这些已聚合数据做自然语言解读。

### 9.1 单条反馈 AI 归因（本期）

输入一条反馈、问答快照和 `trace_snapshot`，输出结构化标签、摘要、严重度、可能阶段、建议下一步。它是最先实现、价值最高的 AI 功能。

### 9.2 每日 AI 质量简报（第二阶段）

每天由定时任务读取已聚合指标与去重后的代表反馈，生成固定结构：

1. 今日总体质量状态（稳定 / 需关注 / 高风险）；
2. 三个最重要问题及其数量、趋势、代表反馈；
3. 新出现或显著上升的问题；
4. 建议由业务、算法、后端分别采取的行动；
5. 数据不足与不确定性说明。

报告应缓存成 JSON/Markdown 文件，避免每次打开首页都调用大模型；页面展示“生成时间、覆盖范围、样本数”。

### 9.3 周报、月报与问题聚类（第三阶段）

在确定性统计先分组后，把每组的代表反馈交给 AI 命名和总结。例如把多条“锂电池/带电货物被当作普货”的反馈归为“货物属性识别覆盖不足”。每个聚类必须给出样本数和代表反馈 ID，支持人工复核。

### 9.4 业务优先级评分

后续可用透明规则计算 `priority_score`，AI 只解释原因：

```text
priority_score = 严重度权重 + 重复出现权重 + 最近增长权重 + 是否阻塞询价权重
```

这样“优先修什么”可追溯、可调参，不会变成黑盒判断。

## 10. 实施计划

### 阶段 A：反馈采集最小闭环（建议先做）

**目标**：内部人员能提交不满意反馈，数据不丢、能关联聊天请求。

影响范围与预计修改文件：

| 文件 | 改动 |
|---|---|
| `main.py` | 新增 `POST /api/chat-feedback`；在 SSE `context` 中可选回传当前 `request_id`。 |
| `config.py` | 新增反馈目录、长度限制、AI 开关/超时等配置。 |
| `feedback/models.py`（新增） | Pydantic 请求/落盘/AI 分析模型与枚举。 |
| `feedback/store.py`（新增） | JSONL 路径、幂等检查、文件锁、追加写入、读取聚合。 |
| `feedback/service.py`（新增） | 脱敏、链路摘要提取、AI 分析编排。 |
| `feedback/prompts.py`（新增） | 结构化 AI 归因 Prompt。 |
| `tests/test_chat_feedback.py`（新增） | 参数校验、幂等、AI 失败仍落盘、JSONL 可解析测试。 |
| 前端客服项目 | 不满意按钮、弹窗、缓存 `request_id`/问答快照、提交状态。 |

验收：提交一条反馈后可在 JSONL 中看到完整原始记录；网络重复请求不重复入库；AI 超时后原始记录仍存在；原有 `/api/chat` 回归正常。

### 阶段 B：Next 反馈工作台与质量总览

**目标**：业务人员可以看今日、近 7 天、近 30 天的问题结构与待处理事项。

- 建立反馈文件访问、JSONL 解析和按 `feedback_id` 聚合层；
- 增加 `/quality`、`/feedback`、`/feedback/[feedbackId]`；
- 将反馈详情链接到原有 `/requests/[requestId]`；
- 实现确定性指标、日期筛选和导出 CSV；
- 增加最基础的人工状态更新事件（仍可写 JSONL）。

### 阶段 C：AI 日报、周报和聚类

**目标**：把“数据”转成可行动的问题清单。

- 增加每日定时汇总与缓存；
- AI 对确定性聚合结果生成日报；
- 对重复问题做聚类、展示代表样本与趋势；
- 将建议动作关联到负责人/处理状态。

### 阶段 D：迁移数据库的触发条件

以下任一情况出现时，迁移 SQLite/PostgreSQL，而不是继续扩展 JSONL：

- 反馈记录超过约 10,000 条或单文件加载明显变慢；
- 应用部署为多实例且需要严格写入一致性；
- 多人需要同时编辑状态、分配负责人、评论；
- 需要复杂全文检索、权限控制、跨月高频统计；
- 反馈成为正式生产数据，需要更强的备份、审计和保留策略。

迁移时以 `feedback_id` 为主键，将原始 `feedback`、`feedback_enrichment`、`feedback_update` 事件分别导入主表/事件表即可；本期的 schema_version 与事件化设计正是为此准备。

## 11. 风险与防护

| 风险 | 影响 | 本期控制方式 |
|---|---|---|
| 用户重复点击、网络重试 | 重复统计 | `client_feedback_id` 幂等去重。 |
| AI 服务超时或格式错误 | 反馈丢失或接口卡顿 | 原始反馈先落盘；AI 异步增强或超时转 pending。 |
| 多进程并发追加 | JSONL 行损坏 | 文件锁、单行追加、flush；多实例后迁库。 |
| 前端伪造 request_id/快照 | 错误关联 | 服务端查日志生成 trace；前端文本仅作反馈上下文，不作事实依据。 |
| 敏感信息写入 | 合规与泄露风险 | 长度限制、基础脱敏、受控目录、Next 后端读取、访问权限隔离。 |
| AI 误判 | 错误优先级 | 标签与用户类型分存，AI 输出置信度与“需人工复核”。 |
| 单一文件无限增长 | 加载变慢 | 预留按日轮转与保留期；Next 按日期加载。 |

## 12. 最终建议

1. 现在就做反馈接口是合适的，2,000～2,500 条内部测试数据使用 JSONL 足够且成本最低。
2. 必须把 `request_id` 一并带入反馈；仅有“窗口 ID + 留言”只能看趋势，难以准确定位是哪次 AI 回答出了问题。
3. 让用户填写“问题类型 + 具体说明”，让 AI 补充“业务域 + 链路阶段 + 根因假设 + 严重度”；两者共同构成质量信号。
4. 日志平台应新增面向非技术人员的质量运营层，但保留原技术排障层，并实现从业务结论到原始请求的下钻。
5. AI 的正确位置是归因、聚类、日报与行动建议；统计与状态必须由确定性程序计算。
6. 先完成阶段 A、B，确认内部人员真实使用和标签口径后，再做日报、周报、月报和数据库迁移。

