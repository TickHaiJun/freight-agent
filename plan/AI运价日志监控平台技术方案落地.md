# AI运价日志监控平台技术方案落地

## 1. 文档目标

这份文档不是产品方案，而是 **Next.js 全栈项目的技术落地方案**。

目标是：你后续新建一个独立项目目录，把 `freight-agent-app.jsonl.2026-06-18` 先放到项目根目录或指定日志目录里，然后基于这份文档，使用 Codex CLI 直接进入开发。

本次只覆盖两个阶段：

- 第一阶段：日志可视化与排障基础版
- 第二阶段：专项业务页

本次**不覆盖**：

- 登录注册
- 权限体系
- 数据库存储
- AI 归因 / AI 总结 / AI 聚类
- 实时告警
- WebSocket 推送

---

## 2. 项目定位

这个平台不是通用日志系统，而是一个 **AI 物流 Agent 排障工作台**。

它解决的问题是：

1. 把 `/data/logs/freight-agent/` 下多个 `.jsonl` 文件动态加载进来。
2. 把逐行日志还原成“请求视角”和“会话视角”。
3. 快速判断一条 AI 询价到底卡在：
   - 意图识别
   - 槽位提取
   - 缺参追问
   - 工具调用
   - 结果生成
   - RAG 检索
4. 形成一个后续可以继续叠加 AI 分析能力的平台底座。

---

## 3. 当前日志样本对技术方案的约束

基于 `freight-agent-app.jsonl.2026-06-18` 样本，当前平台实现必须接受这些现实约束：

### 3.1 不是每一行都有完整结构化字段

存在很多：

- `event = null`
- 只有 `message`
- 没有 `request_id`
- 没有 `session_id`

因此：

- 不能把平台设计成“单纯按 JSON 表格展示”
- 必须同时提供“结构化事件视图”和“原始日志视图”

### 3.2 当前最核心的排障粒度是 `request_id`

样本里一个请求通常有：

```text
request_started
-> slot_extracted / rag_retrieve_started
-> tool_failed / rag_answer_generated / agent_finished
-> request_completed
```

因此平台核心聚合单位应该是：

- 第一优先：`request_id`
- 第二优先：`session_id`

### 3.3 AI 询价链路和 RAG 链路字段不同

询价链路常见字段：

- `sfg`
- `mdg`
- `input_weight`
- `input_vol`
- `package_type`
- `cargo_type`
- `tool_status`
- `error_type`
- `quote_count_total`

RAG 链路常见字段：

- `retrieval_query`
- `retrieval_filters`
- `retrieved_docs_count`
- `retrieved_doc_sources`
- `generator_docs`
- `rag_answer_length`

所以平台页面不能用一套字段硬套所有日志。

### 3.4 日志里已有中文乱码痕迹

例如：

- `message_text`
- `rag_answer_summary`
- `retrieved_doc_sources`

存在乱码表现。

因此第一版平台策略应是：

- 先原样展示
- 后续再补“编码修复 / 清洗”能力

不要为了修编码，在第一版就把日志解析层搞复杂。

---

## 4. 技术栈与运行方式

## 4.1 技术栈

建议使用：

- Next.js 16.2.9
- React 19
- TypeScript
- App Router
- shadcn/ui
- Tailwind CSS
- Node Runtime 的 Route Handlers
- `zod` 做请求参数和返回结构校验
- `dayjs` 做时间格式化

如果只允许最小依赖，建议新增依赖控制在：

- `zod`
- `dayjs`
- `lucide-react`
- `recharts` 或 `visx` 二选一做图表

第一版不建议额外接：

- Zustand / Redux
- 数据库 ORM
- WebSocket
- 图表过重的商业库

## 4.2 运行方式

这个项目是一个 **Next.js 全栈项目**，既负责页面，也负责后端日志读取 API。

运行链路：

```text
浏览器页面
  -> Next.js 页面
  -> 调用 Next Route Handlers
  -> Route Handlers 读取服务器日志目录
  -> 解析 JSONL
  -> 聚合成请求 / 会话 / 统计结果
  -> 返回给页面展示
```

结论：

- 前端不能直接访问 `/data/logs/freight-agent/`
- 必须由 Next 后端读取日志文件

---

## 5. 项目目录结构建议

建议新项目目录结构如下：

