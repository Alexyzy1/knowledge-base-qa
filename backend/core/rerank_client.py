# backend/core/rerank_client.py
"""Rerank client — 双模式精排器。

模式（由 kb_config.rerank_mode 控制）：
  fusion (默认) — 本地 embedding cosine + token overlap 融合打分
    · 延迟 ~3ms/chunk，零网络依赖
    · 适合精确术语匹配（文件名查询、编号查询等）

  llm    — DeepSeek-V4 LLM-as-judge 打分
    · 延迟 ~200ms/chunk，需网络请求
    · 语义理解更细腻，适合复杂查询
    · 内置 3 个 few-shot 示例覆盖 0~1 全分档

接口完全兼容，上层 retriever/reranker/chat 无需改动调用方式，
只需传入 mode 参数即可切换。
"""
from __future__ import annotations
import asyncio
import re

import numpy as np
from loguru import logger


# ═══════════════════════════════════════════════════════════════════
# 1. Token overlap — 精确关键词匹配（fusion 模式用）
# ═══════════════════════════════════════════════════════════════════

_TOKEN_RE = re.compile(r"[a-zA-Z\d]+|[一-鿿]+")
# 常用无意义停用词（中文+英文）
_STOP = {"的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
         "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
         "没有", "看", "好", "自己", "这", "the", "a", "an", "is", "are",
         "was", "were", "be", "been", "in", "on", "at", "to", "for", "of",
         "and", "or", "it", "its", "that", "this", "with", "from", "as", "by"}


def _token_overlap_scores(query: str, documents: list[str]) -> np.ndarray:
    """query 与每个 document 的共享非停用词比例。
    对精确术语匹配（如 "lec8"、"SVD"、"BM25"）特别有效。
    """
    def tokens(s: str) -> set[str]:
        return {t.lower() for t in _TOKEN_RE.findall(s) if t.lower() not in _STOP}

    q_tokens = tokens(query)
    if not q_tokens:
        return np.zeros(len(documents))

    scores = np.zeros(len(documents))
    for i, doc in enumerate(documents):
        d_tokens = tokens(doc)
        if not d_tokens:
            continue
        shared = q_tokens & d_tokens
        precision = len(shared) / len(q_tokens)
        recall = len(shared) / max(len(d_tokens), 1)
        # F1 of precision/recall on token matching
        scores[i] = (2 * precision * recall) / max(precision + recall, 1e-8)
    return scores


# ═══════════════════════════════════════════════════════════════════
# 2. Embedding cosine — query-doc pair 语义相似度（fusion 模式用）
# ═══════════════════════════════════════════════════════════════════

async def _embedding_scores(query: str, documents: list[str]) -> np.ndarray:
    """对每个 document，将 query 与 doc 拼接后 embed，计算 cosine。
    这样做可以把 query 的关键词和 doc 内容在 embedding 空间对齐。
    """
    from backend.core import embedding_client
    q_vec_np = np.array(await embedding_client.embed_one(query), dtype=np.float64)
    pairs = [f"查询: {query}\n文档: {doc[:800]}" for doc in documents]
    pair_vecs = np.array(await embedding_client.embed(pairs), dtype=np.float64)

    # batch cosine: q_vec × each pair_vec
    q_norm = float(np.linalg.norm(q_vec_np))
    p_norms = np.linalg.norm(pair_vecs, axis=1)
    dots = pair_vecs @ q_vec_np

    scores = np.zeros(len(documents))
    mask = p_norms > 1e-8
    scores[mask] = dots[mask] / (q_norm * p_norms[mask])

    # Qwen3-Embedding cosine 集中在 0.4-0.9，拉伸到 [0, 1]
    scores = (scores - 0.3) / 0.7
    return np.clip(scores, 0.0, 1.0)


