"""查询分类器测试 —— 需 mock LLM。"""
import pytest
from backend.retrieval.query_classifier import classify_query, ClassifyResult


class TestQueryClassifier:

    @pytest.mark.asyncio
    async def test_classify_keyword_query(self, mocker):
        """术语/编号类查询 → keyword + simple。"""
        from backend.core import llm_client
        import json

        async def _fake(messages, **kwargs):
            return (json.dumps({
                "query_type": "keyword",
                "complexity": "simple",
                "reasoning": "这是一个术语查询"
            }), "")

        mocker.patch.object(llm_client, "chat", side_effect=_fake)
        result = await classify_query("lec8")
        assert result.query_type == "keyword"
        assert result.complexity == "simple"

    @pytest.mark.asyncio
    async def test_classify_comparative_query(self, mocker):
        """对比类查询 → comparative + medium/complex。"""
        from backend.core import llm_client
        import json

        async def _fake(messages, **kwargs):
            return (json.dumps({
                "query_type": "comparative",
                "complexity": "complex",
                "reasoning": "涉及到两种算法对比"
            }), "")

        mocker.patch.object(llm_client, "chat", side_effect=_fake)
        result = await classify_query("SVD和PCA有什么区别")
        assert result.query_type == "comparative"
        assert result.complexity == "complex"

    @pytest.mark.asyncio
    async def test_classify_chitchat(self, mocker):
        """问候类查询 → chitchat + simple。"""
        from backend.core import llm_client
        import json

        async def _fake(messages, **kwargs):
            return (json.dumps({
                "query_type": "chitchat",
                "complexity": "simple",
                "reasoning": "打招呼而已"
            }), "")

        mocker.patch.object(llm_client, "chat", side_effect=_fake)
        result = await classify_query("你好")
        assert result.query_type == "chitchat"
        assert result.complexity == "simple"

    @pytest.mark.asyncio
    async def test_classify_llm_failure_fallback(self, mocker):
        """LLM 调用失败 → 回退概念/中等。"""
        from backend.core import llm_client

        async def _fake(messages, **kwargs):
            raise RuntimeError("模拟 LLM 超时")

        mocker.patch.object(llm_client, "chat", side_effect=_fake)
        result = await classify_query("SVD是什么")
        assert result.query_type == "concept"
        assert result.complexity == "medium"

    @pytest.mark.asyncio
    async def test_no_history_short_query(self, mocker):
        """无历史的短查询，正常分类。"""
        from backend.core import llm_client
        import json

        async def _fake(messages, **kwargs):
            return (json.dumps({
                "query_type": "concept",
                "complexity": "medium",
                "reasoning": "概念解释问题"
            }), "")

        mocker.patch.object(llm_client, "chat", side_effect=_fake)
        result = await classify_query("什么是强化学习")
        assert result.query_type == "concept"
        assert result.complexity == "medium"