```text
ai-freight-log-monitor/
├── app/
│   ├── (dashboard)/
│   │   ├── page.tsx                      # 总览页
│   │   ├── files/page.tsx               # 日志文件页
│   │   ├── requests/page.tsx            # 请求列表页
│   │   ├── requests/[id]/page.tsx       # 请求详情页
│   │   ├── sessions/page.tsx            # 会话列表页
│   │   ├── sessions/[id]/page.tsx       # 会话详情页
│   │   ├── errors/page.tsx              # 异常中心
│   │   ├── quote-monitor/page.tsx       # AI运价专项页
│   │   └── rag-monitor/page.tsx         # RAG专项页
│   └── api/
│       ├── log-files/route.ts
│       ├── log-summary/route.ts
│       ├── requests/route.ts
│       ├── requests/[id]/route.ts
│       ├── sessions/route.ts
│       ├── sessions/[id]/route.ts
│       ├── errors/route.ts
│       ├── quote-monitor/route.ts
│       └── rag-monitor/route.ts
├── components/
│   ├── dashboard/
│   ├── logs/
│   ├── requests/
│   ├── sessions/
│   ├── errors/
│   └── charts/
├── lib/
│   ├── logs/
│   │   ├── file-service.ts
│   │   ├── jsonl-parser.ts
│   │   ├── request-aggregator.ts
│   │   ├── session-aggregator.ts
│   │   ├── metrics.ts
│   │   ├── quote-monitor.ts
│   │   ├── rag-monitor.ts
│   │   └── types.ts
│   ├── utils/
│   └── constants/
├── public/
├── logs/                                # 本地开发用日志目录
├── components.json
├── next.config.ts
├── package.json
├── tsconfig.json
└── README.md
```

### 目录设计原则

1. `app/api` 只负责接口入口
2. `lib/logs` 负责日志解析和聚合核心逻辑
3. `components` 负责复用 UI
4. `logs/` 目录仅用于本地开发样本，不代表线上固定结构

---

## 6. 配置方案

## 6.1 环境变量

建议使用：

```env
LOG_ROOT_DIR=./logs
NEXT_PUBLIC_APP_NAME=AI运价日志监控平台
```

本地开发时：

```env
LOG_ROOT_DIR=./logs
```

服务器部署时：

```env
LOG_ROOT_DIR=/data/logs/freight-agent
```

### 原则

- 路径必须配置化
- 页面代码不直接写死 `/data/logs/freight-agent`
- 本地开发先读 `./logs`
- 上线再切到服务器真实目录

---

## 7. 数据模型设计

## 7.1 原始日志行

第一层数据结构：

```ts
type RawLogLine = {
  ts?: string
  level?: string
  logger?: string
  message?: string
  service?: string
  event?: string | null
  session_id?: string
  request_id?: string
  [key: string]: unknown
}
```

## 7.2 请求级聚合结果

这是平台最核心的数据结构：

```ts
type RequestTrace = {
  requestId: string
  sessionId?: string
  startedAt?: string
  completedAt?: string
  totalElapsedMs?: number
  intent?: string
  messageText?: string
  queryReady?: boolean
  toolStatus?: 'failed' | 'succeeded' | 'skipped'
  errorType?: string
  errorStage?: string
  errorMessage?: string
  sfg?: string
  mdg?: string
  inputWeight?: number
  inputVol?: number
  packageType?: string
  cargoType?: string
  retrievalQuery?: string
  retrievalFilters?: Record<string, unknown>
  retrievedDocsCount?: number
  quoteCountTotal?: number
  rawEvents: RawLogLine[]
}
```

## 7.3 会话级聚合结果

```ts
type SessionTrace = {
  sessionId: string
  requestIds: string[]
  requestCount: number
  firstAt?: string
  lastAt?: string
  latestIntent?: string
  hasFailure: boolean
  latestMessageText?: string
}
```

## 7.4 文件级摘要

```ts
type LogFileSummary = {
  fileName: string
  size: number
  lastModified: string
  totalLines: number
  requestCount: number
  intents: Record<string, number>
  errorTypes: Record<string, number>
}
```

---

## 8. 后端实现方案

## 8.1 `file-service.ts`

职责：

- 列出日志目录下所有 `.jsonl` 文件
- 获取文件元信息
- 读取指定文件内容

建议方法：

```ts
listLogFiles(): Promise<LogFileItem[]>
readLogFile(fileName: string): Promise<string[]>
readMultipleLogFiles(fileNames: string[]): Promise<string[]>
```

关键点：

- 只允许读取 `LOG_ROOT_DIR` 内的文件
- 要防目录穿越
- 只接受 `.jsonl` 文件

## 8.2 `jsonl-parser.ts`

职责：

- 把逐行文本转成 JSON 对象
- 跳过非法行
- 保留解析失败统计

建议方法：

```ts
parseJsonlLines(lines: string[]): RawLogLine[]
```

建议返回附带：

