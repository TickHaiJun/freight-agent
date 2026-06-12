# CLAUDE.md — AI 运价 Agent 项目开发指南

## 工作语言
- 全程使用中文思考和回复
- 每步执行前说明意图
- 遇到决策说明理由
- 完成后总结结果

## 项目概述
为公司门户网站开发一个 AI 运价查询 Agent，客户通过聊天窗口查询空运运价。
后端提供 SSE 流式 API，前端直接对接。

---

## 技术栈
- **Python 3.11+**
- **FastAPI** — HTTP 服务、SSE 流式输出
- **LangGraph V1** — Agent 流程编排
- **LangChain V1** — Tool 封装、Prompt 管理
- **DeepSeek API** — 大模型（兼容 OpenAI 格式）
- **uvicorn** — 服务启动（Windows 环境）

---

## 项目目录结构（严格按此创建）

```
freight-agent/
├── CLAUDE.md
├── main.py                  # FastAPI 入口
├── config.py                # 环境变量配置
├── requirements.txt
├── .env                     # 环境变量（不提交 git）
├── graph/
│   ├── __init__.py
│   ├── agent.py             # LangGraph 主流程构建
│   ├── nodes.py             # 所有节点函数
│   ├── state.py             # AgentState 定义
│   └── prompts.py           # 所有 Prompt 模板（集中管理）
├── tools/
│   ├── __init__.py
│   └── air_freight.py       # 空运运价工具
└── rag/
    └── __init__.py          # RAG 预留缺口，暂为占位实现
```

---

## 环境变量（.env）

```env
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

FREIGHT_API_BASE=http://192.168.0.186:9000
```

---

## config.py

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    freight_api_base: str

    class Config:
        env_file = ".env"

settings = Settings()
```

---

## requirements.txt

```
fastapi
uvicorn
python-dotenv
pydantic-settings
langchain
langchain-openai
langgraph
httpx
sse-starlette
```

---

## AgentState 定义（graph/state.py）

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    # 对话历史（LangGraph 标准方式）
    messages: Annotated[list, add_messages]

    # 意图识别结果
    intent: str | None          # "rate_query" | "rag" | "unknown"

    # 运价查询槽位（必填4个 + 选填1个）
    sfg: str | None             # 始发港机场代码（小写，如 pvg）
    mdg: str | None             # 目的港机场代码（小写，如 lax）
    inputWeight: float | None   # 货物重量 kg
    inputVol: float | None      # 货物体积 CBM
    hbrq: str | None            # 航班日期 YYYY-MM-DD（必填）

    # 控制流
    missing_slots: list[str]    # 当前缺失的必填字段名列表
    query_ready: bool           # True = 参数齐全可以调接口

    # 接口结果
    api_result: dict | None     # 原始接口返回
    api_error: str | None       # 接口异常描述

    # RAG 预留
    rag_query: str | None
```

---

## 运价工具（tools/air_freight.py）

