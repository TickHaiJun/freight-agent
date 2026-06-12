# AI 运价 Agent — 启动与调用指南

## 一、启动服务

### 1. 进入项目目录并激活虚拟环境

```bash
cd D:\CompanyPlace\AI\AiFreightRate\freight-agent
AiEnv\Scripts\activate
```

### 2. 启动命令（必须带 NO_PROXY）

**Windows CMD：**

```cmd
set NO_PROXY=192.168.0.186,127.0.0.1,localhost && uvicorn main:app --host 127.0.0.1 --port 8082 --reload
```

**Windows PowerShell：**

```powershell
$env:NO_PROXY="192.168.0.186,127.0.0.1,localhost"; uvicorn main:app --host 127.0.0.1 --port 8082 --reload
```

**Git Bash / WSL：**

```bash
NO_PROXY="192.168.0.186,127.0.0.1,localhost" uvicorn main:app --host 127.0.0.1 --port 8082 --reload
```

### 3. 永久配置（推荐）

在系统环境变量中添加 `NO_PROXY`，之后启动就不需要每次手动设置：

```
变量名：NO_PROXY
变量值：192.168.0.186,127.0.0.1,localhost
```

设置后直接启动即可：

```bash
uvicorn main:app --host 127.0.0.1 --port 8082 --reload
```

### 4. 验证服务是否正常

```bash
curl http://127.0.0.1:8082/health
```

返回 `{"status":"ok"}` 表示启动成功。

---

## 二、接口说明

```
POST http://127.0.0.1:8082/api/chat
Content-Type: application/json
```

返回格式：SSE（Server-Sent Events）流式响应

---

## 三、调用示例

### 示例 1：一次性提供完整信息

**请求：**

```json
{
  "session_id": "user_001",
  "message": "上海到洛杉矶，500公斤，2个立方，明天发货，查空运价格",
  "context": null
}
```

**响应（SSE 流式）：**

```
data: {"type": "text", "content": "根"}
data: {"type": "text", "content": "据"}
data: {"type": "text", "content": "您"}
...（逐字输出）
```

**完整拼接后的 AI 回复：**

```
根据您的查询条件，共为您找到 2条 从上海浦东（PVG）至洛杉矶（LAX）的空运报价。

报价详情如下：

报价 1
- 路由：直达
- 航班日期：2026-03-12
- 计费重：500.0 kg
- 公斤单价：50.0 元/kg
- 预计总运费：25000.0 元

报价 2
- 路由：经 AAA 中转
- 航班日期：2026-03-12
- 计费重：500.0 kg
- 公斤单价：50.0 元/kg
- 预计总运费：25000.0 元

⚠️ 以上报价仅供参考，不含目的港本地费用及清关费，最终费用以实际订单为准。
如需订舱或获取完整报价，请联系我们的销售团队。
```

**最后返回槽位状态和结束标志：**

```
data: {"type": "context", "context": {"sfg": "pvg", "mdg": "lax", "inputWeight": 500, "inputVol": 2.0, "hbrq": "2026-03-12"}}
data: {"type": "done"}
```

---

### 示例 2：多轮对话（逐步收集信息）

**第 1 轮 — 用户只说了始发和目的：**

```json
{
  "session_id": "user_002",
  "message": "我想查上海到纽约的空运价格",
  "context": null
}
```

AI 回复：`请问这批货的总重量是多少公斤？`

返回的 context：

```json
{"sfg": "pvg", "mdg": "jfk", "inputWeight": null, "inputVol": null, "hbrq": null}
```

**第 2 轮 — 用户补充重量：**

```json
{
  "session_id": "user_002",
  "message": "300公斤",
  "context": {"sfg": "pvg", "mdg": "jfk", "inputWeight": null, "inputVol": null, "hbrq": null}
}
```

AI 回复：`请问货物的总体积是多少立方米（CBM）？如不清楚可告诉我长宽高尺寸。`

返回的 context：

```json
{"sfg": "pvg", "mdg": "jfk", "inputWeight": 300, "inputVol": null, "hbrq": null}
```

**第 3 轮 — 用户补充体积：**

```json
{
  "session_id": "user_002",
  "message": "1.5个立方",
  "context": {"sfg": "pvg", "mdg": "jfk", "inputWeight": 300, "inputVol": null, "hbrq": null}
}
```

AI 回复：`请问货物大概什么时候可以起运？（如没有特别要求，我们将以最近班期为您查询）`

返回的 context：