- `validCount`
- `invalidCount`

但第一版也可以先简单返回数组。

## 8.3 `request-aggregator.ts`

职责：

- 按 `request_id` 聚合日志
- 产出请求级对象

建议逻辑：

1. 遍历所有行
2. 找出含 `request_id` 的结构化日志
3. 按 `request_id` 分组
4. 根据 `event` 和字段提取请求摘要
5. 保留完整 `rawEvents`

建议规则：

- `request_started` 决定请求起点
- `request_completed` 决定请求终点
- `tool_failed` 决定 `toolStatus=failed`
- `tool_succeeded` 决定 `toolStatus=succeeded`
- `slot_extracted` 提取询价参数
- `rag_retrieve_completed` / `rag_answer_generated` 提取 RAG 字段

## 8.4 `session-aggregator.ts`

职责：

- 根据 `session_id` 把多个请求再聚合成会话

建议规则：

- 一个会话可以有多个请求
- 取最早 `startedAt` 作为 `firstAt`
- 取最晚 `completedAt` 作为 `lastAt`
- 任一请求失败，则 `hasFailure=true`

## 8.5 `metrics.ts`

职责：

- 从请求集合中计算总览数据

建议输出：

- 总请求数
- 询价请求数
- RAG 请求数
- `support_info` 数
- 失败请求数
- 平均耗时
- `error_type` 分布
- `intent` 分布
- `sfg` Top 分布

## 8.6 `quote-monitor.ts`

职责：

- 只统计 `intent=rate_query` 请求

建议输出：

- `queryReady=true/false` 分布
- `toolStatus` 分布
- `quoteCountTotal=0` 数量
- `sfg` Top
- `mdg` Top
- `packageType` 分布
- `cargoType` 分布

## 8.7 `rag-monitor.ts`

职责：

- 只统计 `intent=rag` 请求

建议输出：

- `retrievedDocsCount` 分布
- `retrievalFilters` 高频类别
- `retrievedDocSources` Top
- `rag_answer_length` 区间分布

---

## 9. API 设计

## 9.1 第一阶段必须实现

### `GET /api/log-files`

返回日志文件列表。

### `GET /api/log-summary?file=...`

返回单文件摘要。

### `GET /api/requests?file=...`

返回请求列表，支持筛选参数：

- `file`
- `intent`
- `status`
- `errorType`
- `sessionId`
- `requestId`

### `GET /api/requests/[id]`

返回单次请求详情：

- 请求摘要
- 时间线
- 原始事件列表

### `GET /api/sessions?file=...`

返回会话列表。

### `GET /api/sessions/[id]`

返回某个会话下的请求集合。

### `GET /api/errors?file=...`

返回异常中心数据。

## 9.2 第二阶段新增

### `GET /api/quote-monitor?file=...`

返回 AI 运价链路统计。

### `GET /api/rag-monitor?file=...`

返回 RAG 监控统计。

---

## 10. 页面落地方案

## 10.1 第一阶段页面

### 总览页 `/`

展示：

- 总请求数
- rate_query / rag / support_info 分布
- 失败请求数
- 平均耗时
- Top error_type
- 最近异常请求

### 日志文件页 `/files`

展示：

- 文件名
- 大小
- 更新时间
- 请求数

支持：

- 单选文件
- 多选文件
- 刷新文件列表

### 请求列表页 `/requests`

表格展示：

- request_id
- session_id
- intent
- message_text
- total_elapsed_ms
- toolStatus
- errorType
- sfg
- mdg

### 请求详情页 `/requests/[id]`

页面结构建议：

- 顶部摘要卡片
- 中间时间线
- 下方两个 Tab
  - 结构化字段
  - 原始日志

### 会话页 `/sessions`

展示：

- session_id
- requestCount
- hasFailure
- latestIntent
- latestMessageText

### 会话详情页 `/sessions/[id]`

展示：

- 会话概览
- 该会话下全部请求时间线

### 异常中心 `/errors`

展示：

- 异常请求列表
- `error_type` 聚合
- `error_stage` 聚合

## 10.2 第二阶段页面

### AI 运价专项页 `/quote-monitor`

展示：

- 询价总数
- `queryReady` 分布
- `toolStatus` 分布
- `quoteCountTotal=0` 分布
- Top `sfg`
- Top `mdg`
- 包装类型 / 货物类型分布

### RAG 专项页 `/rag-monitor`

展示：

- RAG 请求数
- `retrievedDocsCount` 分布
- `retrievalFilters` 分类分布
- `retrievedDocSources` Top
- 生成耗时与回答长度

---

## 11. 组件设计建议

建议优先抽这些复用组件：