```python
import httpx
from datetime import date
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from config import settings

class AirFreightInput(BaseModel):
    sfg: str = Field(
        description=(
            "始发港机场三字代码，小写。"
            "根据用户提到的城市或地区推断最近的国际机场代码。"
            "例：上海/浦东→pvg，深圳→szx，广州→can，北京/首都→pek，北京大兴→pkx，"
            "杭州→hgh，成都→ctu，重庆→ckg，厦门→xmn，武汉→wuh，西安→xiy，"
            "南京→nkg，昆明→kmg，郑州→cgo，天津→tna。"
            "如用户所在城市无国际机场，推荐距离最近的机场，并在回复中说明。"
            "必须是小写三字代码。"
        )
    )
    mdg: str = Field(
        description=(
            "目的港机场三字代码，小写。"
            "根据用户提到的目的地城市/国家推断最近的主要国际机场代码。"
            "例：洛杉矶/LA→lax，纽约→jfk，芝加哥→ord，迈阿密→mia，"
            "法兰克福→fra，伦敦→lhr，巴黎→cdg，阿姆斯特丹→ams，"
            "马德里→mad，米兰→mxp，东京→nrt，大阪→kix，首尔→icn，"
            "悉尼→syd，迪拜→dxb，多伦多→yyz，温哥华→yvr，墨西哥城→mex。"
            "如用户说的是国家而非城市，选该国最主要的货运机场。"
            "必须是小写三字代码。"
        )
    )
    inputWeight: float = Field(
        description=(
            "货物毛重，单位：kg（公斤）。"
            "用户可能说'500公斤'、'0.5吨'、'500kg'，统一换算为 kg 的数值。"
            "1吨=1000kg。必须大于0。"
        )
    )
    inputVol: float = Field(
        description=(
            "货物体积，单位：CBM（立方米）。"
            "用户可能说'1.5方'、'1.5立方'、'1.5CBM'，统一换算为 CBM 数值。"
            "如用户提供的是长×宽×高(cm)，换算：长×宽×高÷1000000=CBM。"
            "必须大于0。"
        )
    )
    hbrq: str = Field(
        description=(
            "期望航班日期，格式 YYYY-MM-DD。"
            "用户可能说'下周一'、'3月10号'、'越快越好'等，"
            "转换为具体日期字符串。"
            "如用户说越快越好或没有偏好，使用今天的日期。"
        )
    )

@tool(args_schema=AirFreightInput)
def search_air_freight_rate(
    sfg: str,
    mdg: str,
    inputWeight: float,
    inputVol: float,
    hbrq: str,
) -> dict:
    """
    查询空运运价。当用户询问空运运费/报价/价格时调用此工具。
    调用前必须确认：始发港(sfg)、目的港(mdg)、货物重量(inputWeight)、
    货物体积(inputVol)、航班日期(hbrq) 五个参数均已收集完毕。
    任何参数缺失时不要调用此工具，应先向用户追问。
    """
    # 计算计费重（航空计费规则：重量和体积重取较大值）
    # 体积重 = CBM * 1000 / 6 = kg（即 1CBM = 166.67kg）
    volume_weight = round(inputVol * 1000 / 6, 2)
    charge_weight = max(inputWeight, volume_weight)

    url = f"{settings.freight_api_base}/fee/api/airFreightFee/getUnitPrice"
    params = {
        "sfg": sfg.lower(),
        "mdg": mdg.lower(),
        "inputWeight": inputWeight,
        "inputVol": inputVol,
        "hbrq": hbrq,
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        return {"success": False, "error": "TIMEOUT", "message": "运价接口请求超时，请稍后重试"}
    except httpx.HTTPError as e:
        return {"success": False, "error": "HTTP_ERROR", "message": f"接口请求失败：{str(e)}"}
    except Exception as e:
        return {"success": False, "error": "UNKNOWN", "message": f"系统异常：{str(e)}"}

    return {
        "success": data.get("resultsuccess", False),
        "status": data.get("resultstatus"),
        "message": data.get("resultmessage"),
        "quotes": data.get("resultdata", []),
        "charge_weight": charge_weight,       # 计费重（kg）
        "actual_weight": inputWeight,
        "volume_weight": volume_weight,
        "sfg": sfg,
        "mdg": mdg,
        "hbrq": hbrq,
    }
```

---

## Prompt 模板（graph/prompts.py）

所有 Prompt 集中在此文件管理，修改提示词只改这里。

