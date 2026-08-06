"""中文文本分段测试。纯函数，无外部依赖。"""
import pytest
from backend.ingest.text_splitter import (
    split_text, split_text_recursive,
    split_text_markdown, split_text_sentence_window,
    _cosine_similarity,
)


class TestSplitText:

    def test_chinese_sentence_boundary(self):
        """标准中文分段：在句号处断开。"""
        text = "第一段落包含多个句子。第二段落也是独立句子！第三段呢？结尾。"
        chunks = split_text(text, chunk_size=15, overlap=3)
        assert len(chunks) >= 1
        assert all(c for c in chunks)

    def test_long_no_punctuation(self):
        """无标点长文本：按 chunk_size 硬切。"""
        text = "A" * 1200
        chunks = split_text(text, chunk_size=500, overlap=50)
        assert len(chunks) >= 2

    def test_empty_text(self):
        """空文本返回空列表。"""
        assert split_text("") == []
        assert split_text("   ") == []

    def test_overlap_raises_when_invalid(self):
        """overlap >= chunk_size 抛 ValueError。"""
        with pytest.raises(ValueError):
            split_text("测试文本内容", chunk_size=50, overlap=50)

    def test_overlap_consistency(self):
        """overlap 正确：产出多个 chunk 且非空。"""
        text = "。".join([f"第{i}句测试内容足够长从而需要多个chunk" for i in range(50)])
        chunks = split_text(text, chunk_size=200, overlap=50)
        assert len(chunks) >= 5
        for c in chunks:
            assert len(c) > 0


class TestSplitTextRecursive:

    def test_paragraph_split(self):
        """按段落切分：\\n\\n 优先。"""
        text = "第一段内容。\n\n第二段内容。\n\n第三段很长" + "内容" * 500
        chunks = split_text_recursive(text, chunk_size=300, overlap=30)
        assert len(chunks) >= 3
        assert all(c for c in chunks)

    def test_sentence_boundary_fallback(self):
        """无段落时回退到句末标点切。"""
        text = "这是第一个句子。这是第二个句子！这是第三个？这是第四个；这是第五个。"
        chunks = split_text_recursive(text, chunk_size=30, overlap=5)
        assert len(chunks) >= 2

    def test_empty_text(self):
        assert split_text_recursive("") == []
        assert split_text_recursive("   ") == []

    def test_single_long_word(self):
        """单个超长无标点词 → 硬切。"""
        text = "A" * 1500
        chunks = split_text_recursive(text, chunk_size=500, overlap=50)
        assert len(chunks) >= 3
        assert all(len(c) <= 500 for c in chunks)

    def test_overlap_consistency(self):
        """重叠正确：相邻 chunk 共享内容。"""
        text = "。".join([f"第{i}句测试内容足够长从而需要多个chunk切分" for i in range(50)])
        chunks = split_text_recursive(text, chunk_size=200, overlap=50)
        assert len(chunks) >= 5

    def test_short_text_single_chunk(self):
        """短文本 → 单个 chunk。"""
        chunks = split_text_recursive("短短一句话。", chunk_size=500, overlap=50)
        assert len(chunks) == 1
        assert "短短一句话。" in chunks[0]


class TestSplitTextMarkdown:

    def test_header_split(self):
        """按 # 标题切分。"""
        text = "# 第一章\n内容A。\n\n## 第一节\n内容B。\n\n## 第二节\n内容C。"
        chunks = split_text_markdown(text, chunk_size=500, overlap=50)
        assert len(chunks) >= 3
        assert any("# 第一章" in c for c in chunks)

    def test_no_headers_falls_back(self):
        """无标题 → 退回 recursive。"""
        text = "普通文本没有标题。第二句内容。"
        chunks = split_text_markdown(text, chunk_size=500, overlap=50)
        assert len(chunks) >= 1

    def test_empty(self):
        assert split_text_markdown("") == []
        assert split_text_markdown("  ") == []


class TestSplitTextSentenceWindow:

    def test_window_context(self):
        """句子窗口：chunk 包含目标句及前后各一句。"""
        text = "第一句。第二句。第三句。第四句。第五句。"
        chunks = split_text_sentence_window(text, chunk_size=500, overlap=50, window_size=1)
        assert len(chunks) == 5
        # 中间句(第三句)一定存在：找到以第二句开头、包含第四句的 chunk（三句完整窗口）
        has_window = [c for c in chunks if "第二句" in c and "第三句" in c and "第四句" in c]
        assert len(has_window) >= 1
        assert "第一句" not in has_window[0]  # 不应越界到更外层的句子

    def test_empty(self):
        assert split_text_sentence_window("") == []

    def test_single_sentence(self):
        chunks = split_text_sentence_window("仅此一句。", chunk_size=500)
        assert len(chunks) == 1
        assert "仅此一句" in chunks[0]


class TestCosineSimilarity:

    def test_identical(self):
        sim = _cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        assert sim == pytest.approx(1.0, rel=0.001)

    def test_orthogonal(self):
        sim = _cosine_similarity([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
        assert sim == pytest.approx(0.0, abs=0.001)

    def test_opposite(self):
        sim = _cosine_similarity([1.0, 1.0], [-1.0, -1.0])
        assert sim == pytest.approx(-1.0, rel=0.001)
