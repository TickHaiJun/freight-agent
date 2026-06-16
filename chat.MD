# 前端聊天室调用使用案例

本文档用于前端开发聊天室时对接当前项目的聊天接口，基于当前实际实现整理，不是旧版示例。

适用接口：

- `POST /api/chat`
- `GET /health`

接口特点：

- 返回格式是 `SSE` 流式响应
- AI 文本按 `text` 事件逐字返回
- 每轮结束会返回 `context`
- 多轮对话必须把上一轮的 `context` 原样传回

---

## 1. 接口地址

本地开发常见地址：

```text
http://127.0.0.1:8012
```

聊天接口：

```text
POST /api/chat
Content-Type: application/json
```

健康检查：

```text
GET /health
```

---

## 2. 请求体格式

前端每次调用 `/api/chat` 时，请求体格式如下：

```json
{
  "session_id": "web_xxx",
  "message": "用户输入内容",
  "context": null
}
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `session_id` | `string` | 是 | 会话唯一标识，前端生成并在同一会话内保持不变 |
| `message` | `string` | 是 | 用户本轮消息 |
| `context` | `object \| null` | 否 | 上一轮返回的上下文状态，多轮对话必须传回 |

---

## 3. 当前 context 结构

当前后端实际返回的 `context` 结构如下：

```json
{
  "sfg": "pvg",
  "mdg": "ord",
  "inputWeight": 500,
  "inputVol": 1,
  "hbrq": "2026-04-29",
  "flightType": null,
  "packageType": null,
  "cargoType": null,
  "twoCode": null,
  "gid": null,
  "query_completed": true
}
```

字段说明：

| 字段 | 类型 | 说明 |
|---|---|---|
| `sfg` | `string \| null` | 始发港机场代码 |
| `mdg` | `string \| null` | 目的港机场代码 |
| `inputWeight` | `number \| null` | 重量，单位 kg |
| `inputVol` | `number \| null` | 体积，单位 CBM |
| `hbrq` | `string \| null` | 单日期查询日期 |
| `flightType` | `string \| null` | 航班类型，如直达/中转 |
| `packageType` | `string \| null` | 包装类型，如托盘/散货 |
| `cargoType` | `string \| null` | 货类，如普货 |
| `twoCode` | `string \| null` | 航司二字码 |
| `gid` | `number \| null` | 客户报价 ID |
| `query_completed` | `boolean` | 上一轮是否已经完成一次运价查询 |

前端原则：

1. `context` 不要手动改字段名
2. 收到什么就原样缓存
3. 下一轮原样传回

---

## 4. SSE 响应格式

后端返回 `text/event-stream`。

每条事件格式类似：

```text
data: {"type":"text","content":"已"}
data: {"type":"text","content":"为"}
data: {"type":"text","content":"您"}
...
data: {"type":"context","context":{...}}
data: {"type":"done"}
```

当前事件类型：

| `type` | 说明 |
|---|---|
| `text` | AI 回复文本，逐字返回 |
| `context` | 当前轮最新上下文，前端必须缓存 |
| `error` | 错误提示 |
| `done` | 本轮完成 |

前端建议处理顺序：

1. 收到 `text` 时逐步拼接 AI 回复
2. 收到 `context` 时更新本地会话状态
3. 收到 `done` 时结束本轮加载状态

---

## 5. 前端最小调用示例

```javascript
let currentContext = null;
let currentSessionId = createSessionId();