```python
from datetime import date

TODAY = date.today().strftime("%Y-%m-%d")

# ─────────────────────────────────────────────────────
# 1. 意图识别 Prompt
# ─────────────────────────────────────────────────────
INTENT_SYSTEM = """你是一个专业的国际物流客服助手，服务于一家空运物流公司。
你的职责是识别用户意图，分为以下三类：

- rate_query：用户想查询空运运价/报价/费用/多少钱/怎么收费
- rag：用户咨询业务相关问题（如：时效、流程、包装要求、清关、限制货物等）
- unknown：无法识别/闲聊/投诉/与物流无关

只返回以下三个值之一：rate_query / rag / unknown
不要解释，不要多余内容，只返回分类结果。"""

INTENT_USER = "用户说：{message}"

# ─────────────────────────────────────────────────────
# 2. 槽位提取 Prompt
# ─────────────────────────────────────────────────────
SLOT_SYSTEM = f"""你是国际空运报价助手，今天日期是 {TODAY}。

你的任务是从对话历史中提取运价查询所需的参数，返回 JSON 格式。

【需要提取的字段】
- sfg: 始发港机场三字代码（小写）。根据城市推断最近国际机场。
- mdg: 目的港机场三字代码（小写）。根据城市/国家推断主要货运机场。
- inputWeight: 货物重量，单位 kg，数字类型。
- inputVol: 货物体积，单位 CBM，数字类型。
- hbrq: 航班日期，格式 YYYY-MM-DD。用户说"越快越好"或未说明则用今天日期 {TODAY}。

【港口推断规则】
- 只从对话中推断，不要编造
- 城市无机场时推荐最近机场
- 必须返回小写三字代码

【返回格式】
严格返回 JSON，不要有任何多余内容：
{{
  "sfg": "pvg" 或 null,
  "mdg": "lax" 或 null,
  "inputWeight": 500 或 null,
  "inputVol": 1.5 或 null,
  "hbrq": "2026-03-10" 或 null
}}"""

SLOT_USER = "对话历史：\n{history}"

# ─────────────────────────────────────────────────────
# 3. 追问 Prompt（每次只问一个缺失字段）
# ─────────────────────────────────────────────────────
ASK_SYSTEM = """你是专业的国际空运报价助手，说话简洁友好。
根据当前缺失的字段，向用户追问，一次只问一个问题。
不要说"好的"、"明白了"等多余的话，直接问。"""

ASK_USER = """
已知信息：
- 始发港：{sfg}
- 目的港：{mdg}
- 货物重量：{inputWeight}
- 货物体积：{inputVol}
- 航班日期：{hbrq}

当前最需要补充的字段：{missing_field}

请用一句话向用户追问这个信息。
追问规则：
- 缺 sfg（始发港）：问"请问货物从哪个城市/机场发货？"
- 缺 mdg（目的港）：问"请问货物要运往哪个城市或国家？"
- 缺 inputWeight（重量）：问"请问这批货的总重量是多少公斤？"
- 缺 inputVol（体积）：问"请问货物的总体积是多少立方米（CBM）？如不清楚可告诉我长宽高尺寸。"
- 缺 hbrq（航班日期）：问"请问货物大概什么时候可以起运？（如没有特别要求，我们将以最近班期为您查询）"
"""

# ─────────────────────────────────────────────────────
# 4. 结果语义化 Prompt
# ─────────────────────────────────────────────────────
RESULT_SYSTEM = """你是专业的国际空运报价助手，擅长将运价数据解读为客户易懂的中文报价说明。
说话专业但友好，回答结构清晰。不要编造任何接口中没有的数据。"""

RESULT_USER = """
请根据以下运价查询结果，用中文向客户展示报价信息。

【查询条件】
- 始发港：{sfg}（{sfg_upper}）
- 目的港：{mdg}（{mdg_upper}）
- 货物重量：{actual_weight} kg
- 货物体积：{inputVol} CBM
- 计费重：{charge_weight} kg（取实重与体积重的较大值，体积重={volume_weight}kg）
- 航班日期：{hbrq}

【接口返回报价列表】
{quotes_text}

【展示要求】
1. 先用一句话简述查询结果概况（共找到几条报价）
2. 逐条展示每条报价，格式如下：
   - 路由：直达 或 经XXX中转
   - 航班日期：XXXX-XX-XX
   - 计费重：XXX kg
   - 公斤单价：XX 元/kg
   - 预计总运费：XXXXX 元
3. 如有多条，指出最优方案（最低价）
4. 末尾统一添加免责声明：
   "⚠️ 以上报价仅供参考，不含目的港本地费用及清关费，最终费用以实际订单为准。如需订舱或获取完整报价，请联系我们的销售团队。"

【无结果时】
如果报价列表为空，回复：
"非常抱歉，暂未查询到 {sfg_upper}→{mdg_upper} 的空运报价。可能原因：该航线暂无在线报价，或货物类型有限制。建议您联系我们的销售团队获取人工报价。"
"""

# ─────────────────────────────────────────────────────
# 5. 兜底回复 Prompt
# ─────────────────────────────────────────────────────
FALLBACK_RESPONSES = {
    "rag": "感谢您的咨询！业务详情查询功能正在建设中，如需了解具体业务信息，请联系我们的客服团队，我们将为您提供专业解答。",
    "unknown": "您好！我是专业的国际空运报价助手，可以帮您查询空运运价。请问您有空运报价需求吗？",
    "api_timeout": "抱歉，运价系统响应超时，请稍后再试。如需紧急报价，请联系我们的销售团队。",
    "api_error": "抱歉，运价查询系统暂时异常，请稍后重试。",
    "no_result": "抱歉，暂未查询到符合条件的运价，建议联系我们的销售团队获取人工报价。",
}
```