async def _rerank_fusion(
    query: str,
    documents: list[str],
    top_n: int | None = None,
    score_threshold: float = 0.0,
) -> list[dict]:
    """融合 embedding + token overlap 双路打分。"""
    if not documents:
        return []

    n = len(documents)

    # 如果只有 1 条，不用打分直接返回
    if n == 1:
        return [{"index": 0, "score": 0.8, "document": documents[0]}]

    # 两路并行打分
    token_scores = _token_overlap_scores(query, documents)

    if n >= 5:
        embed_scores = await _embedding_scores(query, documents)
        w_embed, w_token = 0.4, 0.6
    else:
        # 少量候选：不值得跑 embedding，token overlap 足够
        embed_scores = np.zeros(n)
        w_embed, w_token = 0.0, 1.0

    fused = w_embed * embed_scores + w_token * token_scores

    # softmax 放大区分度（让高分与低分的差距更明显）
    from scipy.special import softmax
    fused = softmax(fused * 3.0)

    results = [
        {"index": i, "score": round(float(fused[i]), 4), "document": doc}
        for i, doc in enumerate(documents)
    ]
    results.sort(key=lambda x: x["score"], reverse=True)

    # 先取 top_n（如果有），再按阈值过滤，避免候选量大时 softmax 归一化后全被阈值杀
    if top_n is not None:
        results = results[:top_n]
    results = [r for r in results if r["score"] >= score_threshold]

    top_scores = [f"{r['score']:.3f}" for r in results[:5]]
    logger.info("Rerank (fusion) {} 条 → 返回 {} 条, top5={}", n, len(results), top_scores)
    return results


# ═══════════════════════════════════════════════════════════════════
# 3. LLM-as-judge 模式
# ═══════════════════════════════════════════════════════════════════

_LLM_SYSTEM = (
    "你是一个文档相关性打分器。给定一个【查询】和一组【文档】，"
    "你要评估每个文档对回答该查询的有用程度，给出 0~1 的相关性分数。\n"
    "\n"
    "打分锚点（务必拉开区分度）：\n"
    "  0.9~1.0 文档直接、完整地回答了查询；\n"
    "  0.6~0.8 文档包含查询的核心信息，但不完整；\n"
    "  0.3~0.5 文档与查询同领域/同主题，提供背景知识或相邻话题，即使不能直接回答也有参考价值；\n"
    "  0.1~0.2 文档仅有个别词语擦边，或同属一个课程/领域但主题不同；\n"
    "  0.0     文档与查询完全无关。\n"
    "\n"
    "评分步骤：先判断文档与查询是否属于同一知识领域（如同一课程、同一学科），再判断它能提供多少有用信息。\n"
    "同领域的即使不能直接回答，也应给 0.3 以上。不同领域但术语碰巧重叠的才给低分。\n"
    "\n"
    "特别注意：OCR 提取的代码片段、公式、图片描述也可能是高度相关的学习资料，"
    "请根据语义内容判断，不要因为格式碎片化或排版不连续而低估分数。\n"
    "\n"
    "严格只输出以下 JSON，不要任何额外文字、解释或 markdown 围栏：\n"
    '{"scores": [{"index": 文档编号整数, "score": 相关性分浮点}, ...]}\n'
    "必须为输入里的每个文档都给出且仅给出一项。\n"
    "\n"
    "示例 1（直接回答 + 同主题背景 + 擦边 + 无关）：\n"
    "查询：怎么教猫咪用猫砂盆\n"
    "文档:\n"
    "[0] 把猫砂盆放在安静角落，猫进食后抱它到盆里，用前爪扒猫砂，几次后它就学会了。\n"
    "[1] 猫的厕所应每天清理，保持干净卫生，否则猫会拒绝使用。\n"
    "[2] 狗狗定点排便需要在固定地点反复引导和奖励。\n"
    "[3] 猫是哺乳动物，寿命一般十几年。\n"
    "[4] 量子纠缠是微观粒子间的非局域关联现象。\n"
    '输出：{"scores": [{"index": 0, "score": 0.95}, {"index": 1, "score": 0.65}, {"index": 2, "score": 0.25}, {"index": 3, "score": 0.15}, {"index": 4, "score": 0.0}]}\n'
    "\n"
    "示例 2（核心信息但不完整 + 背景补充 + 同领域可参考 + OCR 碎片）：\n"
    "查询：Dijkstra 算法的时间复杂度是多少\n"
    "文档:\n"
    "[0] Dijkstra 算法通过优先队列每次选择距离最小的未访问节点，时间复杂度为 O((V+E) log V)。\n"
    "[1] A* 算法在 Dijkstra 基础上引入启发式函数，能更高效地找到最短路径。\n"
    "[2] 为了优化图搜索的效率，我们可以使用二叉堆或斐波那契堆等数据结构。\n"
    "[3] V(s) = max_a Σ P(s'|s,a) [R(s,a,s') + γ V(s')] 这就是 Bellman 方程。\n"
    '输出：{"scores": [{"index": 0, "score": 1.0}, {"index": 1, "score": 0.55}, {"index": 2, "score": 0.35}, {"index": 3, "score": 0.0}]}'
)


