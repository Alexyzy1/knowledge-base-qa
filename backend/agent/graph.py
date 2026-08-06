"""Agentic RAG — LangGraph StateGraph。

图结构：
    START → Planner ──(有搜索词)──→ Searcher → Generator ──(非simple)──→ Verifier ──(fail+未超max_iterations)──→ Searcher
                  └──(无搜索词)──→ Generator                                    └──(pass/超限)──→ END
                                                                           └──(simple)──→ END

4 个节点：
  - Planner  : ChatDeepSeek 分析问题，产出搜索关键词列表 + 复杂度判断
  - Searcher : 调用 unified_retrieve 统一检索入口
  - Generator: 基于上下文生成回答
  - Verifier : 检查回答忠实度，不通过则带着建议关键词回 Searcher

C4 自适应：复杂度 simple 跳过 Verifier，medium 最多 2 次重试，complex 最多 4 次。
"""
from __future__ import annotations

from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.config import get_stream_writer
from langchain_deepseek import ChatDeepSeek
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from pydantic import BaseModel, Field
from loguru import logger

from backend import config
from backend.agent.state import AgentState


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic 输出约束
# ═══════════════════════════════════════════════════════════════════════════════

class PlannerOutput(BaseModel):
    """Planner 的结构化输出。"""
    queries: list[str] = Field(
        default_factory=list,
        description="搜索关键词列表；如果问题无需检索（如打招呼、询问能力），返回空列表"
    )
    reasoning: str = Field(
        default="",
        description="分析推理过程，解释为什么选择这些关键词（或为什么不需要检索）"
    )
    complexity: str = Field(
        default="medium",
        description="问题复杂度：simple(单一概念)/medium(需综合)/complex(多步推理)"
    )


