"""检索改写测试。需 mock LLM。"""
import pytest
from backend.retrieval import query_rewriter


class TestQueryRewriter:

    @pytest.mark.asyncio
    async def test_no_history_returns_original(self):
        """无历史 → 原样返回，不调 LLM。"""
        result = await query_rewriter.rewrite("地铁票价规则", None)
        assert result == "地铁票价规则"
        result = await query_rewriter.rewrite("地铁票价规则", [])
        assert result == "地铁票价规则"

    @pytest.mark.asyncio
    async def test_with_history_triggers_rewrite(self, mocker):
        """有历史 → 触发改写。"""
        from backend.core import llm_client

        async def _fake_chat(messages, **kwargs):
            return ("地铁票价对学生是否有优惠", "")

        mocker.patch.object(llm_client, "chat", side_effect=_fake_chat)
        history = [
            {"role": "user", "content": "介绍地铁票价"},
            {"role": "assistant", "content": "按里程计费"},
        ]
        result = await query_rewriter.rewrite("它对学生有优惠吗", history)
        assert result == "地铁票价对学生是否有优惠"

    @pytest.mark.asyncio
    async def test_rewrite_empty_result_fallback(self, mocker):
        """LLM 返回空 → 回退原 query。"""
        from backend.core import llm_client

        async def _fake_chat(messages, **kwargs):
            return ("", "")

        mocker.patch.object(llm_client, "chat", side_effect=_fake_chat)
        history = [{"role": "user", "content": "测试"}]
        result = await query_rewriter.rewrite("问题", history)
        assert result == "问题"

    @pytest.mark.asyncio
    async def test_rewrite_llm_error_fallback(self, mocker):
        """LLM 调用失败 → 回退原 query。"""
        from backend.core import llm_client

        async def _fake_chat(messages, **kwargs):
            raise RuntimeError("模拟 LLM 超时")

        mocker.patch.object(llm_client, "chat", side_effect=_fake_chat)
        history = [{"role": "user", "content": "测试"}]
        result = await query_rewriter.rewrite("问题", history)
        assert result == "问题"

    # ── P1-1: 改写后长度限制，防止 LLM 输出冗长文本稀释检索精度 ──

    @pytest.mark.asyncio
    async def test_rewrite_too_long_fallback(self, mocker):
        """改写结果过长（> 原 query 3 倍且 > 200 字）→ 回退原 query。"""
        from backend.core import llm_client

        long_text = "这是一个关于知识库系统的非常详细的改写查询" * 20  # 远超 200 字
        assert len(long_text) > 200

        async def _fake_chat(messages, **kwargs):
            return (long_text, "")

        mocker.patch.object(llm_client, "chat", side_effect=_fake_chat)
        history = [{"role": "user", "content": "介绍一下知识库"}]
        result = await query_rewriter.rewrite("它是什么", history)
        # 应回退原 query（超长）
        assert result == "它是什么"

    @pytest.mark.asyncio
    async def test_rewrite_normal_length_passes(self, mocker):
        """改写结果长度合理 → 正常返回改写结果。"""
        from backend.core import llm_client

        reasonable = "知识库问答系统的核心架构是什么"

        async def _fake_chat(messages, **kwargs):
            return (reasonable, "")

        mocker.patch.object(llm_client, "chat", side_effect=_fake_chat)
        history = [{"role": "user", "content": "知识库系统架构"}, {"role": "assistant", "content": "包含RAG管线"}]
        result = await query_rewriter.rewrite("它的核心是什么", history)
        assert result == reasonable
