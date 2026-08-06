"""HyDE (Hypothetical Document Embeddings) —— 假设文档生成。

思路：让 LLM 根据用户问题生成一段「教科书式描述」，
对其做 embedding，用这个向量去检索。
这样检索的是「答案应该长什么样」而不是「问题长什么样」，
能更精准地匹配知识库中的相关内容。

仅对 concept/comparative 类查询有意义；
keyword 和 chitchat 类不应调用此模块。
"""
from __future__ import annotations

from loguru import logger

from backend.core import llm_client, embedding_client

HYDE_SYSTEM = (
    "你是知识库问答系统的查询扩展器。"
    "根据用户问题，生成一段假设性的「教科书式定义或解释」（中文，80-150字），"
    "这段文字会被用于知识库的语义检索。"
    "不要回答问题本身，只要写一段关于该主题的典型描述，"
    "像一个知识库文档里会出现的段落那样。"
    "只输出描述本身，不要任何前缀或引号。"
)


async def generate_hyde_embedding(query: str) -> list[float] | None:
    """生成 HyDE 假设文档的 embedding 向量。

    Returns:
        2560 维 float 列表，或 None（失败时上层跳过 HyDE 通道）。
    """
    messages = [
        {"role": "system", "content": HYDE_SYSTEM},
        {"role": "user", "content": f"用户问题：{query}"},
    ]

    # Step 1: LLM 生成假设文档
    try:
        hyde_text, _ = await llm_client.chat(
            messages, temperature=0.3, max_tokens=200,
        )
        hyde_text = (hyde_text or "").strip()
        if not hyde_text:
            logger.info("HyDE: LLM 返回空文本，跳过")
            return None
    except Exception as exc:
        logger.warning("HyDE: LLM 调用失败，跳过: {}", exc)
        return None

    logger.info("HyDE: 生成假设文档 {} 字: {!r}", len(hyde_text), hyde_text[:80])

    # Step 2: 对假设文档做 embedding
    try:
        vec = await embedding_client.embed_one(hyde_text)
        return vec
    except Exception as exc:
        logger.warning("HyDE: embedding 失败，跳过: {}", exc)
        return None
