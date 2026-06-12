# 2026-06-09 Agent 问题修复实现方案

## 参考

本方案基于：

- `docs/questions/2026-06-09_agent-problem-analysis.md`
- 当前实现代码：
  - `graph/nodes.py`
  - `graph/origin_parser.py`
  - `graph/prompts.py`
  - `graph/state.py`
  - `tools/air_freight.py`
  - `main.py`

说明：用户消息里写的是 `docs/2026-06-09_agent-problem-analysis.md`，当前仓库内实际存在的是 `docs/questions/2026-06-09_agent-problem-analysis.md`，以下方案按现有实际文件为准。

---

## 目标

本轮实现不是重做 Agent，而是在保持现有 `/api/chat` SSE 协议、现有 LangGraph 主图结构、现有 `context` 机制不破坏的前提下，解决以下问题：

1. 缺始发港时不追问，反而直接错误查价
2. 新完整询价被误判成旧结果追问
3. “全部港口有哪些”“你不问我始发港吗”这类业务解释/纠错问题掉进错误兜底
4. 闲聊与非业务问题没有承接能力
5. 上一轮错误上下文污染下一轮新询价

---

## 非目标

本轮不做以下事情：

1. 不改 `/api/chat` 请求与 SSE 返回协议
2. 不把 `sfg` 从字符串改成 `list[str]`
3. 不新增复杂数据库持久化
4. 不重写整个 `graph/agent.py` 节点编排
5. 不顺手扩展复杂货代规则，如危品细分、客户级价格策略、舱位可订性

---

## 总体策略

采用“最小闭环、局部增强”的方式实现，不走大重构。

核心思路：

1. 保持顶层 `intent` 体系基本稳定
   - 继续复用 `rate_query / support_info / rag / result_analysis / result_reference / unknown`
   - 不急着新增一堆顶层 intent

2. 把问题收敛到 3 个关键层
   - `intent_node`：重排优先级，补 `business_meta / smalltalk` 识别
   - `slot_node`：新增查价前合法性校验，阻止脏槽位放行
   - `support_info_node / fallback_node`：把“欢迎语 / 业务说明 / 真兜底”分层

3. 新增少量纯函数 helper，而不是新增复杂图节点
   - 优先新增 helper 文件或 helper 函数
   - 避免修改 `graph/agent.py` 的边结构，降低回归风险

---

## 待确认边界

以下边界不阻塞首版实现，我会先按默认方案设计；如果后续你要改，只影响局部文案和规则，不影响主架构。

### 1. “全部港口有哪些”的回答形式

默认方案：

- 先返回“全部港口”对应的是分公司固定白名单
- 文案同时给出中文名 + 三字码
- 结尾补一句“如果要直接查价，也可以回复全部港口 + 目的港 + 重量体积”

### 2. `sfg == mdg` 的纠错策略

默认方案：

- 若判定 `sfg` 明显被污染成了 `mdg`，优先保留 `mdg`
- 清空 `sfg`
- 转为追问始发港

原因：

- 从现有错例看，目的港通常更容易从句子中稳定抽到
- 保留 `mdg`、清空 `sfg` 的风险比双清更小

### 3. 轻闲聊的能力边界

默认方案：

- 支持 greeting、简单在吗、你是谁、你能做什么、轻度接话
- 不做开放式长聊天
- 不把闲聊写入运价槽位

### 4. 真兜底触发条件

默认方案：

- 只有“业务问题系统确实无法回答”或“RAG 无依据且无法通过追问解决”时，才进入人工邮箱兜底

---

## 方案设计

## 一、Intent 层改造

### 目标

解决：

1. 新完整询价被旧结果追问截走
2. 业务解释/流程纠错类问题误进 `rate_query`
3. 非业务闲聊只能掉 `unknown`

### 实现方式

优先在 `graph/nodes.py` 内调整 `intent_node` 规则顺序，并补充 3 组 helper。

### 建议新增 / 改造的 helper

在 `graph/nodes.py` 中新增或改造：

1. `_looks_like_meta_correction(message: str) -> bool`
   - 命中示例：
     - `你不问我始发港是哪里吗`
     - `你是不是理解错了`
     - `你先别查，先确认下我的条件`
     - `你帮我看看还缺什么`

