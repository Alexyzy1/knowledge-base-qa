"""内容安全过滤测试。"""
import pytest
from backend.core import safety


class TestQuickCheck:

    def test_hit_blocked(self):
        """词库命中 → 返回命中词。"""
        result = safety.quick_check("我想看色情内容")
        assert result is not None

    def test_no_hit_pass(self):
        """词库未命中 → 返回 None。"""
        result = safety.quick_check("地铁票价怎么算")
        assert result is None

    def test_empty_text_pass(self):
        """空文本 → None。"""
        assert safety.quick_check("") is None
        assert safety.quick_check("   ") is None

    # ── P1-2: 纯 ASCII 词 \\b 边界匹配，防止短词误伤 ──

    def test_ascii_word_in_chinese_context_hits(self):
        """中文语境下纯 ASCII 词仍命中（\b 在中文/ASCII 间有效）。"""
        assert safety.quick_check("看AV视频") is not None
        assert safety.quick_check("涉及SM内容") is not None

    def test_ascii_word_no_false_positive_in_english(self):
        """英文单词中的子串不误伤。"""
        assert safety.quick_check("JAVASCRIPT") is None
        assert safety.quick_check("I have a question") is None
        assert safety.quick_check("SMALL") is None
        assert safety.quick_check("COSMIC") is None
        assert safety.quick_check("TRANSMISSION") is None
        assert safety.quick_check("FAVORITE") is None

    def test_ascii_word_hits_standalone(self):
        """纯 ASCII 词独立出现时命中。"""
        assert safety.quick_check("AV 视频") is not None
        assert safety.quick_check("看 AV 的网站") is not None

    def test_chinese_word_still_substring(self):
        """中文词仍用子串匹配（不受 ASCII 边界逻辑影响）。"""
        assert safety.quick_check("涉及色情内容") is not None
        assert safety.quick_check("涉及毒品交易") is not None


class TestLLMCheck:

    @pytest.mark.asyncio
    async def test_llm_unsafe(self, mocker):
        """LLM 审查判定 unsafe。"""
        from backend.core import llm_client

        async def _fake_chat(messages, **kwargs):
            return ('{"unsafe": true, "category": "色情"}', "")

        mocker.patch.object(llm_client, "chat", side_effect=_fake_chat)
        result = await safety.llm_check("不当内容")
        assert result is True

    @pytest.mark.asyncio
    async def test_llm_safe(self, mocker):
        """LLM 审查判定 safe。"""
        from backend.core import llm_client

        async def _fake_chat(messages, **kwargs):
            return ('{"unsafe": false, "category": "none"}', "")

        mocker.patch.object(llm_client, "chat", side_effect=_fake_chat)
        result = await safety.llm_check("普通内容")
        assert result is False

    @pytest.mark.asyncio
    async def test_llm_exception_pass(self, mocker):
        """LLM 审查异常 → 放行（不阻断正常问答）。"""
        from backend.core import llm_client

        async def _fake_chat(messages, **kwargs):
            raise RuntimeError("模拟 LLM 崩溃")

        mocker.patch.object(llm_client, "chat", side_effect=_fake_chat)
        result = await safety.llm_check("任何内容")
        assert result is False


class TestIsBlocked:

    @pytest.mark.asyncio
    async def test_word_hit_blocks(self):
        """词库命中即拦截，不调 LLM。"""
        blocked, reason = await safety.is_blocked("色情内容", word_check=True, use_llm=False)
        assert blocked is True
        assert reason.startswith("keyword:")

    @pytest.mark.asyncio
    async def test_llm_check_hit(self, mocker):
        """词库未命中，LLM 判定 unsafe。"""
        from backend.core import llm_client

        async def _fake_chat(messages, **kwargs):
            return ('{"unsafe": true, "category": "暴力"}', "")

        mocker.patch.object(llm_client, "chat", side_effect=_fake_chat)
        blocked, reason = await safety.is_blocked("看似正常的内容", word_check=True, use_llm=True)
        assert blocked is True
        assert reason == "llm"
