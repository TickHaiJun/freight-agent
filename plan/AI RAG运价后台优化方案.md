# AI RAG 运价后台优化方案

## 目标与边界

本文件只覆盖当前 `freight-agent` 后台的优化工作：在不破坏既有 `/api/chat` SSE 协议、前端 `context` 多轮机制与运价查询/RAG 链路的前提下，新增聊天不满意反馈采集、可靠落盘、链路关联和 AI 结构化归因。

后台不实现聊天弹窗，也不实现 Next 日志平台的质量看板、统计图表和人工工作台。

## 接口设计

### `/api/chat` 保持兼容

既有请求体和 `text`、`context`、`done`、`error` 事件类型不变。仅在原有 `context` 对象中增加可选字段 `request_id`：

```json
{"type":"context","context":{"request_id":"req_xxx"}}
```

旧前端可忽略该字段；新前端缓存它，以精确关联被反馈的单轮回答。

### `POST /api/chat-feedback`

接口返回普通 JSON，不使用 SSE：

```json
{"feedback_id":"fb_01J...","status":"accepted","ai_analysis_status":"completed"}
```

该接口独立于聊天主链路，失败不能影响已完成的聊天回答。请求字段如下：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `session_id` | 是 | 聊天窗口 ID。 |
| `request_id` | 强烈建议 | 当前轮请求 ID，由 `context` 获取。 |
| `feedback_text` | 是 | 用户具体说明，建议 5～1,000 字。 |
| `dissatisfaction_types` | 是 | 用户问题类型多选，至少一项。 |
| `user_question` | 是 | 本轮用户问题快照，最多 2,000 字。 |
| `assistant_answer` | 是 | 被反馈的回答快照，最多 6,000 字。 |
| `conversation_excerpt` | 否 | 最近 2～3 轮上下文，最多 6,000 字。 |
| `allow_context_for_review` | 否 | 是否允许带上问答内容用于排查。 |

`page_url`、`client_version`、`client_feedback_id` **不属于该接口字段**。`created_at`、`feedback_id`、AI 标签、严重度和处理状态均由服务端生成，前端不得提交。

问题类型枚举：`incorrect_answer`、`incomplete_answer`、`misunderstood_question`、`quote_result_issue`、`clarification_issue`、`knowledge_issue`、`slow_response`、`display_issue`、`other`。

## JSONL 落盘与事件模型

本地默认目录为 `./data/feedback/chat-feedback.jsonl`；生产环境建议为 `/data/logs/freight-agent/feedback/chat-feedback.jsonl`。反馈与 `freight-agent-app.jsonl` 分目录，避免人工反馈与应用日志混用。

不要使用持续改写的 JSON 数组，采用一行一个 JSON 对象的 JSONL，可安全追加、逐行容错和按天归档。

处理顺序固定：

```text
请求校验 → 追加 feedback（ai_analysis.status=pending） → AI 分析（严格超时）
→ 追加 feedback_enrichment → 返回 accepted / completed / pending
```

原始事件至少包含 `record_type=feedback`、`schema_version`、服务端生成的 `feedback_id`/北京时间 `created_at`、会话与请求关联、用户反馈、问答快照、`trace_snapshot`、初始 AI 状态及 `workflow.status=new`。

AI 成功后追加 `record_type=feedback_enrichment`，包含 AI 摘要、质量标签、业务域、链路阶段、根因假设、严重度、置信度、建议动作与人工复核标记。后续人工处理必须追加 `record_type=feedback_update`，而不能改写历史 JSONL 行。

当存在 `request_id` 时，服务端从内存或当日应用 JSONL 形成轻量 `trace_snapshot`：`intent`、`query_ready`、`tool_status`、`error_type`、`total_elapsed_ms`、起运地、目的地、`retrieved_docs_count` 等。查不到时记录 `trace_found=false`，但仍接收反馈。

## AI 归因与安全

AI 的输入仅限用户反馈、本轮问答、必要上下文、结构化链路摘要和允许枚举；不得输入全量日志、密钥、完整堆栈或无关历史会话。输出需受 Pydantic/JSON Schema 限制；根因必须表达为“可能/需复核”，证据不足时降低置信度并标记人工复核。

用户问题类型与 AI 标签分开保存，AI 不得覆盖用户原始感受。AI 超时、格式错误或网络失败时，原始反馈已落盘；记录失败摘要并返回 `pending` 或 `failed`，不能丢失反馈。

落盘前执行长度限制和基础脱敏（手机号、邮箱、身份证号、订单号）；反馈文件只放在受控目录，不作为静态资源暴露。

## 配置、并发与实施

建议配置：

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

每次写入使用单行 `json.dumps(..., ensure_ascii=False)` 加换行并 flush。单进程使用锁；多 worker/容器使用系统文件锁或按进程、日期分片。应用日志仅记录反馈 ID 与摘要，记录 `chat_feedback_received`、`chat_feedback_ai_completed`、`chat_feedback_ai_failed`，不重复记录用户全文。

预计改动：`main.py`、`config.py`、新增 `feedback/models.py`、`feedback/store.py`、`feedback/service.py`、`feedback/prompts.py`、`tests/test_chat_feedback.py`。

验收：原 `/api/chat` SSE 与运价链路回归正常；`context` 可返回 request_id；合法反馈可逐行解析；AI 失败仍保留原始记录；单进程并发无半行损坏；接口模型不含 `page_url`、`client_version`、`client_feedback_id`。

当前不含 `client_feedback_id`，因此不能做到客户端网络重试的精确幂等；第一版由前端提交态控制重复点击。反馈达到约 10,000 条、多人编辑、复杂检索或多实例严格一致性时迁移 SQLite/PostgreSQL，并以 `feedback_id` 为主键导入事件。
