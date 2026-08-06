"""HyDE 假设文档生成测试 —— 需 mock LLM + embedding。"""
import pytest
from backend.retrieval.hyde import generate_hyde_embedding


class TestHyDE:

    @pytest.mark.asyncio
    async def test_generate_hyde_embedding_success(self, mocker, mock_embedding):
        """正常生成：返回 2560 维向量。"""
        from backend.core import llm_client

        async def _fake_llm(messages, **kwargs):
            return ("奇异值分解(SVD)是一种矩阵分解方法，将矩阵分解为三个矩阵的乘积，广泛应用于降维、推荐系统和数据压缩等领域。", "")

        mocker.patch.object(llm_client, "chat", side_effect=_fake_llm)

        result = await generate_hyde_embedding("SVD是什么")
        assert result is not None
        assert len(result) == 2560

    @pytest.mark.asyncio
    async def test_hyde_llm_failure_fallback(self, mocker):
        """LLM 失败 → 返回 None。"""
        from backend.core import llm_client

        async def _fake_llm(messages, **kwargs):
            raise RuntimeError("模拟超时")

        mocker.patch.object(llm_client, "chat", side_effect=_fake_llm)
        result = await generate_hyde_embedding("强化学习概念")
        assert result is None

    @pytest.mark.asyncio
    async def test_hyde_embedding_failure_fallback(self, mocker):
        """Embedding 失败 → 返回 None。"""
        from backend.core import llm_client
        from backend.core import embedding_client

        async def _fake_llm(messages, **kwargs):
            return ("一段假设文本。", "")

        async def _fake_embed_one(text):
            raise RuntimeError("模拟嵌入失败")

        mocker.patch.object(llm_client, "chat", side_effect=_fake_llm)
        mocker.patch.object(embedding_client, "embed_one", side_effect=_fake_embed_one)

        result = await generate_hyde_embedding("测试查询")
        assert result is None