def _llm_rerank_max_tokens(n_docs: int) -> int:
    from backend import config
    return min(config.RERANK_MAX_TOKENS_CAP, 40 * n_docs + 64)


async def _llm_score_with_retry(messages: list[dict], n_docs: int) -> dict:
    from backend import config
    from backend.core import llm_client
    from backend.core.json_parser import parse_llm_json

    max_tokens = _llm_rerank_max_tokens(n_docs)
    last_err: Exception | None = None
    for attempt in range(config.RERANK_MAX_RETRIES + 1):
        try:
            raw, _ = await llm_client.chat(messages, temperature=0, max_tokens=max_tokens)
            parsed = parse_llm_json(raw, default={"scores": []})
            if parsed.get("scores"):
                if attempt:
                    logger.info("LLM Rerank 第 {} 次重试成功", attempt)
                return parsed
            last_err = ValueError("解析结果无 scores")
        except Exception as e:
            last_err = e
        if attempt < config.RERANK_MAX_RETRIES:
            backoff = 0.5 * (2 ** attempt)
            logger.warning("LLM Rerank 第 {} 次失败({}), {}s 后重试", attempt + 1, last_err, backoff)
            await asyncio.sleep(backoff)
    logger.error("LLM Rerank 重试 {} 次仍失败: {}, 兜底全 0", config.RERANK_MAX_RETRIES, last_err)
    return {"scores": []}


async def _rerank_llm(
    query: str,
    documents: list[str],
    top_n: int | None = None,
    score_threshold: float = 0.0,
) -> list[dict]:
    """LLM (DeepSeek-V4) 打分精排。语义理解细腻，适合复杂查询。"""
    if not documents:
        return []
    if len(documents) == 1:
        return [{"index": 0, "score": 0.8, "document": documents[0]}]

    numbered = "\n".join(f"[{i}] {doc}" for i, doc in enumerate(documents))
    messages = [
        {"role": "system", "content": _LLM_SYSTEM},
        {"role": "user", "content": f"查询：{query}\n\n文档:\n{numbered}"},
    ]

    parsed = await _llm_score_with_retry(messages, len(documents))

    score_map: dict[int, float] = {}
    for item in parsed.get("scores", []):
        try:
            idx = int(item["index"])
            if 0 <= idx < len(documents):
                score_map[idx] = float(item["score"])
        except (KeyError, ValueError, TypeError):
            continue

    results = [
        {"index": i, "score": score_map.get(i, 0.0), "document": doc}
        for i, doc in enumerate(documents)
    ]
    results.sort(key=lambda x: x["score"], reverse=True)

    results = [r for r in results if r["score"] >= score_threshold]
    if top_n is not None:
        results = results[:top_n]

    top_scores = [f"{r['score']:.3f}" for r in results[:5]]
    logger.info("Rerank (LLM) {} 条 → 返回 {} 条, top5={}", len(documents), len(results), top_scores)
    return results


# ═══════════════════════════════════════════════════════════════════
# 4. 统一入口 — 根据 mode 分发
# ═══════════════════════════════════════════════════════════════════

async def rerank(
    query: str,
    documents: list[str],
    top_n: int | None = None,
    score_threshold: float = 0.0,
    mode: str = "fusion",
) -> list[dict]:
    """统一精排入口。

    mode:
      "fusion" — 本地 embedding + token overlap（默认，快）
      "llm"    — DeepSeek-V4 LLM 打分（语义细腻，慢）

    返回: [{"index": int, "score": float, "document": str}, ...]
    """
    if mode == "llm":
        return await _rerank_llm(query, documents, top_n=top_n, score_threshold=score_threshold)
    # 默认走 fusion（未知 mode 也兜底到 fusion）
    if mode != "fusion":
        logger.warning("未知 rerank_mode={!r}，兜底到 fusion", mode)
    return await _rerank_fusion(query, documents, top_n=top_n, score_threshold=score_threshold)
