"""
retrieval/reranker.py —— 检索结果精排层（召回→融合 之后的第三阶段）

职责：在 retriever 出来的候选 chunk(list[dict]) 与 rerank_client(只认 list[str])
之间做映射缝合。rerank_client 返回的 index 是「输入 documents 的下标」，用它把
LLM 打的分映射回原始 chunk dict，保证上层始终拿到带 doc_id/chunk_id/text 的完整结果。

与 retriever 解耦：retriever 只管召回+融合，本层是独立可选的后处理，
上层(chat 接口)按需决定要不要过这道闸门。
"""
from __future__ import annotations
from loguru import logger

from backend.core import rerank_client


async def rerank_chunks(
    query: str,
    candidates: list[dict],
    top_n: int = 5,
    score_threshold: float = 0.08,
    rerank_mode: str = "fusion",
) -> list[dict]:
    """
    query:           查询原文
    candidates:      retriever 返回的候选(每项含 text / doc_id / chunk_id / ...)
    top_n:           精排后保留条数
    score_threshold: 低于此分的候选直接丢弃(默认 0.1，滤掉判为基本无关的)
    rerank_mode:     "fusion" (本地) | "llm" (大模型打分)
    返回:            按 rerank score 降序的 list[dict]，在原 chunk dict 上加 "rerank_score"
                     字段；rrf_score/ranks/scores 等原字段保留，便于全链路追溯。
    """
    if not candidates:
        return []

    # 1. 拆出纯文本喂给 rerank_client，下标与 candidates 一一对应
    docs = [c["text"] for c in candidates]

    # 2. 精排，返回 [{index, score, document}, ...]
    ranked = await rerank_client.rerank(
        query, docs, top_n=top_n, score_threshold=score_threshold, mode=rerank_mode
    )

    # 3. 用 index 把分数缝回原始 chunk dict（关键：index 是 candidates 的下标）
    out: list[dict] = []
    for r in ranked:
        chunk = dict(candidates[r["index"]])   # 拷贝，不改原对象
        chunk["rerank_score"] = r["score"]
        out.append(chunk)

    logger.info(
        "rerank: 候选 {} 条 → 精排保留 {} 条 (threshold={})",
        len(candidates), len(out), score_threshold,
    )
    return out