2. `_looks_like_business_scope_question(message: str) -> bool`
   - 命中示例：
     - `全部港口有哪些`
     - `你们支持哪些始发港`
     - `全部查询是什么意思`

3. `_looks_like_smalltalk(message: str) -> bool`
   - 命中示例：
     - `你好`
     - `在吗`
     - `你是谁`
     - `谢谢`

### `intent_node` 新优先级

建议改为：

1. 明确的 greeting / smalltalk
2. 明确的 meta correction / business_meta
3. 明确的新完整询价
4. 明确的 pending action 短回复
5. 结果分析 / 结果字段追问
6. RAG
7. 业务说明 support_info
8. 真正 unknown -> hard fallback

### 关键点

#### 1. 新完整询价必须早于 `result_reference`

这是解决：

- `我有一票货，从南京，上海，发往洛杉矶 890公斤 9个立方，托盘，今天发货多少钱`

被误判成旧报价结果价格追问的关键。

#### 2. `business_meta` 不新开图节点

首版不建议新增 `conversation_guidance` 节点。

更稳的做法：

- 仍然走 `intent = support_info`
- 通过 `support_info_kind = business_meta / all_origin_scope / smalltalk`
- 在 `support_info_node` 内输出对应解释与引导

这样不需要改图结构。

---

## 二、新询价识别规则加强

### 目标

解决：

1. 新询价重开识别太弱
2. `发往` 没被当成航线信号
3. 中间态上下文压过新输入

### 实现方式

改造 `graph/nodes.py` 中：

- `_looks_like_new_complete_rate_query(...)`
- `_has_rate_context(...)`
- `_looks_like_rate_followup(...)`
- `_looks_like_package_type_reply(...)`

### 具体改动

#### 1. `_looks_like_new_complete_rate_query(...)`

增强信号词：

- `发往`
- `发去`
- `送往`
- `去往`
- `查一下`
- `帮我查`
- `我有一票货`
- `重新查`
- `再查一票`

降低触发门槛：

- 不再强依赖 `query_completed=True`
- 只要当前句子同时出现：
  - 航线/目的港信号
  - 至少 2 个以上运价关键参数
  - 且不是明显的结果追问短句
  即可判定为新询价

#### 2. `_has_rate_context(...)`

收紧规则，不再“2 个字段就算有报价上下文”。

建议拆成两个概念：

1. `has_slot_context`
   - 只表示当前会话里确实积累过询价信息

2. `has_executable_rate_context`
   - 必须至少接近可查价状态，或者已存在明确待补槽位

首版可以不改函数名，但内部逻辑要收紧，避免脏半成品上下文被过度复用。

#### 3. `_looks_like_package_type_reply(...)`

必须增加“短句约束”：

- 仅当消息长度短、无重量/体积/日期/航线信息时，才视为补包装类型
- 如果一句话同时带：
  - 始发港/目的港
  - 重量/体积
  - 日期
  - 包装
  则优先判为新询价，不判成短回复

---

## 三、Origin 解析修复

### 目标

解决：

1. 多始发港里混入目的港
2. `发往` 未触发始发段截断

### 实现方式

修改 `graph/origin_parser.py`

### 具体改动

#### 1. 扩充 `DESTINATION_MARKERS`

至少补充：

- `发往`
- `发去`
- `送往`
- `去往`

#### 2. 增加 origin segment 截断保护

对于：

- `从南京，上海，发往洛杉矶`

必须在 `发往` 前截断 origin segment，不能让 `洛杉矶` 继续参与始发港候选。

#### 3. 增加测试

新增或补充测试：

- `从上海，香港，南京 飞 洛杉矶`
- `从南京，上海，发往洛杉矶`
- `全部港口查一下飞洛杉矶`
- `上海香港南京到洛杉矶`

---

## 四、查价前合法性校验

### 目标

解决：

1. `sfg=lax, mdg=lax` 这类脏槽位被直接放行
2. 多始发港被污染后仍然 `query_ready=True`
3. 用户明明缺始发港却没有追问

### 实现方式

不建议新增 LangGraph 节点。

建议新增一个纯函数 helper 文件，例如：

- `graph/query_validation.py`

也可以接受先放在 `graph/nodes.py` 内部，首版以最小改动为先。

### 建议提供的接口

