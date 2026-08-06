"""
retrieval/retriever.py —— 统一检索入口，支持 dense / sparse / hybrid 三模式

设计：召回与融合解耦。
  - dense  : query → embedding → Milvus dense ANN
  - sparse : query 原文 → Milvus BM25
  - hybrid : 两路并发召回 → 可插拔融合器(默认应用层 rrf_merge) → 截 top_k

融合被抽成独立一步(_fuse)，日后换加权融合 / 库内 RRFRanker / 加第三路召回，
只动融合环节，retrieve 主干不变。
"""
from __future__ import annotations
import asyncio
from loguru import logger

from backend.store import milvus_store
from backend.retrieval.rrf import rrf_merge


async def _dense_recall(query: str, kb_id: int | None,
                        kb_ids: list[int] | None, recall_k: int) -> list[dict]:
    from backend.core import embedding_client
    qv = await embedding_client.embed_one(query)
    # Milvus 调用是同步的，丢线程池避免阻塞事件循环
    return await asyncio.to_thread(milvus_store.search, qv,
                                   kb_id=kb_id, kb_ids=kb_ids, top_k=recall_k)


async def _sparse_recall(query: str, kb_id: int | None,
                         kb_ids: list[int] | None, recall_k: int) -> list[dict]:
    return await asyncio.to_thread(milvus_store.search_sparse, query,
                                   kb_id=kb_id, kb_ids=kb_ids, top_k=recall_k)


def _fuse(dense_hits: list[dict], sparse_hits: list[dict], top_k: int) -> list[dict]:
    """可插拔融合环节。当前：应用层 RRF。
    未来要换库内 RRFRanker / 加权融合 / 加第三路，只改这里。"""
    return rrf_merge(
        {"dense": dense_hits, "sparse": sparse_hits},
        k=60,
        id_key="chunk_id",
        top_k=top_k,
    )


def diversify_chunks(chunks: list[dict], max_per_doc: int = 2, top_k: int = 30) -> list[dict]:
    """确保结果来自多个不同文档：每篇最多取 max_per_doc 条，补足到 top_k 条。
    防止少数文档垄断检索结果。"""
    from loguru import logger
    seen_docs: dict[int, int] = {}
    diverse: list[dict] = []
    rest: list[dict] = []
    for c in chunks:
        did = c.get("doc_id")
        if did is None:
            diverse.append(c)
        elif seen_docs.get(did, 0) < max_per_doc:
            seen_docs[did] = seen_docs.get(did, 0) + 1
            diverse.append(c)
        else:
            rest.append(c)
    if len(diverse) < top_k:
        # 第二轮：从 rest 中补位，仍然遵守 max_per_doc（第二轮翻倍限制允许更多但不会无限）
        round2_limit = max_per_doc * 2
        for c in rest:
            if len(diverse) >= top_k:
                break
            did = c.get("doc_id")
            if did is not None and seen_docs.get(did, 0) >= round2_limit:
                continue
            if did is not None:
                seen_docs[did] = seen_docs.get(did, 0) + 1
            diverse.append(c)
    logger.info("多样性过滤: {} 条来自 {} 个文档 → {} 条 (max_per_doc={}, round2_limit={})",
                len(chunks), len(seen_docs), min(len(diverse), top_k), max_per_doc, round2_limit)
    return diverse[:top_k]


async def retrieve(
    query: str,
    mode: str = "hybrid",
    kb_id: int | None = None,
    kb_ids: list[int] | None = None,
    top_k: int = 5,
    recall_k: int = 20,
) -> list[dict]:
    """
    query   : 用户查询原文
    mode    : "dense" | "sparse" | "hybrid"
    kb_id   : 单库隔离（向后兼容）；与 kb_ids 同时存在时 kb_ids 优先
    kb_ids  : 多库隔离；None 表示不过滤，[] 表示无可检索库
    top_k   : 最终返回条数
    recall_k: hybrid 模式下每路召回条数(召回比 top_k 深，避免单路靠后但另一路靠前的被漏)
    返回    : list[dict]，dense/sparse 模式含 score；hybrid 模式含 rrf_score/ranks/scores
    """
    # 空列表 = 无可检索库，直接返回
    if kb_ids is not None and len(kb_ids) == 0:
        logger.info("retrieve[{}] kb_ids=[] → 空结果", mode)
        return []

    if mode == "dense":
        hits = await _dense_recall(query, kb_id, kb_ids, top_k)
        logger.info("retrieve[dense] kb_ids={} kb_id={} 返回 {} 条",
                    kb_ids, kb_id, len(hits))
        return hits

    if mode == "sparse":
        hits = await _sparse_recall(query, kb_id, kb_ids, top_k)
        logger.info("retrieve[sparse] kb_ids={} kb_id={} 返回 {} 条",
                    kb_ids, kb_id, len(hits))
        return hits

    if mode == "hybrid":
        dense_hits, sparse_hits = await asyncio.gather(
            _dense_recall(query, kb_id, kb_ids, recall_k),
            _sparse_recall(query, kb_id, kb_ids, recall_k),
        )
        fused = _fuse(dense_hits, sparse_hits, top_k)
        logger.info(
            "retrieve[hybrid] kb_ids={} kb_id={} dense={} sparse={} → 融合 {} 条",
            kb_ids, kb_id, len(dense_hits), len(sparse_hits), len(fused),
        )
        return fused

    raise ValueError(f"未知 mode: {mode!r}，应为 dense/sparse/hybrid")
