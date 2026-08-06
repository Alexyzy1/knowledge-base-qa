"""Unified Retrieval —— 统一检索入口。

消除标准管线 (_retrieve_and_rerank) 和 Agent 管线 (searcher_node)
中的重复检索逻辑，提供单一入口给两条管线复用。

流程：
  1. 文件名匹配（所有 queries 的并集）
  2. 多 query 并发检索（定向 + 全局 + [HyDE 通道]）
  3. 多 query 结果合并去重
  4. Diversify → Rerank → Filename Boost
  5. Build Context（分配引用编号）
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from loguru import logger

from backend.retrieval.retriever import diversify_chunks
from backend.retrieval.reranker import rerank_chunks
from backend.retrieval.rrf import rrf_merge
from backend.store import mysql_store as db


@dataclass
class RetrievalRequest:
    queries: list[str]                             # 子查询列表
    kb_ids: list[int]                              # 目标知识库
    rerank_mode: str = "fusion"                    # fusion | llm
    do_rerank: bool = True
    do_filename_match: bool = True
    dense_weight: float = 0.5
    sparse_weight: float = 0.5
    hyde_embedding: list[float] | None = None      # HyDE 向量，非 None 时增加 dense_hyde 通道
    top_k: int = 30
    recall_k: int = 100
    max_per_doc: int = 2
    rerank_top_n: int = 15


@dataclass
class RetrievalResult:
    chunks: list[dict] = field(default_factory=list)
    context: str = ""
    sources: list[dict] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


async def _retrieve_single_query(
    query: str,
    kb_ids: list[int],
    matched_doc_ids: list[int],
    recall_k: int,
    dense_weight: float,
    sparse_weight: float,
    hyde_embedding: list[float] | None,
) -> list[dict]:
    """对单个 query 执行完整的定向+全局检索，返回 chunk 列表。"""
    from backend.store import milvus_store
    from backend.core import embedding_client

    chunks: list[dict] = []

    # ── Stage A: 定向检索 ──
    if matched_doc_ids:
        # 限制定向检索的文档数
        target_docs = matched_doc_ids[:20]
        qv = await embedding_client.embed_one(query)

        async def _dense_scoped():
            return await asyncio.to_thread(
                milvus_store.search, qv, kb_ids=kb_ids, top_k=40, doc_ids=target_docs)

        async def _sparse_scoped():
            return await asyncio.to_thread(
                milvus_store.search_sparse, query, kb_ids=kb_ids, top_k=40, doc_ids=target_docs)

        scoped_d, scoped_s = await asyncio.gather(_dense_scoped(), _sparse_scoped())
        scoped = rrf_merge(
            {"dense": scoped_d, "sparse": scoped_s},
            k=60, id_key="chunk_id", top_k=30,
            weights={"dense": dense_weight, "sparse": sparse_weight},
        )
        chunks.extend(scoped)

    # ── Stage B: 全局检索 ──
    channels: dict[str, list[dict]] = {}

    # dense_original
    qv = await embedding_client.embed_one(query)
    channels["dense_original"] = await asyncio.to_thread(
        milvus_store.search, qv, kb_ids=kb_ids, top_k=recall_k)

    # dense_hyde（如果有）
    if hyde_embedding is not None:
        channels["dense_hyde"] = await asyncio.to_thread(
            milvus_store.search, hyde_embedding, kb_ids=kb_ids, top_k=recall_k)

    # sparse
    channels["sparse"] = await asyncio.to_thread(
        milvus_store.search_sparse, query, kb_ids=kb_ids, top_k=recall_k)

    # 加权 RRF 融合
    global_weights = {
        "dense_original": dense_weight,
        "dense_hyde": dense_weight * 0.5 if "dense_hyde" in channels else 0.0,
        "sparse": sparse_weight,
    }
    global_merged = rrf_merge(channels, k=60, id_key="chunk_id", top_k=30,
                               weights=global_weights)

    # ── Stage C: 合并（定向优先） ──
    seen: set = set()
    result: list[dict] = []
    for c in chunks:
        cid = c.get("chunk_id")
        if cid is not None and cid not in seen:
            seen.add(cid)
            result.append(c)
    for c in global_merged:
        cid = c.get("chunk_id")
        if cid is not None and cid not in seen:
            seen.add(cid)
            result.append(c)

    return result


async def unified_retrieve(req: RetrievalRequest) -> RetrievalResult:
    """统一检索入口。"""
    # 空库直接返回
    if not req.kb_ids:
        return RetrievalResult(context="（未找到相关上下文）", stats={"kb_empty": True})

    stats: dict = {"total_queries": len(req.queries)}

    # ── 1. 文件名匹配 ──
    matched_doc_ids: list[int] = []
    if req.do_filename_match:
        all_matched: set[int] = set()
        for q in req.queries:
            ids = db.search_documents_by_filename(req.kb_ids, q)
            all_matched.update(ids)
        matched_doc_ids = list(all_matched)
        logger.info("[UnifiedRetrieve] 文件名匹配: {} 个文档, matched={}",
                    len(matched_doc_ids), matched_doc_ids[:10])

    stats["filename_matches"] = len(matched_doc_ids)
    stats["hyde_enabled"] = req.hyde_embedding is not None

    # ── 2. 多 query 并发检索 ──
    results_per_query: list[list[dict]] = []
    try:
        results_per_query = await asyncio.gather(
            *[_retrieve_single_query(
                q, req.kb_ids, matched_doc_ids, req.recall_k,
                req.dense_weight, req.sparse_weight, req.hyde_embedding,
            ) for q in req.queries],
            return_exceptions=True,
        )
    except Exception as exc:
        logger.warning("[UnifiedRetrieve] 检索异常: {}", exc)

    # ── 3. 合并去重 ──
    seen_ids: set[int] = set()
    all_chunks: list[dict] = []
    for i, r in enumerate(results_per_query):
        if isinstance(r, Exception):
            logger.warning("[UnifiedRetrieve] query[{}] 检索失败: {}", i, r)
            continue
        for c in r:
            cid = c.get("chunk_id")
            if cid is not None and cid not in seen_ids:
                seen_ids.add(cid)
                all_chunks.append(c)

    logger.info("[UnifiedRetrieve] {} 个 query → {} 条 chunks（去重后）",
                len(req.queries), len(all_chunks))
    stats["merged_count"] = len(all_chunks)

    if not all_chunks:
        return RetrievalResult(context="（未找到相关上下文）", stats=stats)

    # ── 4. Diversify ──
    diverse = diversify_chunks(all_chunks, max_per_doc=req.max_per_doc, top_k=req.top_k)

    # ── 5. Rerank ──
    if req.do_rerank:
        # 阈值区分模式：fusion 用相对分（softmax 拉伸），llm 用绝对分（0~1 锚点）
        thr = 0.08 if req.rerank_mode == "fusion" else 0.15
        ranked = await rerank_chunks(
            req.queries[0], diverse, top_n=req.rerank_top_n,
            score_threshold=thr, rerank_mode=req.rerank_mode,
        )
    else:
        ranked = diverse[:req.rerank_top_n]

    # ── 6. Filename Boost ──
    if matched_doc_ids:
        BOOST = 0.15
        boosted_count = 0
        for c in ranked:
            if c.get("doc_id") in matched_doc_ids:
                c["rerank_score_raw"] = c.get("rerank_score", 0)
                c["rerank_score"] = min(c.get("rerank_score", 0) + BOOST, 1.0)
                boosted_count += 1
        if boosted_count > 0:
            ranked.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        stats["boosted"] = boosted_count

    # ── 7. Build Context ──
    seen_docs: dict[int, int] = {}
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

        text = c["text"]
        # 去掉 chunk 文本中的 [filename] 前缀
        if fname:
            prefix = f"[{fname}]\n"
            if text.startswith(prefix):
                text = text[len(prefix):]
            prefix2 = f"[{fname}]"
            if text.startswith(prefix2):
                text = text[len(prefix2):]

        score_tag = f" [相关度: {c.get('rerank_score', 0):.2f}]" if c.get('rerank_score', 0) > 0 else ""
        parts.append(f"[{label}]{score_tag} (来源文件：{fname})\n{text}")

    context = "\n\n".join(parts)

    # ── 构建 sources ──
    sources: list[dict] = []
    seen_src: set[int] = set()
    for c in ranked:
        did = c.get("doc_id")
        if did is not None and did not in seen_src:
            seen_src.add(did)
            doc = db.get_document(did)
            sources.append({"doc_id": did, "filename": (doc or {}).get("filename") or str(did)})

    logger.info("[UnifiedRetrieve] 最终 {} chunks, {} sources, {} 字",
                len(ranked), len(sources), len(context))
    stats["final_count"] = len(ranked)
    stats["source_count"] = len(sources)

    return RetrievalResult(chunks=ranked, context=context, sources=sources, stats=stats)
