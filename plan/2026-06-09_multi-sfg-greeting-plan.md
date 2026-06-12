# 多始发港询价与 Greeting 方案评估

## 目标

本次需求只讨论方案，不直接改代码。目标是在不破坏现有 `/api/chat` SSE 协议、不破坏现有单港询价链路的前提下，补齐两项能力：

1. 询价时 `sfg` 从单值升级为支持多个始发港。
2. 用户说“全部查询 / 全部港口 / 所有始发港”等表达时，`sfg` 固定映射为白名单：
   `XMN,CAN,SZX,HKG,SGN,SIN,LAX,NKG,HGH,HFE,NTG,WUX,PVG,CKG,WUH,CTU,XIY,KMG,PEK,PKX,TAO,CGO`
3. 用户输入“你好”等寒暄时，返回新的固定欢迎语：
   `您好！我是唯凯国际AI 小凯，可以作为空运报价与业务支持助手。您可以让我帮您快速查价，也可以帮您看最便宜方案、筛选直飞/中转、指定航司，或者查询业务资料和单证要求。`

## 已确认边界

1. 多始发港传给报价接口时，`sfg` 使用逗号分隔字符串，例如 `pvg,hkg,nkg`。
2. 默认结果展示仍保持现状：
   单次回复只给出当前条件下最优的一条结果。
   当前系统已有“按包装类型分桶给散货/托盘各一条最低价”的现有逻辑，若此次不调整结果策略，应保持原行为不回退。
3. 当用户明确说“显示全部数据”时，再展开完整报价明细。
4. “全部查询”严格按固定白名单执行，不做动态扩展。

## 现状判断

当前系统里，`sfg` 不是只在抽取层单值，而是整条链路都默认单值：

1. 状态层 [`graph/state.py`](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\state.py:5) 中 `sfg` 是 `str | None`。
2. 槽位 Prompt [`graph/prompts.py`](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\prompts.py:14) 明确要求 `sfg` 返回单个三字码。
3. 工具入参 [`tools/air_freight.py`](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\tools\air_freight.py:16) 的 `sfg` 是单字符串。
4. 工具执行 [`graph/nodes.py`](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\nodes.py:2397) 只调用一次 `search_air_freight_rate.invoke(...)`。
5. 结果标准化 [`graph/result_handlers.py`](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\result_handlers.py:24) 也只保存一个 `query.sfg`。
6. “你好/您好”当前会在 [`graph/nodes.py`](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\nodes.py:588) 命中 `small_talk`，然后走 `unknown` 兜底，不是独立 greeting 能力。

结论：

这次需求必须同时改规则识别、LLM 抽取约束、工具调用和结果归并。只改 Prompt 不够，且风险大。

## 推荐方案

### 一、`sfg` 仍在状态里保留为字符串，但语义升级为“逗号分隔代码串”

不建议第一版把 `sfg` 直接改成 `list[str]`。

原因：

1. 现有 `context` 回传和前端缓存已经按字符串工作。
2. 工具层最终也需要传逗号分隔字符串给下游接口。
3. 结果层、日志层、复用确认链路里大量字符串拼接逻辑会更容易兼容。

推荐做法：

1. 内部新增若干辅助函数，将 `sfg` 在节点内按需转成列表处理。
2. `state["sfg"]`、`context["sfg"]`、工具入参 `sfg` 最终都保持字符串。
3. 字符串规范：
   单港：`pvg`
   多港：`pvg,hkg,nkg`
   全部：白名单对应的完整字符串

### 二、识别策略采用“规则优先，LLM 兜底，工具执行前再标准化”

不建议把多始发港识别全部交给 LLM。

推荐三层识别：

