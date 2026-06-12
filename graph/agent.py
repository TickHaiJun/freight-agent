from langgraph.graph import StateGraph, END
from graph.state import AgentState
from graph.nodes import (
    intent_node, slot_node, ask_node,
    tool_node, result_node, fallback_node,
    rag_retrieve_node, rag_answer_node,
    result_analysis_node,
    result_reference_node,
    support_info_node,
)
# 流程编排层

def route_intent(state: AgentState) -> str:
    """
    意图路由函数。

    作用：
    - 读取 state 中已经由 intent_node 写入的 intent
    - 根据 intent 决定下一步进入哪个节点

    路由规则：
    - rate_query -> 进入 slot 节点，继续做槽位抽取
    - rag -> 进入 rag_retrieve 节点，走 RAG 检索链路
    - 其他情况 -> 进入 fallback 节点，返回兜底回复
    """
    intent = state.get("intent")

    # 如果识别为运价查询，则进入槽位提取节点
    if intent == "rate_query":
        return "slot"

    # 如果识别为“围绕上一批结果继续分析”，直接进入结果分析链
    if intent == "result_analysis":
        return "result_analysis"

    # 如果识别为“围绕当前结果追问某个字段”，进入结果引用解释链。
    if intent == "result_reference":
        return "result_reference"

    # 业务服务类与能力说明类问题，直接进入轻量信息答复节点。
    if intent == "support_info":
        return "support_info"

    # 如果识别为知识库问答，则进入 RAG 检索节点
    # 这里不再走 fallback，而是显式进入“检索 -> 生成”链路
    if intent == "rag":
        return "rag_retrieve"

    # 其他未知意图统一走兜底节点
    return "fallback"


def route_slot(state: AgentState) -> str:
    """
    槽位路由函数。

    作用：
    - 判断当前是否已经收集齐运价查询所需参数
    - 如果槽位完整，则进入工具调用节点
    - 如果槽位不完整，则进入追问节点

    依赖字段：
    - state["query_ready"]
    """
    # 如果查询条件已经齐备，进入 tool 节点调用报价工具
    if state.get("query_ready"):
        return "tool"

    # 否则进入 ask 节点，让模型继续追问缺失字段
    return "ask"


def route_tool(state: AgentState) -> str:
    """
    工具结果路由函数。

    作用：
    - 判断工具调用后是否出错
    - 如果出错，则直接结束
    - 如果成功，则进入结果语义化节点

    依赖字段：
    - state["api_error"]
    """
    # 如果工具调用失败，并且已经写入 api_error，
    # 说明 tool_node 内部已经把错误提示消息写回 messages，
    # 因此这里直接结束整条流程即可
    if state.get("api_error"):
        return END

    # 否则进入 result 节点，把结构化结果转成自然语言答复
    return "result"


def build_agent():
    """
    构建并编译 LangGraph Agent。

    整体职责：
    1. 创建状态图
    2. 注册所有节点
    3. 设置入口节点
    4. 配置条件路由
    5. 配置固定边
    6. 编译为可执行的 graph 对象
    """
    # 创建一个基于 AgentState 的状态图
    # AgentState 定义了整条链路中允许流转的状态字段
    graph = StateGraph(AgentState)

    # 注册节点：
    # 每个节点本质上都是一个“读 state -> 处理 -> 返回新 state”的函数
    graph.add_node("intent", intent_node)
    graph.add_node("slot", slot_node)
    graph.add_node("ask", ask_node)
    graph.add_node("tool", tool_node)
    graph.add_node("result", result_node)
    graph.add_node("fallback", fallback_node)
    graph.add_node("rag_retrieve", rag_retrieve_node)
    graph.add_node("rag_answer", rag_answer_node)
    graph.add_node("result_analysis", result_analysis_node)
    graph.add_node("result_reference", result_reference_node)
    graph.add_node("support_info", support_info_node)

    # 设置图的入口节点：
    # 所有请求都从 intent 节点开始，先做意图识别
    graph.set_entry_point("intent")

    # 配置 intent 节点的条件边：
    # intent_node 执行完成后，不是固定走向某一节点，
    # 而是调用 route_intent(state) 决定下一跳
    graph.add_conditional_edges("intent", route_intent, {
        "slot": "slot",
        "result_analysis": "result_analysis",
        "result_reference": "result_reference",
        "support_info": "support_info",
        "rag_retrieve": "rag_retrieve",
        "fallback": "fallback",
    })

    # 配置 slot 节点的条件边：
    # 槽位齐全 -> tool
    # 槽位不齐 -> ask
    graph.add_conditional_edges("slot", route_slot, {
        "tool": "tool",
        "ask": "ask",
    })

    # 配置 tool 节点的条件边：
    # 工具失败 -> END
    # 工具成功 -> result
    graph.add_conditional_edges("tool", route_tool, {
        "result": "result",
        END: END,
    })

    # 固定边配置：
    # ask 节点执行完后直接结束，
    # 因为这一轮的目标只是追问用户，不会继续往下查报价
    graph.add_edge("ask", END)

    # result 节点执行完后结束，
    # 因为结果已经生成完成
    graph.add_edge("result", END)

    # fallback 节点执行完后结束，
    # 因为兜底回复已经给出
    graph.add_edge("fallback", END)

    # 结果分析链输出完结果后直接结束
    graph.add_edge("result_analysis", END)
    graph.add_edge("result_reference", END)
    graph.add_edge("support_info", END)

    # RAG 链路是固定两步：
    # 先检索，再生成答案
    graph.add_edge("rag_retrieve", "rag_answer")

    # RAG 生成完答案后结束
    graph.add_edge("rag_answer", END)

    # 编译状态图，返回可执行 Agent
    return graph.compile()


# 在模块加载时直接构建 Agent，
# 供外部通过 agent.invoke(...) 调用
agent = build_agent()
