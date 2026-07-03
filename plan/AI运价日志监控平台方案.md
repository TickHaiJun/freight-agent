# AI运价日志监控平台方案

## 1. 目标

这个平台的目标不是做一个通用日志查看器，而是做一个面向 **AI 运价 Agent 排障** 的监控平台。

核心诉求有 4 个：

1. 能按天加载服务器 `/data/logs/freight-agent/` 下的多个 `.jsonl` 日志文件。
2. 能把原始事件流还原成“会话 / 请求 / 节点”的可读链路。
3. 能快速定位 AI 询价问题，例如：意图识别错、缺参追问异常、运价接口失败、日志字段冲突、RAG 检索异常。
4. 后续可逐步接入 AI 做总结、归因、聚类和建议，但第一阶段不依赖 AI 也能稳定排障。

项目技术栈按你的要求：

- Next.js 16.2.9
- React
- TypeScript
- shadcn/ui
- Next 后端 Route Handlers / Node Runtime
- 不做登录注册

---

## 2. 基于 `freight-agent-app.jsonl.2026-06-18` 的样本分析

我先基于当前日志样本提炼了结构特征，这些特征会直接决定平台怎么设计。

### 2.1 日志样本概况

样本文件：`logs/freight-agent-app.jsonl.2026-06-18`

统计结果：

- 总行数：281
- 结构化请求数：19
- 请求完整闭环数：19
- 含工具调用请求数：8
- `rate_query` 请求数：12
- `rag` 请求数：5
- `support_info` 请求数：2
- `tool_failed`：8 次
- `tool_failed.error_type` 全部为：`HTTP_ERROR`

### 2.2 当前日志适合做什么

这份日志非常适合做：

- 请求级时间线回放
- 会话级对话链路回放
- AI 询价失败归因
- RAG 检索链路分析
- 每日成功率 / 失败率 / 节点耗时统计

### 2.3 当前日志存在的结构问题

这份日志并不是“完美结构化”，存在几个现实问题，平台设计时必须考虑：

1. 很多行的 `event` 为 `null`
   这类日志更像原始运行日志，适合放在“原始日志”Tab，不适合直接做指标统计。

2. 中文存在乱码痕迹
   例如 `message_text`、`rag_answer_summary`、文档名等字段里出现了 `浣犲ソ`、`閿傜數姹?` 这类内容。
   这说明日志链路里存在编码问题。平台层可以先原样显示，但要预留“编码修复/脱敏/清洗”能力。

3. 结构化字段覆盖率并不是 100%
   并不是每一行都有 `session_id`、`request_id`、`intent`、`event`。
   所以平台不能只按“逐行表格”设计，而要做“结构化事件 + 原始日志双视图”。

4. 询价链路与 RAG 链路字段不同
   - 询价链路核心字段：`sfg`、`mdg`、`input_weight`、`input_vol`、`package_type`、`cargo_type`、`tool_status`、`error_type`
   - RAG 链路核心字段：`retrieval_query`、`retrieval_filters`、`retrieved_docs_count`、`retrieved_doc_sources`、`generator_docs`

所以页面不能只做一个统一表格，必须按业务链路做“字段适配”。

---

## 3. 平台总体实现思路

### 3.1 不建议前端直接访问服务器文件路径

虽然日志文件存放在服务器：

```text
/data/logs/freight-agent/
```

但前端浏览器不能直接读取这个系统目录。

正确做法是：

- **Next.js 后端**读取 `/data/logs/freight-agent/`
- 提供自己的 API 给前端页面调用
- 前端页面只请求 Next 的接口，不直接碰文件系统

也就是说，架构应该是：

```text
浏览器页面
  -> Next.js API / Route Handlers
  -> 读取 /data/logs/freight-agent/*.jsonl
  -> 解析 / 聚合 / 过滤 / 分页
  -> 返回给前端页面
```

这是最合理、最稳、也最符合你当前技术栈的方案。

### 3.2 平台数据分三层

#### 第一层：原始文件层

直接来自服务器：

- `freight-agent-app.jsonl`
- `freight-agent-app.jsonl.2026-06-18`
- 后续更多按天归档文件

#### 第二层：解析聚合层

由 Next 后端完成：

- 逐行解析 JSONL
- 过滤非法行
- 按 `request_id` 聚合成“请求”
- 按 `session_id` 聚合成“会话”
- 计算统计指标
- 提取异常请求

#### 第三层：页面消费层

前端页面消费的是：

