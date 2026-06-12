from rag.generator import generate_answer
from rag.query_analyzer import analyze_query
from rag.retriever import hybrid_retrieve


def run_rag_pipeline(question: str) -> dict:
    """
    执行一次完整的 RAG 主流程，并返回过程信息和最终答案。

    整体流程：
    1. 先分析用户问题，得到更适合检索的 query，以及可选的 filters
    2. 用分析后的 query + filters 去做混合检索
    3. 把检索到的文档交给 generator 生成最终回答
    4. 返回这次流程中的关键中间结果，便于调试、排查和扩展

    参数：
        question: 用户原始问题

    返回：
        一个 dict，包含：
        - retrieval_query: 实际用于检索的 query
        - retrieval_filters: 实际用于检索的过滤条件
        - retrieved_docs: 检索到的文档列表
        - rag_answer: 最终生成的回答
    """

    # 第一步：分析用户问题
    # 这里通常会做 query rewrite、意图识别、metadata filter 推断等
    # 比如把“v3 的登录超时怎么配”改写成更适合检索的 query，
    # 同时提取出版本、产品线、文档类型等过滤条件
    analysis = analyze_query(question)

    # 第二步：做检索
    # 优先使用 analyze_query 产出的 query 和 filters；
    # 如果分析结果里没有 query，就退回用户原始问题
    docs = hybrid_retrieve(
        query=analysis.get("query", question),
        filters=analysis.get("filters"),
    )

    # 第三步：做生成
    # 注意这里传给 generator 的 question 仍然是“用户原始问题”，
    # 而不是改写后的 retrieval_query。
    # 这是合理的，因为检索 query 可以为召回效果服务，
    # 但最终回答最好还是围绕用户原本的提问方式来生成。
    answer = generate_answer(question=question, retrieved_docs=docs)

    # 返回完整结果，而不是只返回 answer
    # 这样做有两个好处：
    # 1. 便于调试：可以看到检索到底用了什么 query / filters
    # 2. 便于扩展：以后前端如果要展示引用文档、检索条件、调试信息，就不用改主流程
    return {
        "retrieval_query": analysis.get("query", question),
        "retrieval_filters": analysis.get("filters"),
        "retrieved_docs": docs,
        "rag_answer": answer,
    }


def query_knowledge_base(question: str) -> str:
    """
    对外提供一个更简单的知识库查询接口。

    和 run_rag_pipeline 的区别：
    - run_rag_pipeline 返回完整的中间结果 + 最终答案，适合调试、排查、扩展
    - query_knowledge_base 只返回最终答案，适合给上层业务直接调用

    参数：
        question: 用户问题

    返回：
        最终的 RAG 回答文本
    """
    return run_rag_pipeline(question)["rag_answer"]