---

## LangGraph 节点实现（graph/nodes.py）

```python
import json
from datetime import date
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from graph.state import AgentState
from graph.prompts import (
    INTENT_SYSTEM, INTENT_USER,
    SLOT_SYSTEM, SLOT_USER,
    ASK_SYSTEM, ASK_USER,
    RESULT_SYSTEM, RESULT_USER,
    FALLBACK_RESPONSES,
)
from tools.air_freight import search_air_freight_rate
from config import settings

def get_llm(streaming=False):
    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        streaming=streaming,
        temperature=0.2,
    )

# ── 1. 意图识别节点 ─────────────────────────────────
def intent_node(state: AgentState) -> AgentState:
    last_message = state["messages"][-1].content
    llm = get_llm()
    response = llm.invoke([
        SystemMessage(content=INTENT_SYSTEM),
        HumanMessage(content=INTENT_USER.format(message=last_message)),
    ])
    intent = response.content.strip().lower()
    if intent not in ["rate_query", "rag", "unknown"]:
        intent = "unknown"
    return {**state, "intent": intent}

# ── 2. 槽位提取节点 ─────────────────────────────────
def slot_node(state: AgentState) -> AgentState:
    # 构建对话历史文本
    history_lines = []
    for msg in state["messages"]:
        role = "用户" if isinstance(msg, HumanMessage) else "助手"
        history_lines.append(f"{role}：{msg.content}")
    history_text = "\n".join(history_lines)

    llm = get_llm()
    response = llm.invoke([
        SystemMessage(content=SLOT_SYSTEM),
        HumanMessage(content=SLOT_USER.format(history=history_text)),
    ])

    # 解析 JSON，容错处理
    try:
        slots = json.loads(response.content.strip())
    except json.JSONDecodeError:
        # 尝试提取 JSON 部分
        content = response.content
        start = content.find("{")
        end = content.rfind("}") + 1
        try:
            slots = json.loads(content[start:end])
        except Exception:
            slots = {}

    # 合并已有槽位（不覆盖已确认的值）
    updated = {
        "sfg": slots.get("sfg") or state.get("sfg"),
        "mdg": slots.get("mdg") or state.get("mdg"),
        "inputWeight": slots.get("inputWeight") or state.get("inputWeight"),
        "inputVol": slots.get("inputVol") or state.get("inputVol"),
        "hbrq": slots.get("hbrq") or state.get("hbrq"),
    }

    # 判断缺失字段
    required = ["sfg", "mdg", "inputWeight", "inputVol", "hbrq"]
    missing = [f for f in required if not updated.get(f)]
    query_ready = len(missing) == 0

    return {
        **state,
        **updated,
        "missing_slots": missing,
        "query_ready": query_ready,
    }

# ── 3. 追问节点 ─────────────────────────────────────
def ask_node(state: AgentState) -> AgentState:
    missing_field = state["missing_slots"][0]  # 每次只问第一个缺失字段
    llm = get_llm(streaming=True)

    def format_val(v):
        return str(v) if v is not None else "未提供"

    prompt = ASK_USER.format(
        sfg=format_val(state.get("sfg")),
        mdg=format_val(state.get("mdg")),
        inputWeight=format_val(state.get("inputWeight")),
        inputVol=format_val(state.get("inputVol")),
        hbrq=format_val(state.get("hbrq")),
        missing_field=missing_field,
    )
    response = llm.invoke([
        SystemMessage(content=ASK_SYSTEM),
        HumanMessage(content=prompt),
    ])
    return {
        **state,
        "messages": state["messages"] + [AIMessage(content=response.content)],
    }

# ── 4. 工具调用节点 ──────────────────────────────────
def tool_node(state: AgentState) -> AgentState:
    result = search_air_freight_rate.invoke({
        "sfg": state["sfg"],
        "mdg": state["mdg"],
        "inputWeight": state["inputWeight"],
        "inputVol": state["inputVol"],
        "hbrq": state["hbrq"],
    })
    if not result.get("success"):
        error = result.get("error", "UNKNOWN")
        if error == "TIMEOUT":
            msg = FALLBACK_RESPONSES["api_timeout"]
        else:
            msg = FALLBACK_RESPONSES["api_error"]
        return {
            **state,
            "api_result": None,
            "api_error": msg,
            "messages": state["messages"] + [AIMessage(content=msg)],
        }
    return {**state, "api_result": result, "api_error": None}

# ── 5. 结果语义化节点 ────────────────────────────────
def result_node(state: AgentState) -> AgentState:
    api_result = state["api_result"]
    quotes = api_result.get("quotes", [])

    # 格式化报价列表为文本
    if quotes:
        quotes_lines = []
        for i, q in enumerate(quotes, 1):
            quotes_lines.append(
                f"报价{i}：路由={q.get('zzg','未知')}，"
                f"航班日期={q.get('hbrq')}，"
                f"公斤单价={q.get('unitPrice')}元，"
                f"总运费={q.get('priceTotal')}元"
            )
        quotes_text = "\n".join(quotes_lines)
    else:
        quotes_text = "无报价数据"

    llm = get_llm(streaming=True)
    prompt = RESULT_USER.format(
        sfg=api_result["sfg"],
        sfg_upper=api_result["sfg"].upper(),
        mdg=api_result["mdg"],
        mdg_upper=api_result["mdg"].upper(),
        actual_weight=api_result["actual_weight"],
        inputVol=state["inputVol"],
        charge_weight=api_result["charge_weight"],
        volume_weight=api_result["volume_weight"],
        hbrq=api_result["hbrq"],
        quotes_text=quotes_text,
    )
    response = llm.invoke([
        SystemMessage(content=RESULT_SYSTEM),
        HumanMessage(content=prompt),
    ])
    return {
        **state,
        "messages": state["messages"] + [AIMessage(content=response.content)],
    }

# ── 6. 兜底节点 ──────────────────────────────────────
def fallback_node(state: AgentState) -> AgentState:
    intent = state.get("intent", "unknown")
    msg = FALLBACK_RESPONSES.get(intent, FALLBACK_RESPONSES["unknown"])
    return {
        **state,
        "messages": state["messages"] + [AIMessage(content=msg)],
    }
```