class VerifierOutput(BaseModel):
    """Verifier 的结构化输出。"""
    passed: bool = Field(
        description="回答是否通过质检：忠实于上下文、无编造、回答了用户的全部问题"
    )
    issues: list[str] = Field(
        default_factory=list,
        description="发现的问题列表（未通过时填写，通过时为空）"
    )
    suggested_queries: list[str] = Field(
        default_factory=list,
        description="未通过时建议的补充搜索关键词（最多 3 个）"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ChatDeepSeek 惰性工厂（避免 import 时就要求 api_key）
# ═══════════════════════════════════════════════════════════════════════════════

def _make_llm(temperature: float = 0.3, max_tokens: int = 2048) -> ChatDeepSeek:
    """惰性创建 ChatDeepSeek 实例。只在节点被调用时才初始化，
    使得语法检查/冒烟测试/图编译不需要 api_key。"""
    return ChatDeepSeek(
        model=config.LLM_MODEL,
        api_key=config.MODEL_API_KEY,
        api_base=config.MODEL_API_BASE,
        temperature=temperature,
        max_tokens=max_tokens,
    )

# ═══════════════════════════════════════════════════════════════════════════════
# Prompt 模板
# ═══════════════════════════════════════════════════════════════════════════════

PLANNER_SYSTEM = """你是一个知识库问答系统的查询规划器。根据用户问题，决定需要搜索哪些关键词才能找到相关信息。

规则：
1. 如果用户只是打招呼（"你好"、"hi"等）或询问你的能力（"你能做什么"），返回空的 queries 列表
2. 如果用户的问题与知识相关，拆解出 1-3 个搜索关键词（短词组，不要长句）
3. 关键词应覆盖问题的不同方面或可能的表述方式
4. reasoning 用一句话说明你的决策思路
5. 判断问题复杂度：
   - simple：单一概念解释、定义、简单事实（如"SVD是什么"、"lec8的内容"）
   - medium：需要综合多个知识点或段落（如"SVD在推荐系统中的应用"）
   - complex：需要对比分析、多步推理、跨文档关联（如"SVD和PCA在降维上的区别和适用场景"）"""


GENERATOR_SYSTEM = """你是一个知识库问答助手。严格依据提供的【上下文】回答用户问题。

规则：
1. 每段上下文前有形如 [N] 的来源编号，回答时在引用处标注对应角标
2. 即使上下文没有直接、完整的答案，也请说明上下文中最接近相关的内容是什么，并标注来源。不要只回一句"未找到"。
3. 回答简洁、直接，不要添加上下文之外的编造。
4. 只有在上下文中确实没有任何相关内容时，才可以说"知识库中未找到相关内容"。

提示：OCR 提取的代码片段、公式、图片描述也可能是学习资料的一部分，请结合查询语义判断，不要因为格式碎片而忽视。"""


VERIFIER_SYSTEM = """你是一个问答质检器。检查给定的回答是否忠实于上下文，是否完整回答了用户问题。

判断标准：
- pass:
  - 回答忠实于上下文，无编造，至少部分回答了问题
  - 或者回答正确说明了上下文中未找到直接信息，并给出了最相关的内容
- fail:
  - 回答有编造、与上下文明显矛盾
  - 或者遗漏了上下文中已有的关键信息，在已有信息足够的情况下说"未找到"

如果 fail，给出具体问题（至少 1 条）和建议的补充搜索关键词（最多 3 个）。
如果 pass，issues 和 suggested_queries 均返回空列表。"""


# ═══════════════════════════════════════════════════════════════════════════════
# 图节点
# ═══════════════════════════════════════════════════════════════════════════════

async def planner_node(state: AgentState) -> dict:
    """Planner 节点：分析用户问题，产出搜索关键词。"""
    query = state["query"]
    history = state.get("history") or []
    kb_ids = state.get("kb_ids") or []

    logger.info("[Planner] 开始分析 query={!r} kb_ids={}", query[:80], kb_ids)

    # 构造消息（含可用知识库信息）
    kb_info = ""
    if kb_ids:
        from backend.store import mysql_store as db
        names = []
        for kid in kb_ids:
            basic = db.get_kb_basic(kid)
            names.append(basic["name"] if basic else f"KB#{kid}")
        kb_info = f"当前可用知识库：{', '.join(names)}。"
    else:
        kb_info = "当前无可用知识库。"

    user_msg = f"{kb_info}\n\n用户问题：{query}"

    # 追加最近对话历史上下文
    if history:
        recent = history[-4:]  # 最近 2 轮
        hist_text = "\n".join(
            f"{'用户' if m['role'] == 'user' else '助手'}：{m['content'][:200]}"
            for m in recent
        )
        user_msg = f"对话历史：\n{hist_text}\n\n{user_msg}"

    # 结构化 LLM 调用
    llm_with_schema = _make_llm(temperature=0.3, max_tokens=2048).with_structured_output(PlannerOutput, method="function_calling")
    result: PlannerOutput = await llm_with_schema.ainvoke([
        SystemMessage(content=PLANNER_SYSTEM),
        HumanMessage(content=user_msg),
    ])

    logger.info("[Planner] action={} queries={} reasoning={!r}",
                "search" if result.queries else "answer",
                result.queries, result.reasoning[:100])

    return {
        "search_queries": result.queries,
        "reasoning": result.reasoning,
        "complexity": result.complexity,
        "max_iterations": {"simple": 0, "medium": 2, "complex": 4}.get(result.complexity, 2),
        "verify_enabled": result.complexity != "simple",
        # 初始化后续字段
        "chunks": [],
        "context": "",
        "answer": "",
        "passed": False,
        "issues": [],
        "iteration": 0,
    }


async def searcher_node(state: AgentState) -> dict:
    """Searcher 节点：对 search_queries 并发检索，合并去重。复用统一检索入口。"""
    queries = state.get("search_queries") or []
    kb_ids = state.get("kb_ids") or []
    iteration = state.get("iteration", 0)

    if not queries:
        logger.info("[Searcher] 无搜索词，跳过")
        return {"chunks": [], "context": ""}

    logger.info("[Searcher] iteration={} queries={} kb_ids={}", iteration, queries, kb_ids)

    # 读取 rerank_mode（取第一个知识库的配置）
    rerank_mode = "fusion"
    if kb_ids:
        from backend.store import mysql_store as _db2
        _cfg = _db2.get_kb_config(kb_ids[0])
        if _cfg:
            _m = _cfg.get("rerank_mode")
            if _m in ("fusion", "llm"):
                rerank_mode = _m

    from backend.retrieval.unified_retrieval import unified_retrieve, RetrievalRequest

    result = await unified_retrieve(RetrievalRequest(
        queries=queries,
        kb_ids=kb_ids,
        rerank_mode=rerank_mode,
        do_rerank=True,
        do_filename_match=True,
        top_k=30,
        recall_k=150,
        max_per_doc=2,
        rerank_top_n=15,
    ))

    return {"chunks": result.chunks, "context": result.context}


async def generator_node(state: AgentState) -> dict:
    """Generator 节点：基于上下文（可能为空）生成回答。"""
    query = state["query"]
    context = state.get("context") or ""
    search_queries = state.get("search_queries") or []
    history = state.get("history") or []

    has_context = bool(context.strip() and "未找到相关上下文" not in context)
    logger.info("[Generator] has_context={} query={!r}", has_context, query[:80])

    if has_context:
        user_msg = f"【上下文】\n{context}\n\n【用户问题】\n{query}"
    else:
        # 无上下文：直接回答，但不能编造知识
        user_msg = (
            f"【用户问题】\n{query}\n\n"
            f"注意：知识库中未找到与该问题相关的文档。"
            f"请说明未找到相关信息，不要编造答案。"
            f"如果是打招呼或一般性问题，可以正常回复。"
        )

    messages = [SystemMessage(content=GENERATOR_SYSTEM)]
    # 注入对话历史（最近 6 轮），保持多轮记忆
    if history:
        recent = history[-12:]  # 最多 6 对对话
        for m in recent:
            if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip():
                messages.append(HumanMessage(content=m["content"]) if m["role"] == "user"
                                 else AIMessage(content=m["content"]))
    messages.append(HumanMessage(content=user_msg))

    llm_creative = _make_llm(temperature=0.7, max_tokens=config.LLM_ANSWER_MAX_TOKENS)
    resp = await llm_creative.ainvoke(messages)

    answer = (resp.content or "").strip()
    logger.info("[Generator] 产出 {} 字", len(answer))

    # stream writer（用于 SSE 推送中间结果）
    try:
        writer = get_stream_writer()
        writer({"node": "generator", "answer": answer})
    except RuntimeError:
        pass  # 不在 streaming 上下文中

    return {"answer": answer}


async def verifier_node(state: AgentState) -> dict:
    """Verifier 节点：检查回答质量，决定是否补充检索。"""
    query = state["query"]
    context = state.get("context") or ""
    answer = state.get("answer") or ""
    iteration = state.get("iteration", 0)

    # 无上下文时直接放行（已经告知用户未找到）
    if not context.strip() or "未找到相关上下文" in context:
        logger.info("[Verifier] 无上下文，直接放行")
        return {"passed": True, "issues": [], "iteration": iteration}

    # ── 前置检查：省掉不必要的 LLM Verifier 调用 ──
    # 1) Generator 已明确告知"未找到"，直接放行
    _not_found_markers = ["未找到相关内容", "未找到相关信息", "没有找到相关", "not found"]
    if any(m in answer for m in _not_found_markers):
        logger.info("[Verifier] Generator 返回'未找到'，直接放行，跳过 LLM 质检")
        return {"passed": True, "issues": [], "iteration": iteration + 1, "search_queries": []}

    logger.info("[Verifier] iteration={} answer_len={} context_len={}",
                iteration, len(answer), len(context))

    llm_with_schema = _make_llm(temperature=0.3, max_tokens=2048).with_structured_output(VerifierOutput, method="function_calling")
    result: VerifierOutput = await llm_with_schema.ainvoke([
        SystemMessage(content=VERIFIER_SYSTEM),
        HumanMessage(content=(
            f"【用户问题】\n{query}\n\n"
            f"【上下文】\n{context[:3000]}\n\n"
            f"【生成的回答】\n{answer}"
        )),
    ])

    # 2) LLM 说 fail 但没给出 issues 也没建议检索词 → 当作 pass（省一次无意义重试）
    if not result.passed and not result.issues and not result.suggested_queries:
        logger.info("[Verifier] LLM 返回 passed=false 但 issues/suggested 均为空，修正为 passed=true")
        result.passed = True

    logger.info("[Verifier] passed={} issues={} suggested_queries={}",
                result.passed, result.issues, result.suggested_queries)

    return {
        "passed": result.passed,
        "issues": result.issues,
        # suggested_queries 用于补充检索（写回 search_queries）
        "search_queries": result.suggested_queries,
        "iteration": iteration + 1,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 条件路由
# ═══════════════════════════════════════════════════════════════════════════════

def route_after_planner(state: AgentState) -> Literal["searcher", "generator"]:
    """Planner 之后：有搜索词→Searcher，无搜索词→Generator。"""
    queries = state.get("search_queries") or []
    if queries:
        return "searcher"
    return "generator"


def route_after_generator(state: AgentState) -> Literal["verifier", END]:
    """根据 complexity 决定是否走 Verifier。simple 直接 END。"""
    if state.get("complexity", "medium") == "simple":
        logger.info("[Route] simple 复杂度，跳过 Verifier")
        return END
    if not state.get("verify_enabled", True):
        return END
    return "verifier"


def route_after_verifier(state: AgentState) -> Literal["searcher", END]:
    """Verifier 之后：pass→END，fail+iteration<max_iterations→Searcher 重试。"""
    passed = state.get("passed", False)
    iteration = state.get("iteration", 0)
    suggested = state.get("search_queries") or []
    max_iter = state.get("max_iterations", 2)

    if passed or iteration >= max_iter or not suggested:
        if not passed:
            logger.info("[Route] Verifier fail 但已达上限 iteration={}/{}, 强制放行", iteration, max_iter)
        return END
    logger.info("[Route] Verifier fail, 回到 Searcher iteration={}/{}", iteration, max_iter)
    return "searcher"


# ═══════════════════════════════════════════════════════════════════════════════
# 构建图
# ═══════════════════════════════════════════════════════════════════════════════

_builder = StateGraph(AgentState)

_builder.add_node("planner", planner_node)
_builder.add_node("searcher", searcher_node)
_builder.add_node("generator", generator_node)
_builder.add_node("verifier", verifier_node)

_builder.set_entry_point("planner")
_builder.add_conditional_edges("planner", route_after_planner, {
    "searcher": "searcher",
    "generator": "generator",
})
_builder.add_edge("searcher", "generator")
_builder.add_conditional_edges("generator", route_after_generator, {
    "verifier": "verifier",
    END: END,
})
_builder.add_conditional_edges("verifier", route_after_verifier, {
    "searcher": "searcher",
    END: END,
})


def compile_graph(checkpointer=None):
    """编译图。可选传入 SqliteSaver 做 checkpoint 持久化。

    不含 checkpointer：每次执行独立，无历史。
    含 checkpointer：每次执行自动存档，支持 Time Travel 回溯。
    """
    if checkpointer is not None:
        return _builder.compile(checkpointer=checkpointer)
    return _builder.compile()


# 默认无 checkpoint 的图（简单 Agent）
graph = compile_graph()