1. 第一层：规则直出
   适合高确定性表达，直接命中，不进 LLM 猜测。

   典型规则：
   - `全部查询` / `全部港口` / `所有始发港` / `全部始发港` / `都查一下`
     直接映射到固定白名单。
   - `从上海、香港、南京飞洛杉矶`
     直接抽出多个城市分隔词：`、`、`，`、`,`、`和`、`及`、`以及`、`/`
   - `上海 香港 南京到洛杉矶`
     对连续并列城市做保守拆分。
   - `PVG/HKG/NKG 到 LAX`
     支持直接三字码输入。

2. 第二层：LLM 兜底抽取
   只在规则无法稳定判断时使用。

   例如：
   - `华东几个口岸都看下到洛杉矶`
   - `上海香港都报一下`
   - `国内主要港口都看下`

   这里 LLM 的职责不是自由生成，而是结构化输出：
   - `sfg_mode`: `single | multi | all | unknown`
   - `sfg_values`: `["pvg", "hkg", "nkg"]`
   - `confidence`

3. 第三层：执行前标准化
   无论规则还是 LLM 输出，进入工具前统一做：
   - 去重
   - 转小写
   - 保持白名单顺序或用户输入顺序
   - 最终拼成逗号串

### 三、增加一个“始发港解析器”模块，避免把规则散落在 `nodes.py`

建议新增一个轻量模块，例如：

`graph/origin_parser.py` 或 `graph/route_parser.py`

职责：

1. 维护白名单代码集合与城市到代码映射。
2. 提供规则识别函数。
3. 提供 `normalize_sfg_codes(...)`。
4. 提供 `is_all_origin_query(...)`。
5. 提供 `extract_multi_origin_candidates(...)`。

这样可以避免把多港规则全部堆进 [`graph/nodes.py`](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\nodes.py)。

### 四、追问文案不再只问“从哪个城市/机场发货”，要显式说明支持多个值和全部

推荐文案：

`请问您的始发港是哪里？可以告诉我一个或多个始发城市/机场，例如“上海、香港、南京”；如果要全口岸一起查，也可以直接回复“全部港口”。`

更短版本：

`请问始发港是哪里？支持一个、多个，或直接回复“全部港口”一起查询。`

推荐使用第一版文案，信息更完整，命中更稳。

### 五、Greeting 不走 `unknown` 兜底，建议升级为 `support_info` 的一个子类

推荐新增：

1. `support_info_kind = "greeting"`
2. 在 `intent_node` 的 `small_talk_guard` 命中后，不再写成 `unknown`，而是写成：
   - `intent = "support_info"`
   - `support_info_kind = "greeting"`
3. 在 `support_info_node` 中返回固定欢迎语。

理由：

1. greeting 现在已经不是“兜底无关回复”，而是明确产品能力入口。
2. 后续如果要区分：
   - `你好`
   - `你能做什么`
   - `怎么联系人工`
   这三类都可以统一挂在 `support_info` 路由下，结构更干净。

## 用户可能的问法覆盖

### A. 缺少始发港，系统追问后用户补充

1. `上海`
2. `上海发`
3. `从上海`
4. `上海和香港`
5. `上海、香港、南京`
6. `全部港口`
7. `全部查询`
8. `都查一下`
9. `PVG,HKG,NKG`
10. `上海 香港 南京`

### B. 用户首句直接带多个始发港

1. `从上海、香港、南京飞洛杉矶多少钱`
2. `上海香港南京到洛杉矶，500公斤，1个方，散货，明天走`
3. `PVG/HKG/NKG to LAX 500kg 1cbm`
4. `上海和香港飞洛杉矶都报一下`
5. `从上海、香港或者南京发洛杉矶，哪个便宜`

### C. 用户表达“全部查询”

1. `全部港口查一下洛杉矶`
2. `所有始发港到LAX看下`
3. `全部查询飞洛杉矶`
4. `分公司口岸都查一下`
5. `全部始发港都报一下`

### D. Greeting

1. `你好`
2. `您好`
3. `在吗`
4. `hi`
5. `你好啊`

说明：

1. `谢谢`、`好的`、`收到` 这类短句不一定都要回欢迎语，可以继续按现有 small talk 兜底策略处理。
2. 如果要严格只对“你好/您好/在吗/hi”走 greeting，需要把 small talk 再细分成 `greeting` 和 `acknowledge` 两类。