---

## LangGraph 主流程（graph/agent.py）

```python
from langgraph.graph import StateGraph, END
from graph.state import AgentState
from graph.nodes import (
    intent_node, slot_node, ask_node,
    tool_node, result_node, fallback_node,
)

def route_intent(state: AgentState) -> str:
    intent = state.get("intent")
    if intent == "rate_query":
        return "slot"
    return "fallback"

def route_slot(state: AgentState) -> str:
    if state.get("query_ready"):
        return "tool"
    return "ask"

def route_tool(state: AgentState) -> str:
    if state.get("api_error"):
        return END
    return "result"

def build_agent():
    graph = StateGraph(AgentState)

    graph.add_node("intent", intent_node)
    graph.add_node("slot", slot_node)
    graph.add_node("ask", ask_node)
    graph.add_node("tool", tool_node)
    graph.add_node("result", result_node)
    graph.add_node("fallback", fallback_node)

    graph.set_entry_point("intent")

    graph.add_conditional_edges("intent", route_intent, {
        "slot": "slot",
        "fallback": "fallback",
    })
    graph.add_conditional_edges("slot", route_slot, {
        "tool": "tool",
        "ask": "ask",
    })
    graph.add_conditional_edges("tool", route_tool, {
        "result": "result",
        END: END,
    })

    graph.add_edge("ask", END)
    graph.add_edge("result", END)
    graph.add_edge("fallback", END)

    return graph.compile()

agent = build_agent()
```

