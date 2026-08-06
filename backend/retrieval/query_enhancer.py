"""Query Enhancement Pipeline —— 查询增强主模块。

组合以下步骤，生成一个增强后的查询结构，供后端检索层使用：

1. QueryClassifier  → query_type + complexity（后续步骤的策略依据）
2. HyDE Expander    → 假设文档 embedding（仅 concept/comparative）
3. Multi-Angle Rewrite → 1~3 条子查询（从不同角度召回）
4. Weight Config    → dense/sparse RRF 融合权重

设计原则：
- 每一步独立、可单独开关（config.py 的 feature flag 控制）
- 任何步骤失败 → 回退原始 query 或默认值，不阻塞检索
- 每个步骤的函数内部记录日志，方便排查
"""
from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from backend import config


@dataclass
class EnhancedQuery:
    original: str                       # 原始查询（query_rewriter 改写后）
    query_type: str                     # keyword | concept | comparative | procedural | chitchat
    complexity: str                     # simple | medium | complex
    sub_queries: list[str] = field(default_factory=list)  # 子查询列表（含 original）
    hyde_embedding: list[float] | None = None
    dense_weight: float = 0.5
    sparse_weight: float = 0.5


# ── 权重表 ──

_WEIGHT_TABLE = {
    "keyword":     (0.3, 0.7),
    "concept":     (0.6, 0.4),
    "comparative": (0.5, 0.5),
    "procedural":  (0.5, 0.5),
    "chitchat":    (0.5, 0.5),  # chitchat 不检索，权重无实际意义
}


def _get_weights(query_type: str) -> tuple[float, float]:
    return _WEIGHT_TABLE.get(query_type, (0.5, 0.5))


# ── 多角度改写 ──

_MULTI_ANGLE_SYSTEM = (
    "你是查询改写器。把用户问题改写成 {n} 个不同角度的搜索查询。\n"
    "规则：\n"
    "  1. 每个查询是一个独立可检索的短句或关键词；\n"
    "  2. 覆盖不同表述方式（同义词、换个说法）；\n"
    "  3. keyword 类只生成 1 个（术语本身已经很精确）；\n"
    "  4. 输出结果每行一个查询，不要编号、前缀或解释。"
)

_QUERY_COUNT = {
    "keyword": 1,
    "concept": 2,
    "comparative": 3,
    "procedural": 3,
    "chitchat": 1,
}


async def _multi_angle_rewrite(original: str, query_type: str) -> list[str]:
    """生成多角度子查询。失败或数量不足时回退到 [original]."""
    n = _QUERY_COUNT.get(query_type, 1)
    if n <= 1:
        return [original]

    if not getattr(config, 'MULTI_QUERY_ENABLED', True):
        return [original]

    from backend.core import llm_client

    system = _MULTI_ANGLE_SYSTEM.format(n=n)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"原始问题：{original}"},
    ]

    try:
        result_str, _ = await llm_client.chat(
            messages, temperature=0.2, max_tokens=200,
        )
        lines = [line.strip() for line in (result_str or "").split("\n") if line.strip()]
        # 第一行保持 original
        if lines:
            lines = [original] + [l for l in lines if l != original][:n]
        if len(lines) < 1:
            return [original]
        logger.info("多角度改写: {} → {} 条子查询", original[:60], len(lines))
        return lines[:n + 1]  # original + n 条改写
    except Exception as exc:
        logger.warning("多角度改写失败，回退单 query: {}", exc)
        return [original]


async def enhance_query(query: str, history: list[dict] | None = None) -> EnhancedQuery:
    """完整查询增强 pipeline。主入口。"""
    if not getattr(config, 'ENHANCE_ENABLED', True):
        return EnhancedQuery(
            original=query, query_type="concept", complexity="medium",
            sub_queries=[query], dense_weight=0.5, sparse_weight=0.5,
        )

    # Step A: 分类
    if getattr(config, 'ENHANCE_CLASSIFIER_ENABLED', True):
        from backend.retrieval.query_classifier import classify_query
        cls_result = await classify_query(query, history)
    else:
        cls_result = None

    if cls_result is None:
        cls_result = type("_Dummy", (), {
            "query_type": "concept", "complexity": "medium", "reasoning": "classifier disabled"
        })()

    query_type = cls_result.query_type
    complexity = cls_result.complexity
    logger.info("[Enhancer] query={!r} type={} complexity={} reasoning={!r}",
                query[:80], query_type, complexity, cls_result.reasoning[:80])

    # Step B: HyDE（仅 concept / comparative）
    hyde_vec = None
    if getattr(config, 'HYDE_ENABLED', True) and query_type in ("concept", "comparative"):
        from backend.retrieval.hyde import generate_hyde_embedding
        hyde_vec = await generate_hyde_embedding(query)
        if hyde_vec is not None:
            logger.info("[Enhancer] HyDE 生成 embedding 维度={}", len(hyde_vec))

    # Step C: 多角度改写
    sub_queries = await _multi_angle_rewrite(query, query_type)

    # Step D: 权重
    dw, sw = _get_weights(query_type)

    return EnhancedQuery(
        original=query,
        query_type=query_type,
        complexity=complexity,
        sub_queries=sub_queries,
        hyde_embedding=hyde_vec,
        dense_weight=dw,
        sparse_weight=sw,
    )