```json
{"sfg": "pvg", "mdg": "jfk", "inputWeight": 300, "inputVol": 1.5, "hbrq": null}
```

**第 4 轮 — 用户补充日期：**

```json
{
  "session_id": "user_002",
  "message": "越快越好",
  "context": {"sfg": "pvg", "mdg": "jfk", "inputWeight": 300, "inputVol": 1.5, "hbrq": null}
}
```

AI 回复：返回完整报价结果

返回的 context（全部填充完毕）：

```json
{"sfg": "pvg", "mdg": "jfk", "inputWeight": 300, "inputVol": 1.5, "hbrq": "2026-03-11"}
```

---

### 示例 3：非运价查询

**闲聊：**

```json
{
  "session_id": "user_003",
  "message": "你好",
  "context": null
}
```

AI 回复：`您好！我是专业的国际空运报价助手，可以帮您查询空运运价。请问您有空运报价需求吗？`

**业务咨询：**

```json
{
  "session_id": "user_004",
  "message": "空运清关需要什么资料",
  "context": null
}
```

AI 回复：`感谢您的咨询！业务详情查询功能正在建设中，如需了解具体业务信息，请联系我们的客服团队，我们将为您提供专业解答。`

---

## 四、前端 JavaScript 对接代码

```javascript
// 会话级变量，保存槽位状态
let currentContext = null;

async function sendMessage(sessionId, message) {
  const response = await fetch('http://127.0.0.1:8082/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      message: message,
      context: currentContext  // 每轮传回上一轮的 context
    })
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let fullText = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value, { stream: true });
    const lines = chunk.split('\n');

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;

      const data = JSON.parse(line.slice(6));

      switch (data.type) {
        case 'text':
          // 逐字追加到聊天气泡中
          fullText += data.content;
          updateChatBubble(fullText);
          break;

        case 'context':
          // 保存槽位状态，下一轮自动传回
          currentContext = data.context;
          break;

        case 'error':
          showError(data.content);
          break;

        case 'done':
          // 本轮结束
          break;
      }
    }
  }

  return fullText;
}

// 使用示例
sendMessage('session_123', '上海到洛杉矶，500公斤，2个方，查空运报价');
```

---

## 五、Python 调用示例

```python
import httpx
import json

API_URL = "http://127.0.0.1:8082/api/chat"

def chat(session_id: str, message: str, context: dict = None) -> tuple[str, dict]:
    """
    发送消息并解析 SSE 响应
    返回：(AI回复文本, 槽位状态context)
    """
    transport = httpx.HTTPTransport(proxy=None)
    with httpx.Client(timeout=120, transport=transport) as client:
        r = client.post(API_URL, json={
            "session_id": session_id,
            "message": message,
            "context": context
        })

    full_text = ""
    saved_context = None

    for line in r.text.split("\n"):
        if not line.startswith("data: "):
            continue
        data = json.loads(line[6:])
        if data["type"] == "text":
            full_text += data["content"]
        elif data["type"] == "context":
            saved_context = data["context"]

    return full_text, saved_context


# ===== 调用示例 =====

# 第1轮
reply, ctx = chat("test_001", "深圳到法兰克福，800公斤，3个立方，下周一发货，查空运")
print("AI:", reply)
print("Context:", ctx)

# 如果需要多轮，把 ctx 传回去
# reply2, ctx2 = chat("test_001", "改成1000公斤", ctx)
```

---

## 六、cURL 调用示例

```bash
curl -X POST http://127.0.0.1:8082/api/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test001","message":"上海到洛杉矶，500公斤，2个立方，明天发货，查空运价格","context":null}'
```

多轮对话（带 context）：

```bash
curl -X POST http://127.0.0.1:8082/api/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test001","message":"300公斤","context":{"sfg":"pvg","mdg":"lax","inputWeight":null,"inputVol":null,"hbrq":null}}'
```

---

## 七、SSE 响应事件类型汇总

| type | 说明 | 示例 |
|------|------|------|
| `text` | AI 回复内容（逐字） | `{"type":"text","content":"请"}` |
| `context` | 槽位状态（前端需缓存） | `{"type":"context","context":{...}}` |
| `error` | 错误信息 | `{"type":"error","content":"系统异常：..."}` |
| `done` | 本轮结束标志 | `{"type":"done"}` |

**前端处理顺序：** 先接收所有 `text` 拼接显示 → 接收 `context` 缓存 → 收到 `done` 结束本轮。
