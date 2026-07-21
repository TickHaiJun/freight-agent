# AI 运价前端平台优化方案

## 目标与边界

本文件只覆盖 AI 运价前端平台（原生 JavaScript）的优化工作：在每一条已完成 AI 回答旁提供“不满意”反馈入口，以结构化且低成本的方式提交本轮问题。前端不负责文件落盘、AI 标签归因、链路摘要、质量指标或 Next 监控页面。
只基于jsNew/chat-widget.js 文件做修改，其它的不需要改变

## 与聊天协议的衔接

继续使用已有 `/api/chat` SSE 请求和 `text`、`context`、`done`、`error` 事件处理，不改变现有多轮 `context` 合并逻辑。后台会在 `context` 中可选提供 `request_id`；本轮回答完成后缓存：`session_id`、`request_id`、当前用户问题、完整 AI 回答及可选最近 2～3 轮摘要。

`request_id` 是单轮精确关联的关键。老后台未返回该值时仍可提交会话与问答快照，但属于关联降级，不能自行伪造请求 ID。

## 反馈交互

每个已完成 AI 回答旁提供“不满意”按钮，并与该条回答绑定。弹窗包括：

1. 标题：“这条回答哪里没有帮到你？”
2. 问题类型多选，至少选择一项。
3. “具体说明”文本框。
4. “允许我们带上本轮问答内容用于排查”开关；内部测试建议默认开启并明确提示。
5. 提交与取消按钮；成功提示“反馈已提交，感谢帮助我们改进”。

问题类型：`incorrect_answer`、`incomplete_answer`、`misunderstood_question`、`quote_result_issue`、`clarification_issue`、`knowledge_issue`、`slow_response`、`display_issue`、`other`。不展示 AI 标签、严重度、request_id 或原始 JSON 等技术字段。


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

## 接口提交

调用普通 JSON 接口：

```http
POST /api/chat-feedback
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

请求体仅包含 `session_id`、`request_id`、`feedback_text`、`dissatisfaction_types`、`user_question`、`assistant_answer`、可选 `conversation_excerpt` 和 `allow_context_for_review`。

以下字段**不传递**：`page_url`、`client_version`、`client_feedback_id`；也不传 `created_at`、`feedback_id`、AI 分析结果、严重度与工作流状态。接口响应 `status=accepted` 即表示提交成功；不论 `ai_analysis_status` 为 `completed`、`pending` 还是 `failed`，都不应阻塞或误导用户。

## 状态与校验

- 问题类型至少选择一项，反馈说明限制为 5～1,000 字。
- 对问答快照做长度截断，配合后台上限。
- 提交中禁用按钮，成功后标记当前回答已反馈；失败时保留已填写内容并提供重试。
- 原有流式文本渲染、运价询价及多轮对话必须完全不受影响。
- 本期没有 `client_feedback_id`，无法提供客户端重试的精确幂等；使用提交态和成功后的本地 UI 状态防止重复点击。若以后需严格去重，再与后台确定幂等方案。

## 实施与验收

改动范围为聊天消息渲染、SSE context 缓存、反馈弹窗原生 JS 模块、API 调用模块及前端回归用例。验收：按钮关联正确轮次；无有效类型/说明不能提交；请求体不含三个已排除字段；成功、网络失败、AI pending 都有明确提示；聊天主链路回归正常。
