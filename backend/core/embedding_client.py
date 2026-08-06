# backend/core/embedding_client.py
from openai import AsyncOpenAI
from loguru import logger

from backend import config

_client = AsyncOpenAI(api_key=config.MODEL_API_KEY, base_url=config.MODEL_API_BASE)


async def embed(texts: list[str], **kwargs) -> list[list[float]]:
    """批量把文本转成向量,返回顺序与输入严格对齐。"""
    logger.debug("Embedding 请求,文本条数={}", len(texts))
    resp = await _client.embeddings.create(
        model=config.EMBEDDING_MODEL,
        input=texts,
        **kwargs,
    )
    # 按 index 排序,确保向量与输入顺序对齐(别依赖服务端原序)
    ordered = sorted(resp.data, key=lambda d: d.index)
    vectors = [d.embedding for d in ordered]

    dim = len(vectors[0]) if vectors else 0
    if dim and dim != config.EMBEDDING_DIM:
        logger.warning("Embedding 维度={},与 config.EMBEDDING_DIM={} 不一致,检查模型/配置",
                       dim, config.EMBEDDING_DIM)
    logger.info("Embedding 完成,{} 条,维度={}", len(vectors), dim)
    return vectors


async def embed_one(text: str, **kwargs) -> list[float]:
    """单条文本转向量。"""
    return (await embed([text], **kwargs))[0]