- `MetricCard`
- `PageHeader`
- `LogFileSelector`
- `RequestTable`
- `SessionTable`
- `ErrorTable`
- `TimelineView`
- `JsonViewer`
- `KeyValueGrid`
- `IntentBadge`
- `StatusBadge`
- `ErrorBadge`

这些组件会在第一、第二阶段大量复用。

---

## 12. 状态管理建议

这个项目不需要一开始就上复杂全局状态。

建议：

- 页面筛选状态：用 URL query 参数管理
- 数据获取：优先走服务端请求 + 客户端轻状态
- 如有必要，可用 React Context 或轻量 hooks

第一版不建议先上 Zustand / Redux。

原因：

- 这个平台核心是“读文件、聚合、展示”
- 不是高交互编辑系统
- 先把数据流做清晰比状态库更重要

---

## 13. 本地开发与上线切换方案

## 13.1 本地开发

你后面会先把：

```text
freight-agent-app.jsonl.2026-06-18
```

放到新项目根目录或 `logs/` 目录。

建议本地目录：

```text
./logs/freight-agent-app.jsonl.2026-06-18
```

然后 `.env.local`：

```env
LOG_ROOT_DIR=./logs
```

## 13.2 服务器部署

上线时改成：

```env
LOG_ROOT_DIR=/data/logs/freight-agent
```

这样代码本身不变。

---

## 14. 第一阶段详细交付范围

第一阶段交付的定义必须明确，不然后面容易扩散。

### 需要完成

1. Next 项目基础框架
2. shadcn/ui 基础组件初始化
3. 读取日志目录
4. 解析 JSONL
5. 请求级聚合
6. 会话级聚合
7. 总览页
8. 文件列表页
9. 请求列表页
10. 请求详情页
11. 会话页
12. 异常中心

### 验收标准

- 可以在页面选择 `freight-agent-app.jsonl.2026-06-18`
- 可以看到请求列表
- 可以点开一条请求看完整时间线
- 可以看到 `tool_failed` 聚合结果
- 可以按 `intent` 和 `errorType` 筛选

---

## 15. 第二阶段详细交付范围

### 需要完成

1. AI 运价专项页
2. RAG 专项页
3. 多文件聚合统计
4. 更细的业务筛选
5. 图表化统计展示

### 验收标准

- 能单独查看 `rate_query` 链路统计
- 能单独查看 `rag` 链路统计
- 能看出“接口成功但无报价”的占比
- 能看出 RAG 的文档命中情况

---

## 16. Codex CLI 开发时的建议顺序

你后续让 Codex CLI 落地时，建议按下面顺序推进：

### 第一步

初始化 Next.js 项目与 shadcn/ui。

### 第二步

先实现 `lib/logs`：

- `types.ts`
- `file-service.ts`
- `jsonl-parser.ts`
- `request-aggregator.ts`
- `session-aggregator.ts`
- `metrics.ts`

### 第三步

实现 API：

- `/api/log-files`
- `/api/log-summary`
- `/api/requests`
- `/api/requests/[id]`
- `/api/sessions`
- `/api/errors`

### 第四步

实现页面：

- `/`
- `/files`
- `/requests`
- `/requests/[id]`
- `/sessions`
- `/errors`

### 第五步

补第二阶段页面：

- `/quote-monitor`
- `/rag-monitor`

---

## 17. 风险点

## 17.1 中文乱码

当前样本日志已经出现乱码。

第一版策略：

- 平台照样展示
- 先不在平台层做复杂编码修复

## 17.2 日志字段不稳定

并不是每条日志都有完整结构化字段。

第一版策略：

- 聚合时允许缺字段
- 详情页保留原始日志兜底

## 17.3 多文件加载性能

未来日志文件多了以后，不能每次前端都拉全量。

第一版策略：

- 后端先按文件聚合
- 页面分页
- 优先按单文件查看

第二阶段再考虑更强缓存和预聚合。

## 17.4 线上安全

虽然不做登录注册，但至少要注意：

- 只读日志目录
- 禁止任意路径读取
- 不暴露服务器绝对路径到前端

---

## 18. 结论

这套技术方案的核心不是“做一个漂亮 Dashboard”，而是：

> 先把结构化日志真正变成一个可排障、可回放、可聚合的 Next.js 全栈工作台。

如果按这份方案落地，第一、第二阶段已经足够支撑你当前的主要目标：

- 追踪 AI 询价问题
- 分析 RAG 检索问题
- 快速回放单次请求
- 对比不同日志文件的运行情况

而且这份结构后面继续接 AI 归因能力，也不会推倒重来。