```python
def validate_rate_slots(slots: dict) -> dict:
    """
    返回：
    {
        "valid": bool,
        "normalized_slots": dict,
        "missing_slots": list[str],
        "clarify_reason": str | None,
        "clarify_message": str | None,
    }
    """
```

### 校验内容

1. `sfg` 是否存在
2. `mdg` 是否存在
3. `sfg != mdg`
4. 多始发港中是否错误包含 `mdg`
5. `sfg` 是否全部是合法三字码
6. `mdg` 是否是合法三字码
7. 重量、体积是否大于 0
8. 日期字段是否满足单日或区间语义

### 接入位置

优先接在 `slot_node` 末尾、设置 `query_ready` 之前。

即：

1. 先抽槽位
2. 再合并上下文
3. 再跑 `validate_rate_slots`
4. 再决定：
   - `query_ready=True` 进入 `tool`
   - 或转为缺槽位追问 / 纠错说明

### 关键收益

这样可以避免：

- `slot_node` 只看字段是否非空
- `tool_node` 被迫承担错误输入

---

## 五、业务说明 / 闲聊 / 真兜底分层

### 目标

解决：

1. “全部港口有哪些”掉兜底
2. “你好”以外的轻闲聊无法承接
3. 人工邮箱兜底用得过宽

### 实现方式

继续复用 `support_info_node`，但扩充 `support_info_kind`。

### `support_info_kind` 建议扩充为

1. `greeting`
2. `capability_intent`
3. `service_info`
4. `smalltalk`
5. `business_meta`
6. `all_origin_scope`

### 处理策略

#### 1. `smalltalk`

用于：

- 你好
- 在吗
- 你是谁
- 谢谢

要求：

- 不更新任何运价槽位
- 不改 `query_completed`
- 只返回轻量自然回复

#### 2. `business_meta`

用于：

- 你不问我始发港吗
- 你是不是理解错了
- 先确认再查
- 还缺什么

要求：

- 承认当前缺失或误解
- 输出纠偏解释
- 回到报价补参链

#### 3. `all_origin_scope`

用于：

- 全部港口有哪些
- 全部查询包含哪些口岸

要求：

- 回答固定白名单
- 明确这是“分公司固定查询口岸”
- 引导继续报价

#### 4. `fallback_node`

收口为真正的 `hard_fallback`

只在这些场景使用：

1. 问题明显属于业务域，但系统当前没有能力回答
2. RAG 无依据且无法通过追问继续
3. 非法或极度模糊输入，无法判断下一步

---

## 六、Prompt 与文案改造

### 目标

让系统更像业务助理，而不是只会死板查价或死板兜底。

### 修改文件

- `graph/prompts.py`

### 改动点

1. Intent Prompt
   - 强化“新完整询价优先于旧结果追问”
   - 加入 `business_meta / all_origin_scope / smalltalk` 的说明约束

2. Slot Prompt
   - 明确：
     - 没有明确始发港时不要猜 `sfg`
     - 目的港不能同时写进 `sfg`
     - 多始发港允许逗号串

3. Ask 文案
   - 缺始发港时统一改为：
     - `这票货目前还缺始发港。我需要先确认您从哪个城市/机场发货。您可以回复一个始发港、多个始发港，或者直接回复“全部港口”。`

4. Fallback 文案
   - 区分欢迎类与人工兜底类
   - 人工邮箱只保留在硬兜底

---

## 七、状态与上下文策略

### 目标

解决错误上下文被持续复用的问题。

### 修改文件

- `graph/state.py`
- `graph/nodes.py`

### 策略

1. 不新增复杂状态机字段，首版尽量复用现有：
   - `query_subtype`
   - `support_info_kind`
   - `pending_action_*`
   - `pending_reuse_confirmation`

2. 当命中“明确新完整询价”时：
   - 重置上一轮报价分析相关状态
   - 清理不应继承的待确认动作
   - 但不破坏当前消息里新抽到的槽位

3. 当命中 `business_meta`
   - 不更新 `sfg/mdg/weight/vol`
   - 只输出解释与下一步引导

4. 当查价前校验失败
   - 不把明显错误槽位原样写回 `context`
   - 优先写回校正后的安全状态

---

## 八、测试方案

### 目标

避免这轮规则修完后，老链路回归。