## 对 LLM 的约束建议

### 槽位提取 Prompt 需要升级

当前 `build_slot_system(...)` 中 `sfg` 被要求返回单个三字码，需要改成：

1. `sfg` 可以返回：
   - 单值：`pvg`
   - 多值：`pvg,hkg,nkg`
   - 全部：固定白名单拼接串
2. 多始发港必须只返回始发港，不得把目的港混入 `sfg`。
3. 如果用户表达的是多个城市，保持输入顺序。
4. 如果用户说“全部港口/全部查询/所有始发港”，直接返回固定白名单串。

### 但不能只依赖 Prompt

原因：

1. 并列中文地名抽取是高风险点。
2. “上海香港南京到洛杉矶”这类紧凑口语，LLM 容易把最后一个城市误判为目的港。
3. “全部查询”如果纯靠 Prompt，后续模型换版本时不稳定。

因此推荐“规则优先 + Prompt 配合”，而不是“Prompt 全兜”。

## 工具执行与结果策略

### 方案 A：一次调用下游接口，直接传 `sfg=pvg,hkg,nkg`

优点：

1. 改动最小。
2. 与已确认的接口传参方式一致。

风险：

1. 需要确认下游接口对逗号分隔 `sfg` 的真实返回结构。
2. 如果下游返回结果里不保留原始始发港字段，后续“显示全部数据”时可能无法按始发港解释。

### 方案 B：Agent 内部按多个 `sfg` 拆成多次调用，再归并结果

优点：

1. 可控性更高。
2. 每条结果天然知道来源始发港。
3. 更利于以后做“哪个始发港最便宜”的解释。

风险：

1. 改动比方案 A 大。
2. 请求次数随始发港个数增加，全部港口场景下会变慢。

### 推荐结论

第一版优先采用方案 A，但代码结构要预留 B 的扩展点。

建议：

1. 先保持 `search_air_freight_rate(...)` 支持直接传逗号串。
2. 在结果标准化时，若下游已返回可区分始发港的字段，则保留到 `quote.raw` 和标准化字段里。
3. 如果后续发现下游接口无法稳定支撑多港混查，再切到方案 B。

## 结果展示策略

你已确认“默认仍保持之前的结果习惯，只给最优一条；用户说显示全部数据再展开”，这里有一个实现细节要明确：

1. 如果当前系统默认是“散货一条最低价 + 托盘一条最低价”，则多始发港场景也应保持这个既有逻辑，不要因多港升级而变成混排多条。
2. 如果当前查询条件里包装类型已经明确，例如用户说了“散货”，则默认只给散货最优一条。
3. “显示全部数据”时，建议在结果文案里补充始发港列或始发港说明，否则用户看不出是哪一个口岸出的价。

因此结果层建议做两件事：

1. 标准化结果里补一个 `origin_code` 或等效字段。
2. Markdown 表格展开时增加“始发港”列。

## 影响范围

### 必改文件

1. [`graph/nodes.py`](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\nodes.py)
   - `intent_node` small talk/greeting 路由
   - `slot_node` 多始发港识别、合并、复用判断
   - `missing_slots` 与追问逻辑
   - 工具调用前的 `sfg` 标准化
2. [`graph/prompts.py`](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\prompts.py)
   - 槽位提取 Prompt 改成支持单值/多值/全部
   - 缺失 `sfg` 的追问文案升级
   - `unknown` greeting 文案不再承担正式欢迎语职责
3. [`graph/state.py`](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\state.py)
   - 视实现需要，补充 `support_info_kind="greeting"` 注释说明
   - 可选补充 `sfg_mode`，但第一版不是必须
4. [`tools/air_freight.py`](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\tools\air_freight.py)
   - `AirFreightInput.sfg` 描述改为支持逗号分隔多值
   - `_build_query_params(...)` 明确允许 `sfg` 逗号串
   - 若需要结果中补始发港解释字段，也在这里埋点