- 日志文件列表
- 每日统计摘要
- 请求列表
- 会话列表
- 单次请求时间线
- 原始日志详情
- AI 分析结果（如果接入）

---

## 4. 我建议的页面结构

### 4.1 总览页 `/`

这是平台首页，目标是“当天有没有问题，一眼看出来”。

建议展示：

- 今日 / 指定日志文件总请求数
- `rate_query` 请求数
- `rag` 请求数
- `support_info` 请求数
- 询价成功数
- 询价失败数
- `tool_failed` 次数
- `request_failed` 次数
- 平均总耗时 `total_elapsed_ms`
- RAG 平均耗时
- Top `error_type`
- Top `intent`
- Top `origin` (`sfg`)

建议组件：

- 指标卡片
- 趋势折线图
- 失败分布饼图 / 柱状图
- 最近异常请求列表

适合第一眼回答的问题：

- 今天系统有没有明显异常
- AI 询价失败主要集中在哪类错误
- RAG 有没有明显异常
- 是否存在某一批请求耗时过高

### 4.2 日志文件页 `/files`

用于管理多个 `.jsonl` 文件。

建议展示：

- 文件名
- 文件大小
- 最后修改时间
- 日志日期
- 行数
- 请求数
- 是否已解析缓存

建议功能：

- 刷新文件列表
- 选择一个或多个文件加载
- 按日期过滤
- 合并多文件查询
- 标记“当前活跃文件”和“历史归档文件”

这个页面很重要，因为你未来会动态加载多个 `.jsonl`，不是只看单个文件。

### 4.3 请求列表页 `/requests`

这是平台最核心的页面之一。

粒度：一行 = 一个 `request_id`

建议字段：

- `request_id`
- `session_id`
- `intent`
- `message_text`
- `request_started.ts`
- `request_completed.total_elapsed_ms`
- `query_ready`
- `tool_status`
- `error_type`
- `sfg`
- `mdg`
- `retrieved_docs_count`
- `quote_count_total`

建议功能：

- 按日期 / 文件筛选
- 按 `intent` 筛选
- 按是否失败筛选
- 按 `tool_failed` / `request_failed` 筛选
- 按 `error_type` 筛选
- 按 `sfg` / `mdg` 筛选
- 按 `request_id` / `session_id` 搜索
- 按耗时排序

这是排查问题最常用的一页。

### 4.4 请求详情页 `/requests/[requestId]`

粒度：单次请求完整回放

建议分成 4 个 Tab：

#### Tab 1：时间线

按时间顺序展示：

- `request_started`
- `slot_extracted`
- `tool_failed` / `tool_succeeded`
- `rag_retrieve_started` / `rag_retrieve_finished`
- `rag_answer_generated`
- `agent_finished`
- `request_completed`

#### Tab 2：结构化字段

按卡片分组：

- 基础信息
- 询价参数
- RAG 参数
- 错误信息
- 结果摘要

#### Tab 3：原始日志

展示该 `request_id` 对应的所有原始 JSON 行和原始 `message`。

#### Tab 4：AI 分析（后续）

展示 AI 对这次请求的自动总结：

- 这次请求走了什么链路
- 哪一步失败
- 失败原因可能是什么
- 建议先查什么

### 4.5 会话页 `/sessions`

粒度：一行 = 一个 `session_id`

因为你当前日志里一个 `session_id` 会有多次请求，这页适合看用户一整段对话。

建议展示：

- `session_id`
- 请求数
- 第一次时间
- 最后一次时间
- 主要 intent 分布
- 是否包含失败请求
- 最近一次用户问题

建议功能：

- 查看整个 session 的请求时间线
- 识别“多轮询价”与“RAG 问答”混合会话
- 识别某个会话里从 greeting -> 询价 -> 异常 的完整过程

这个页面对还原真实用户行为很重要。

### 4.6 异常中心 `/errors`

这是平台必须有的页。

建议按“异常请求”聚合展示：

- `tool_failed`
- `request_failed`
- `error_type`
- `error_stage`
- `error_message`
- 高频相似异常
- 最近异常时间
- 影响请求数

建议分组方式：

- 按 `error_type`
- 按 `error_stage`
- 按 `message` 模板聚类
- 按 URL / 外部接口维度归并

这页后面会非常实用。

### 4.7 AI 运价链路页 `/quote-monitor`

这是面向你当前业务的专项页面。

建议只看 `intent=rate_query` 请求，并展示：