### 建议新增 / 补充测试

#### 1. `tests/test_origin_parser.py`

补充：

- `从南京，上海，发往洛杉矶` 不应把 `lax` 写进 `sfg`
- `全部港口查一下飞洛杉矶` 应映射固定白名单

#### 2. 新增 `tests/test_intent_routing.py`

覆盖：

- `你好`
- `全部港口有哪些`
- `你不问我始发港是哪里吗`
- `你先别查，先确认下我的条件`
- `我有一票货，从南京，上海，发往洛杉矶 890公斤 9个立方 托盘 今天发货多少钱`

#### 3. 新增 `tests/test_slot_validation.py`

覆盖：

- `sfg=lax, mdg=lax` 应转为缺始发港
- 多始发港中混入 `mdg` 应被清洗或拦截
- 缺少 `sfg` 时必须追问

#### 4. 新增 `tests/test_support_info.py`

覆盖：

- `全部港口有哪些`
- `你是谁`
- `你能做什么`
- `谢谢`

---

## 影响文件

### 必改

1. `graph/nodes.py`
   - intent 优先级
   - 新完整询价识别
   - meta / smalltalk / support_info 分流
   - slot 合并后的查价前校验

2. `graph/origin_parser.py`
   - 目的地截断词补充
   - 多始发港污染修复

3. `graph/prompts.py`
   - intent/slot/ask/fallback 文案与约束

### 建议新增

4. `graph/query_validation.py`
   - 纯函数校验层

### 轻改

5. `graph/state.py`
   - 注释与 subtype 说明补充

### 测试

6. `tests/test_origin_parser.py`
7. `tests/test_intent_routing.py`
8. `tests/test_slot_validation.py`
9. `tests/test_support_info.py`

---

## 风险点

### 1. 规则收紧后，可能短期提高“追问率”

这是预期内现象。

因为首轮目标是：

- 先避免错查
- 再优化追问自然度

### 2. 新询价识别增强后，可能影响老的 follow-up 场景

例如：

- `那香港呢`
- `那全部港口呢`
- `改成托盘`

所以必须配套补回归测试。

### 3. support_info 分层后，文案风格需要统一

否则容易出现：

- greeting 太像欢迎页
- business_meta 太像报错信息
- hard_fallback 太像客服甩锅

---

## 验证方案

实现后至少验证以下用例：

### A. 缺始发港必须追问

输入：

- `我有一票货，发往洛杉矶，散货，600公斤，4个立方，今天发多少`

期望：

- 不调用报价工具
- 追问始发港

### B. 纠错类问题必须解释，不得继续乱查

输入：

- 上一轮出现缺始发港后，用户说：`你不问我始发港是哪里吗`

期望：

- 不调用报价工具
- 解释缺始发港
- 引导回复一个/多个/全部港口

### C. 业务说明类问题不进硬兜底

输入：

- `全部港口有哪些`

期望：

- 返回固定白名单说明
- 不返回人工邮箱兜底

### D. 新完整询价不得误判成结果追问

输入：

- 完成一轮报价后再问：`我有一票货，从南京，上海，发往洛杉矶 890公斤 9个立方，托盘，今天发货多少钱`

期望：

- 识别为新询价
- 重开查价链
- 不复用上一轮结果分析文案

### E. 闲聊不污染上下文

输入：

- `你好`
- `你是谁`
- `谢谢`

期望：

- 正常回复
- 不改询价槽位

---

## 实现顺序建议

按以下顺序落地，回归风险最低：

1. `origin_parser` 修复
2. `intent_node` 优先级重排
3. `slot_node` 查价前合法性校验
4. `support_info_node / fallback_node` 分层
5. `prompts.py` 文案与约束补强
6. 自动化测试补齐

---

## 最终判断

这次实现不建议走“大改图结构”路线。

最优解是：

- 继续使用现有 `support_info` 节点承接 greeting / smalltalk / business_meta
- 继续使用现有 `slot_node` 承接查价前合法性校验
- 通过 helper 和优先级调整，把系统从“会错查的状态机”修到“会确认、会解释、会纠错的业务 Agent”

这样做的优点是：

1. 改动集中
2. 不破坏 SSE 协议
3. 不破坏前端 context 协议
4. 回归面可控
5. 适合下一步直接进入实现
