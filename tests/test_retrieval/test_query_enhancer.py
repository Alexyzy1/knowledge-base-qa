"""查询增强主模块测试 —— 需 mock LLM。"""
import pytest
from backend.retrieval.query_enhancer import enhance_query, EnhancedQuery


class TestQueryEnhancer:

    @pytest.mark.asyncio
    async def test_enhance_keyword_query(self, mocker):
        """keyword 查询：不做 HyDE，不改写，sparse 权重高。"""
        from backend.core import llm_client
        import json

        call_count = 0

        async def _fake_llm(messages, **kwargs):
            nonlocal call_count
            call_count += 1
            system = messages[0].get("content", "")
            if "查询分类器" in system:
                # 分类器调用
                return (json.dumps({
                    "query_type": "keyword",
                    "complexity": "simple",
                    "reasoning": "术语查询"
                }), "")
            else:
                # 多角度改写调用
                raise AssertionError("keyword 不应该调用多角度改写")

        mocker.patch.object(llm_client, "chat", side_effect=_fake_llm)

        result = await enhance_query("lec8")
        assert result.query_type == "keyword"
        assert result.complexity == "simple"
        assert result.sub_queries == ["lec8"]       # keyword → 1 条
        assert result.hyde_embedding is None          # keyword → 不做 HyDE
        assert result.dense_weight == 0.3
        assert result.sparse_weight == 0.7

    @pytest.mark.asyncio
    async def test_enhance_concept_query_with_hyde(self, mocker):
        """concept 查询：HyDE + 2 条改写。"""
        from backend.core import llm_client
        from backend.core import embedding_client
        import json

        call_seq = []

        async def _fake_llm(messages, **kwargs):
            call_seq.append("llm")
            system = messages[0].get("content", "")
            if "查询分类器" in system:
                return (json.dumps({
                    "query_type": "concept",
                    "complexity": "medium",
                    "reasoning": "概念解释"
                }), "")
            elif "查询扩展器" in system:
                # HyDE
                return ("奇异值分解是一种矩阵分解方法……", "")
            elif "查询改写器" in system or "改写" in system:
                # Multi-angle — return 2 rewrites DIFFERENT from original
                return ("用SVD进行矩阵分解的原理\n什么是奇异值分解", "")
            else:
                return ("", "")

        async def _fake_embed_one(text):
            return [0.1] * 2560

        mocker.patch.object(llm_client, "chat", side_effect=_fake_llm)
        mocker.patch.object(embedding_client, "embed_one", side_effect=_fake_embed_one)

        result = await enhance_query("SVD是什么")
        assert result.query_type == "concept"
        assert result.complexity == "medium"
        assert len(result.sub_queries) == 3   # concept → 2 改写 + 1 原始
        assert "SVD是什么" in result.sub_queries
        assert result.hyde_embedding is not None
        assert len(result.hyde_embedding) == 2560
        assert result.dense_weight == 0.6
        assert result.sparse_weight == 0.4

    @pytest.mark.asyncio
    async def test_enhance_classifier_failure_fallback(self, mocker):
        """分类器失败 → 回退 concept/medium，整个 pipeline 继续。"""
        from backend.core import llm_client
        from backend.core import embedding_client

        async def _fake_llm(messages, **kwargs):
            system = messages[0].get("content", "")
            if "查询分类器" in system:
                raise RuntimeError("模拟超时")
            elif "查询扩展器" in system:
                return ("假设文档文本", "")
            else:
                return ("改写1\n改写2", "")

        async def _fake_embed_one(text):
            return [0.1] * 2560

        mocker.patch.object(llm_client, "chat", side_effect=_fake_llm)
        mocker.patch.object(embedding_client, "embed_one", side_effect=_fake_embed_one)

        result = await enhance_query("SVD和PCA的区别")
        assert result.query_type == "concept"    # 默认值
        assert result.complexity == "medium"     # 默认值
        assert len(result.sub_queries) >= 1      # 至少原始 query
        assert "SVD和PCA的区别" in result.sub_queries

    @pytest.mark.asyncio
    async def test_enhance_chitchat_no_hyde_no_rewrite(self, mocker):
        """chitchat 查询：不检索，skip HyDE 和改写。"""
        from backend.core import llm_client
        import json

        async def _fake_llm(messages, **kwargs):
            system = messages[0].get("content", "")
            if "查询分类器" in system:
                return (json.dumps({
                    "query_type": "chitchat",
                    "complexity": "simple",
                    "reasoning": "打招呼"
                }), "")
            else:
                raise AssertionError("chitchat 不应该调用 HyDE 或改写 LLM")

        mocker.patch.object(llm_client, "chat", side_effect=_fake_llm)

        result = await enhance_query("你好")
        assert result.query_type == "chitchat"
        assert result.complexity == "simple"
        assert result.sub_queries == ["你好"]
        assert result.hyde_embedding is None
