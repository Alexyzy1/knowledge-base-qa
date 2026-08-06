"""检索语句改写（任务 8：上下文能力）。

多轮对话里用户常用指代（"它/这个/上面那个/那再呢"），单看当前问题无法检索。
本模块用对话历史把当前问题改写成「不依赖上下文、可独立检索」的查询，再交给召回层。

设计：
  - 无历史 → 直接返回原 query，不调 LLM（省一次调用）。
  - 有历史 → 一次轻量 LLM 调用，max_tokens 受限；失败/异常一律回退原 query，
    绝不因为改写挂掉而阻断问答。
"""
from __future__ import annotations

from loguru import logger

from backend import config
from backend.core import llm_client

_SYSTEM = (
    "你是检索查询改写器。根据【对话历史】，把用户【当前问题】改写成一句"
    "不依赖上下文、可独立用于知识库检索的完整查询。\n"
    "规则：\n"
    "  - 把代词/省略（它、这个、那、上面提到的…）补全成具体名词；\n"
    "  - 只补全指代，不要新增历史里没有的信息，不要回答问题；\n"
    "  - 如果当前问题本身已经完整、与历史无关，原样返回；\n"
    "  - 只输出改写后的查询本身，不要任何前缀、引号或解释。"
)

# 只取最近若干轮，避免历史过长喂爆 token
_MAX_HISTORY_MSGS = 6

# 改写后查询的硬上限（字符数）。超过此长度直接用原 query，
# 防止 LLM 输出冗长文本稀释检索精度。
_MAX_REWRITE_CHARS = 200


def _format_history(history: list[dict]) -> str:
    lines = []
    for m in history[-_MAX_HISTORY_MSGS:]:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        who = "用户" if role == "user" else "助手"
        lines.append(f"{who}：{content}")
    return "\n".join(lines)


async def rewrite(query: str, history: list[dict] | None) -> str:
    """返回用于检索的查询。无历史或改写失败时返回原 query。"""
    if not history:
        return query
    hist_text = _format_history(history)
    if not hist_text:
        return query
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"【对话历史】\n{hist_text}\n\n【当前问题】\n{query}"},
    ]
    try:
        rewritten, _ = await llm_client.chat(
            messages, temperature=0,
            max_tokens=config.QUERY_REWRITE_MAX_TOKENS,
        )
        rewritten = (rewritten or "").strip()
        if not rewritten:
            return query
        if len(rewritten) > max(len(query) * 3, _MAX_REWRITE_CHARS):
            logger.warning("检索改写过长({} 字),回退原 query: {!r}", len(rewritten), rewritten[:80])
            return query
        logger.info("检索改写: {!r} → {!r}", query, rewritten)
        return rewritten
    except Exception as e:
        logger.warning("检索改写失败,回退原 query: {}", e)
        return query