---

## FastAPI 入口（main.py）

```python
import json
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from langchain_core.messages import HumanMessage
from graph.agent import agent
from graph.state import AgentState

app = FastAPI(title="AI 运价 Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境改为实际域名
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    session_id: str
    message: str
    # 传入历史槽位状态（多轮对话用）
    context: dict | None = None

@app.post("/api/chat")
async def chat(request: ChatRequest):
    async def generate():
        # 初始化状态
        initial_state: AgentState = {
            "messages": [HumanMessage(content=request.message)],
            "intent": None,
            "sfg": request.context.get("sfg") if request.context else None,
            "mdg": request.context.get("mdg") if request.context else None,
            "inputWeight": request.context.get("inputWeight") if request.context else None,
            "inputVol": request.context.get("inputVol") if request.context else None,
            "hbrq": request.context.get("hbrq") if request.context else None,
            "missing_slots": [],
            "query_ready": False,
            "api_result": None,
            "api_error": None,
            "rag_query": None,
        }

        try:
            # 同步执行 agent（LangGraph 同步调用）
            final_state = await asyncio.to_thread(agent.invoke, initial_state)

            # 取最后一条 AI 消息流式输出
            ai_messages = [
                m for m in final_state["messages"]
                if hasattr(m, "type") and m.type == "ai"
                or m.__class__.__name__ == "AIMessage"
            ]

            if ai_messages:
                content = ai_messages[-1].content
                # 模拟流式：按字输出
                for char in content:
                    yield {
                        "data": json.dumps({"type": "text", "content": char}, ensure_ascii=False)
                    }
                    await asyncio.sleep(0.02)

            # 返回槽位状态（前端缓存用于下一轮）
            context_data = {
                "sfg": final_state.get("sfg"),
                "mdg": final_state.get("mdg"),
                "inputWeight": final_state.get("inputWeight"),
                "inputVol": final_state.get("inputVol"),
                "hbrq": final_state.get("hbrq"),
            }
            yield {
                "data": json.dumps({"type": "context", "context": context_data}, ensure_ascii=False)
            }
            yield {"data": json.dumps({"type": "done"})}

        except Exception as e:
            yield {
                "data": json.dumps({"type": "error", "content": f"系统异常：{str(e)}"}, ensure_ascii=False)
            }
            yield {"data": json.dumps({"type": "done"})}

    return EventSourceResponse(generate())

@app.get("/health")
async def health():
    return {"status": "ok"}
```

---

## RAG 预留缺口（rag/__init__.py）

```python
# RAG 业务问答模块 - 预留缺口
# 待业务文档整理完成后接入 Chroma + 向量模型

def query_knowledge_base(question: str) -> str:
    """
    TODO:
    1. 向量化 question
    2. Chroma 检索 Top-K 文档
    3. 组装 Prompt + 生成带引用的回答
    """
    return "业务咨询功能正在建设中，如需帮助请联系客服。"
```

---

## 启动命令

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务（Windows）
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 测试接口
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test001","message":"我有一批货从上海到洛杉矶，帮我查空运价格"}'
```

---

## 开发注意事项（必读）

1. **所有 Prompt 只在 `graph/prompts.py` 修改**，节点代码不硬写提示词
2. **港口推断完全交给 LLM**，代码层不做别名映射表
3. **槽位状态由前端 context 字段传递**，实现多轮对话记忆
4. **计费重逻辑在 `tools/air_freight.py` 的 Python 代码里计算**，不依赖 LLM
5. **后续新增运输方式**（海运/铁路），在 `tools/` 下新建文件，在 `graph/nodes.py` 的 `tool_node` 里按 `transport_mode` 分发即可
6. **RAG 接入时**，只需完善 `rag/__init__.py` 的 `query_knowledge_base` 函数，`fallback_node` 里已预留调用入口
7. **不要在代码里硬写 API Key 和接口地址**，全部从 `config.py` 读取环境变量
8. **错误处理**：接口超时/异常一律走 `FALLBACK_RESPONSES`，不把技术错误暴露给用户