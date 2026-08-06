"""
retrieval/rrf.py —— Reciprocal Rank Fusion (RRF) 多路检索结果融合

为什么用 RRF：dense（cosine，越大越近）与 sparse/BM25（分数无上界）的原始分
尺度完全不可比，直接加权相加没有意义。RRF 只看每路里的「排名」，不看原始分，
天然规避尺度问题。

公式：rrf_score(doc) = Σ_i  1 / (k + rank_i(doc))
  - rank 从 1 开始（每路排第 1 名贡献 1/(k+1)，最大）
  - k 默认 60（Cormack 2009 经验值；k 越大，各路名次差异被压得越平）
  - 某 doc 只出现在部分路里时，只累加它出现过的那几路

输入输出都带 payload（text 等），融合完直接可用，retriever 不必二次回库。
"""
from __future__ import annotations


def rrf_merge(
    channels: dict[str, list[dict]],
    k: int = 60,
    id_key: str = "chunk_id",
    top_k: int | None = None,
    weights: dict[str, float] | None = None,
) -> list[dict]:
    """
    channels: {路名: [结果dict, ...]}，每路按相关度降序（最相关在前）。
              例 {"dense": [...], "sparse": [...]}。
              每个结果 dict 至少含 id_key；通常还含 text / score / doc_id。
    weights:  每路权重，默认全部 1.0（与旧版行为完全一致）。
              公式：rrf_score(doc) = Σ_i  w_i / (k + rank_i(doc))
    返回:     融合后按 rrf_score 降序的 list[dict]，每条形如
              {
                <原 payload 字段，如 chunk_id/doc_id/text>,
                "rrf_score": float,
                "ranks":  {"dense": 1, "sparse": 3},        # 各路名次(1-based)，缺路不列
                "scores": {"dense": 0.87, "sparse": 12.3},  # 各路原始分，纯调试用
              }
    """
    merged: dict = {}

    for channel_name, results in channels.items():
        w = (weights or {}).get(channel_name, 1.0)
        for rank, item in enumerate(results, start=1):
            cid = item[id_key]

            if cid not in merged:
                # 首次见到这个 chunk：拷一份 payload（剔掉单路 score），起底融合字段
                payload = {kk: vv for kk, vv in item.items() if kk != "score"}
                payload["rrf_score"] = 0.0
                payload["ranks"] = {}
                payload["scores"] = {}
                merged[cid] = payload

            entry = merged[cid]
            entry["rrf_score"] += w / (k + rank)
            entry["ranks"][channel_name] = rank
            entry["scores"][channel_name] = item.get("score")

    fused = sorted(merged.values(), key=lambda x: x["rrf_score"], reverse=True)
    if top_k is not None:
        fused = fused[:top_k]
    return fused