function createSessionId() {
  return `web_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

async function sendChatMessage(message) {
  const response = await fetch("http://127.0.0.1:8012/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      session_id: currentSessionId,
      message,
      context: currentContext
    })
  });

  if (!response.ok || !response.body) {
    throw new Error(`HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let assistantText = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data: ")) continue;

      const payload = trimmed.slice(6);
      if (!payload) continue;

      const event = JSON.parse(payload);

      if (event.type === "text") {
        assistantText += event.content || "";
        renderAssistantText(assistantText);
      }

      if (event.type === "context") {
        currentContext = event.context || null;
      }

      if (event.type === "error") {
        renderAssistantText(event.content || "请求失败");
      }

      if (event.type === "done") {
        finishAssistantMessage();
      }
    }
  }
}
```

---

## 6. 聊天室开发建议

建议前端维护以下状态：

```javascript
const chatState = {
  sessionId: "web_xxx",
  context: null,
  messages: [],
  isSending: false
};
```

建议消息结构：

```javascript
{
  role: "user" | "assistant",
  content: "文本内容",
  status: "streaming" | "done" | "error"
}
```

推荐流程：

1. 用户点击发送
2. 先把用户消息写入消息列表
3. 创建一条空的 AI 消息，占位显示“正在输入”
4. 调用 `/api/chat`
5. 收到 `text` 事件时，持续更新这条 AI 消息
6. 收到 `context` 时，更新本地 `context`
7. 收到 `done` 时，将 AI 消息标记为完成

---

## 7. 单轮完整询价案例

### 请求

```json
{
  "session_id": "web_001",
  "message": "上海到芝加哥，500公斤，1个立方，4月29日，多少钱",
  "context": null
}
```

### 响应特征

1. `text` 事件逐字返回完整报价内容
2. 最后会返回一个 `context`
3. `context.query_completed` 会变成 `true`

### 前端处理结果

- 展示 AI 报价内容
- 缓存本轮 `context`
- 等下一轮继续追问或重新询价时传回

---

## 8. 多轮补参案例

### 第 1 轮

请求：

```json
{
  "session_id": "web_002",
  "message": "上海到芝加哥多少钱",
  "context": null
}
```

预期：

- AI 不会直接查价
- 会一次性提示缺少：
  - 重量
  - 体积
  - 日期

### 第 2 轮

请求：

```json
{
  "session_id": "web_002",
  "message": "900公斤 4月29日",
  "context": {
    "sfg": "pvg",
    "mdg": "ord",
    "inputWeight": null,
    "inputVol": null,
    "hbrq": null,
    "flightType": null,
    "packageType": null,
    "cargoType": null,
    "twoCode": null,
    "gid": null,
    "query_completed": false
  }
}
```

预期：

- AI 继续提示还缺体积

### 第 3 轮

请求：

```json
{
  "session_id": "web_002",
  "message": "1个立方",
  "context": {
    "sfg": "pvg",
    "mdg": "ord",
    "inputWeight": 900,
    "inputVol": null,
    "hbrq": "2026-04-29",
    "flightType": null,
    "packageType": null,
    "cargoType": null,
    "twoCode": null,
    "gid": null,
    "query_completed": false
  }
}
```

预期：

- 开始返回报价结果
- `query_completed` 变成 `true`

---

## 9. 新一轮询价案例

上一轮已经查完：

- 上海到芝加哥
- 900 公斤
- 1 个立方
- 4 月 29 日

此时用户又发：

```json
{
  "session_id": "web_002",
  "message": "青岛到莫斯科",
  "context": {
    "sfg": "pvg",
    "mdg": "ord",
    "inputWeight": 900,
    "inputVol": 1,
    "hbrq": "2026-04-29",
    "flightType": null,
    "packageType": null,
    "cargoType": null,
    "twoCode": null,
    "gid": null,
    "query_completed": true
  }
}
```

预期行为：

1. 后端识别为新航线询价
2. 不继续沿用旧重量/体积/日期
3. 返回一次性缺参提醒
4. 新 `context` 中：
   - `sfg`、`mdg` 会更新
   - `inputWeight`、`inputVol`、`hbrq` 会变回 `null`

这意味着前端只需要正常传回 `context`，不要额外做“新会话清空逻辑”。

---

## 10. 类似运价案例

当用户输入完整条件，但指定日期没有精确运价时，后端会自动继续查“未来 7 天类似运价”。

### 请求

```json
{
  "session_id": "web_003",
  "message": "北京到上海，500公斤，1个立方，4月23日，多少钱",
  "context": null
}
```

### 可能出现的结果

1. 有精确结果  
   直接返回精确报价 Markdown table

2. 无精确结果但有类似结果  
   返回提示文案 + 类似运价 Markdown table

3. 完全无结果  
   返回人工联系邮箱

前端无需额外区分，只需要正常展示 AI 文本即可。

---

## 11. RAG 问答案例

### 请求

```json
{
  "session_id": "web_004",
  "message": "锂电池货物需要什么声明文件",
  "context": null
}
```

### 前端处理

和报价一样：

1. 正常接收 `text`
2. 正常接收 `context`
3. 正常等待 `done`

注意：

- 即使是 RAG 问答，后端也会返回 `context`
- 前端不要因为是知识问答就丢掉 `context`

---

## 12. 重置会话案例

如果用户点击“重置会话”，前端应该做两件事：

1. 生成新的 `session_id`
2. 把本地 `context` 清空为 `null`

示例：

```javascript
function resetSession() {
  currentSessionId = createSessionId();
  currentContext = null;
}
```

注意：

- 只清空前端本地状态即可
- 后端当前没有单独的“重置会话接口”

---

## 13. 前端注意事项

### 1. 必须使用同一个 session_id

同一个聊天室会话中，多轮对话必须复用同一个 `session_id`。

### 2. 必须回传 context

每轮都要把上一轮的 `context` 带回，否则：

- 多轮补参会断掉
- 新航线询价的上下文判断也可能不准确

### 3. 不要自己推断参数

前端不要自己改动：

- `sfg`
- `mdg`
- `inputWeight`
- `inputVol`
- `hbrq`

由后端来判断和更新即可。

### 4. Markdown 由前端渲染

当前 AI 可能返回：

- Markdown table
- 列表
- 粗体

聊天室前端应支持 Markdown 渲染，而不是直接当纯文本输出。

建议至少支持以下能力：

- 表格渲染
- 段落和换行
- 有序/无序列表
- 粗体
- 引用块

如果前端直接把返回文本塞进普通 `textContent`，运价结果里的报价表格会失去可读性。

### 5. 处理好流式中断

如果 fetch 失败或 `response.body` 不存在：

- 当前轮 AI 消息标记为错误
- 不要污染现有 `context`

---

## 14. 推荐前端联调问题

可以先用下面这些问题做聊天室联调：

### 运价单轮

- 上海到芝加哥，500公斤，1个立方，4月29日，多少钱

### 运价多轮

- 上海到芝加哥多少钱
- 900公斤 4月29日
- 1个立方

### 新航线继续询价

- 青岛到莫斯科

### 业务知识

- 锂电池货物需要什么声明文件

### 非业务兜底

- 你好

---

## 15. 一句话总结

前端聊天室接入当前项目时，最重要的不是请求格式本身，而是两件事：

1. 正确处理 `SSE`
2. 正确缓存并回传 `context`

只要这两点做对，运价多轮补参、RAG 问答、类似运价和新航线切换都能正常工作。