- 询价请求数
- `query_ready=true/false`
- 缺参追问数量
- `tool_failed` 数
- `quote_count_total=0` 数
- 多始发港请求数
- `sfg/mdg` 分布
- 包装类型分布
- 查询日期分布

可以直观看到：

- 询价失败主要卡在抽参、追问、工具还是结果阶段
- 哪些港口组合容易失败
- 是否大量出现“接口成功但无报价”

### 4.8 RAG 监控页 `/rag-monitor`

建议只看 `intent=rag` 请求。

展示：

- `retrieval_query`
- `retrieval_filters`
- `retrieved_docs_count`
- `retrieved_doc_sources`
- `generator_docs`
- `rag_answer_length`
- 耗时

对你后面维护知识库很有价值。

---

## 5. Next.js 后端我会怎么设计

### 5.1 文件访问层

建议新增一个日志访问模块，例如：

```text
src/lib/logs/
  file-service.ts
  jsonl-parser.ts
  request-aggregator.ts
  session-aggregator.ts
  metrics.ts
```

#### `file-service.ts`

职责：

- 读取 `/data/logs/freight-agent/`
- 列出可用 `.jsonl` 文件
- 读取指定文件内容
- 支持按日期或文件名过滤

#### `jsonl-parser.ts`

职责：

- 逐行解析 JSONL
- 跳过非法行
- 标记编码异常 / 脏字段

#### `request-aggregator.ts`

职责：

- 按 `request_id` 聚合事件
- 提取一个请求的开始、结束、耗时、错误、工具结果、RAG 结果

#### `session-aggregator.ts`

职责：

- 按 `session_id` 聚合请求
- 生成会话维度摘要

#### `metrics.ts`

职责：

- 统计请求数
- 统计失败率
- 统计 intent 分布
- 统计 error_type 分布
- 统计耗时分布

### 5.2 Next API / Route Handlers 设计

建议接口：

#### `GET /api/log-files`

返回文件列表。

#### `GET /api/log-summary?file=...`

返回某个文件的摘要统计。

#### `GET /api/requests?file=...&intent=...&status=...`

返回请求列表。

#### `GET /api/requests/[requestId]`

返回单个请求的完整时间线与详情。

#### `GET /api/sessions?file=...`

返回会话列表。

#### `GET /api/sessions/[sessionId]`

返回单个会话的完整请求链路。

#### `GET /api/errors?file=...`

返回异常请求列表与异常聚合统计。

#### `GET /api/quote-monitor?file=...`

返回 AI 询价专项指标。

#### `GET /api/rag-monitor?file=...`

返回 RAG 专项指标。

注意：

- 这些接口全部由 Next 后端读取服务器本地日志目录
- 前端不直接读文件系统
- 这样你后面上服务器也更稳

---

## 6. 前端页面我会怎么做

UI 方向建议：

- 使用 shadcn/ui 的 `table`、`tabs`、`card`、`badge`、`dialog`、`sheet`、`select`、`command`、`tooltip`、`scroll-area`
- 首页偏 Dashboard 风格
- 列表页偏排障工作台风格
- 详情页偏时间线 + 原始 JSON 双栏风格

### 一些关键交互建议

1. 所有列表页支持“点进详情”
2. 请求详情页支持“复制 `request_id` / `session_id`”
3. 原始 JSON 支持代码块查看
4. 支持按 `error_type` 快速筛同类异常
5. 支持从一个 session 跳到其所有 request
6. 支持从一个请求跳到其原始日志上下文

---

## 7. 是否需要接入 AI

结论：

- **第一阶段不依赖 AI，也应该能把平台做得非常有用。**
- **第二阶段再接 AI，会显著提高排障效率，但不应该一开始就把平台绑死在 AI 上。**

原因很直接：

- 结构化日志本身已经足够做筛选、统计、时间线回放
- 如果基础数据层没理顺，AI 只会放大噪音
- 先把“可查、可筛、可回放”做好，再上 AI 最稳

---

## 8. 如果接入 AI，我建议做哪些功能

### 8.1 单次请求 AI 归因

在请求详情页中，增加一个“AI 分析”按钮。

输入给 AI：

- 该请求完整事件流
- 关键字段
- 错误字段
- 相关原始日志片段

输出：

- 这次请求走了什么链路
- 真正失败点在哪
- 失败属于哪一类问题
- 建议优先看哪几个配置 / 模块

这是最值得最先接入的 AI 功能。

### 8.2 每日日志 AI 总结

对单个 `.jsonl` 文件做总结：

