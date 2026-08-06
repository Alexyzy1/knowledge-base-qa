"""LangChain Tools — 把现有检索能力封装为标准 Tool 接口。

设计意图：
  - Tool 只是薄封装，真正的检索/精排/改写逻辑仍在 retrieval/ 模块。
  - kb_ids 由调用方（Searcher 节点）从 AgentState 注入，LLM 不接触。
  - Tool 返回格式化好的文本，LLM 直接拼入 prompt 即可。
"""
from __future__ import annotations

from langchain_core.tools import tool
from loguru import logger

from backend.retrieval.retriever import retrieve
from backend.retrieval.reranker import rerank_chunks
from backend.retrieval.query_rewriter import rewrite
from backend.store import mysql_store as db


@tool
async def search_knowledge_base(query: str, kb_ids: list[int]) -> str:
    """在知识库中检索与 query 最相关的文档片段。

    内部走 hybrid 召回 → RRF 融合 → rerank 精排，返回 top-5。
    每条结果前带 [N] 来源编号，供 LLM 引用。

    Args:
        query: 搜索查询字符串（已改写、可直接用于检索）
        kb_ids: 目标知识库 ID 列表

    Returns:
        格式化的上下文字符串，格式为：
        [1] (来源文件：xxx.pdf)
        片段内容...

        [2] (来源文件：yyy.docx)
        片段内容...
    """
    if not kb_ids:
        return "（未指定知识库）"

    # 1) 检索（recall_k=150 宽召回 + RRF 融合 50，确保跨文件覆盖）
    candidates = await retrieve(query, mode="hybrid", kb_ids=kb_ids, top_k=50, recall_k=150)
    if not candidates:
        return f"（在指定知识库中未找到与「{query}」相关的内容）"

    # 2) 多样性 + 精排（每篇 ≤2 chunk，阈值 0.0 只排序不丢弃）
    from backend.retrieval.retriever import diversify_chunks
    diverse = diversify_chunks(candidates, max_per_doc=2, top_k=20)
    ranked = await rerank_chunks(query, diverse, top_n=10, score_threshold=0.0)

    # 3) 格式化为文本（按 doc_id 编号）
    seen_docs: dict[int, int] = {}  # doc_id → 引用编号
    parts: list[str] = []
    cite = 0
    for c in ranked:
        did = c.get("doc_id")
        if did is not None and did not in seen_docs:
            cite += 1
            seen_docs[did] = cite
        label = seen_docs.get(did, "?") if did is not None else "?"
        doc = db.get_document(did) if did is not None else None
        fname = (doc or {}).get("filename") or f"文档#{did}"
        parts.append(f"[{label}] (来源文件：{fname})\n{c['text']}")

    logger.info("search_kb tool: query={!r} kb_ids={} → {} chunks, {} sources",
                query[:60], kb_ids, len(ranked), len(seen_docs))
    return "\n\n".join(parts)


@tool
async def rewrite_query_tool(query: str, history: list[dict] | None = None) -> str:
    """用对话历史改写查询，使其可独立用于知识库检索。

    将多轮对话中的代词/省略补全为具体名词，返回一句完整查询。

    Args:
        query: 用户当前问题原文
        history: 对话历史列表 [{"role":"user/assistant","content":"..."}, ...]

    Returns:
        改写后的完整查询字符串。无历史或改写失败时返回原 query。
    """
    result = await rewrite(query, history)
    if result != query:
        logger.info("rewrite tool: {!r} → {!r}", query[:60], result[:60])
    return result


@tool
def list_knowledge_bases() -> str:
    """列出所有可用的知识库，包含名称、文档数、chunk 数。

    Returns:
        格式化的知识库列表，每行一个。
    """
    kbs = db.list_kb()
    if not kbs:
        return "（当前无可用知识库）"

    lines = ["可用知识库："]
    for kb in kbs:
        kid = kb["id"]
        doc_count = db.count_documents(kid)
        chunk_count = db.count_chunks(kid)
        desc = (kb.get("description") or "").strip()
        line = f"  • [{kid}] {kb['name']}"
        if desc:
            line += f" — {desc[:60]}"
        line += f" （{doc_count} 个文档，{chunk_count} 个片段）"
        lines.append(line)
    return "\n".join(lines)