5. [`graph/result_handlers.py`](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\graph\result_handlers.py)
   - 标准化结果结构支持多始发港结果里的始发港字段
   - “显示全部数据”时可展开始发港列

### 建议新增文件

1. `graph/origin_parser.py`
   - 白名单
   - 城市到三字码映射
   - “全部查询”规则
   - 多港拆分/去重/标准化

### 可能受影响但不一定要改

1. [`main.py`](D:\CompanyPlace\AIProject\AiFreightRate\freight-agent\main.py)
   - 如果 `context["sfg"]` 继续保持字符串，则可不改结构，只是自然回传新值
2. RAG 相关文件
   - 本次无需改

## 风险点

1. `sfg` 现在参与了复用确认、新航线识别、城市澄清等逻辑，升级成多值后，简单字符串比较会误判。
2. “上海、香港、南京到洛杉矶”这类句子，如果只靠 LLM，存在把部分城市误识别成目的港的风险。
3. 下游接口若对 `sfg=pvg,hkg,nkg` 支持不稳定，工具层必须准备回退方案。
4. “全部港口”白名单里包含 `LAX`，这在语义上看像目的港，不像始发港；如果这确实是业务白名单，就按配置执行，但需要在代码里明确注释“这是业务指定列表，不按常识裁剪”。
5. 当前测试目录里没有询价链路自动化测试，改动后回归风险偏高。

## 验证方案

### 规则验证

1. `你好`
   - 应返回固定欢迎语
2. `我有一票货发洛杉矶，500公斤，散货，1个立方，明天发，多少钱`
   - 应追问始发港，并明确支持一个、多个或全部
3. `上海、香港、南京`
   - 应把 `sfg` 标准化为对应三字码逗号串
4. `全部港口`
   - 应把 `sfg` 置为固定白名单逗号串
5. `从上海，香港，南京飞洛杉矶多少钱`
   - 应一次识别出多始发港，不再追问 `sfg`

### 结果验证

1. 多始发港默认回复
   - 应保持现有“最优结果”策略，不要一下子展开大列表
2. 用户说 `显示全部数据`
   - 应展开全部数据，且能区分始发港

### 回归验证

1. 单始发港老路径
   - `上海到洛杉矶 500公斤 1个方 散货 明天`
   - 行为不能退化
2. 上一轮查完报价后再说 `那青岛呢`
   - 城市跟进和角色澄清逻辑不能被多港支持破坏
3. `谢谢`、`好的`
   - 不应误触发完整 greeting

## 备选方案

### 备选方案 1：`sfg` 改为 `list[str]`

优点：

1. 类型表达更自然。
2. 逻辑上更清晰。

缺点：

1. 会波及 `context`、日志、Prompt、工具入参、结果结构。
2. 改动面明显大于当前需求。

结论：

不建议第一版采用。

### 备选方案 2：仅改 Prompt，不加规则

优点：

1. 开发快。

缺点：

1. 命中率和稳定性不可控。
2. 调试困难。
3. 后续模型或提示词变化容易回退。

结论：

不建议采用。

## 实施建议顺序

1. 先抽离 `origin_parser`，把多港和全部查询规则固化。
2. 再升级 `intent_node` 的 greeting 路由。
3. 再改槽位 Prompt 与追问文案。
4. 再改工具入参与结果标准化。
5. 最后补最少量的回归测试样例。

## 推荐结论

建议采用以下落地组合：

1. `sfg` 继续保持字符串存储，内部语义改为逗号分隔代码串。
2. 多始发港识别采用“规则优先 + LLM 兜底 + 执行前标准化”。
3. “全部查询”固定映射白名单，不依赖模型猜。
4. greeting 从 `unknown` 兜底提升为 `support_info.greeting`。
5. 默认结果展示保持现状，只在用户说“显示全部数据”时展开，并在展开结果里补始发港维度。