- 今日总请求数
- AI 询价成功/失败情况
- 高频错误
- 新出现的异常模式
- 值得关注的请求样本

适合放在首页或文件详情页。

### 8.3 异常聚类与归并

AI 可以对相似错误做聚类，例如：

- 同类 `HTTP_ERROR`
- 同类字段冲突错误
- 同类 RAG 检索空结果
- 同类配置错误

输出：

- 聚类名
- 影响请求数
- 代表样本
- 建议原因

### 8.4 业务层异常洞察

不只是技术错误，还可以做业务洞察：

- 哪些航线最常无报价
- 哪些问题最容易触发缺参追问
- 哪些问题用户常用自然语言表达但系统识别不稳定
- 哪类 RAG 问题最常没有命中资料

这对你持续迭代 Agent 很有价值。

---

## 9. 我建议的平台分阶段建设顺序

### 第一阶段：日志可视化与排障基础版

必须做：

- 文件列表页
- 总览页
- 请求列表页
- 请求详情页
- 会话页
- 异常中心

这个阶段就足够支撑你当前排障。

### 第二阶段：专项业务页

补：

- AI 运价链路页
- RAG 监控页
- 更细的筛选与统计

### 第三阶段：AI 辅助分析

补：

- 单次请求 AI 归因
- 每日日志 AI 总结
- 异常聚类
- 建议下一步排查项

---

## 10. 当前样本日志对平台设计的直接启发

基于 `freight-agent-app.jsonl.2026-06-18`，我会特别注意这几点：

1. **结构化事件优先，原始 `message` 辅助**
   因为很多真正可统计的信息在 `event` 和结构化字段里。

2. **请求视图优先于逐行日志视图**
   因为你真正排障是按 `request_id` 查，不是按第 173 行查。

3. **一定要保留原始日志视图**
   因为目前 `event=null` 的运行日志仍然有价值，尤其排查链路细节时。

4. **要预留编码问题处理**
   当前日志里中文存在乱码痕迹，平台后面可以考虑增加：
   - 原样显示
   - 尝试修复显示
   - 仅对关键摘要字段做清洗

5. **要区分 AI 询价和 RAG 两条链路**
   这两个链路的字段完全不同，混在一个页面里会让平台不好用。

---

## 11. 我对这个平台的最终建议

如果你的目标是“方便我接入排查问题”，那这个平台第一版不要做成“通用 APM”，也不要做成“纯日志查看器”。

更适合你的定位应该是：

> 一个面向 AI 物流 Agent 的排障工作台。

它最重要的不是炫技，而是让你快速回答这几类问题：

- 这次请求有没有走到工具
- 是抽参失败、接口失败还是结果生成失败
- 当前问题是 AI 识别问题，还是业务接口问题，还是日志/代码问题
- 某个异常今天出现了多少次
- 哪些会话值得重点回看

从这个角度看：

- **先不接 AI，也能做得很有价值**
- **但后续接 AI 会显著提高复盘和归因效率**

---

## 12. 我的推荐落地方案

### 先做

- Next.js 后端读取 `/data/logs/freight-agent/`
- 请求级聚合
- 会话级聚合
- 总览 + 请求列表 + 请求详情 + 异常中心

### 再做

- AI 运价专项页
- RAG 专项页
- 多文件聚合分析

### 最后做

- AI 单次归因
- AI 每日日志总结
- AI 异常聚类

---

## 13. 实现范围建议

### 本期建议纳入

- 读取多个 `.jsonl`
- 文件列表
- 总览统计
- 请求列表
- 请求详情时间线
- 会话页
- 异常中心
- AI 运价监控页

### 本期不建议强行纳入

- 登录注册
- 权限体系
- 数据库存储
- 实时 WebSocket 推送
- 复杂告警系统
- 把所有原始日志全量入库

---

## 14. 结论

这套平台完全可以基于你现在的 `.jsonl` 日志先做起来，而且第一版就会很有用。

最关键的设计原则是：

1. 前端不直接碰 `/data/logs/freight-agent/`，而是通过 Next 后端读取。
2. 平台核心粒度是 `request_id` 和 `session_id`，不是逐行文本日志。
3. 先把“可视化排障”做稳，再接 AI。
4. AI 最适合承担的是“归因、总结、聚类、建议”，而不是替代底层日志解析。

如果后续进入实现，我建议先从下面 4 个模块起：

- 日志文件访问层
- 请求聚合器
- 总览页
- 请求列表 + 详情页
