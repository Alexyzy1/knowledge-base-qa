"""精排映射层测试。使用 conftest mock_rerank fixture，不单独 mock。"""
import pytest
from backend.retrieval.reranker import rerank_chunks


class TestRerankChunks:

    @pytest.mark.asyncio
    async def test_empty_candidates(self):
        """空候选 → 空返回。"""
        result = await rerank_chunks("query", [])
        assert result == []

    @pytest.mark.asyncio
    async def test_rerank_adds_score_field(self, mock_rerank):
        """精排后每个 chunk 新增 rerank_score 字段。"""
        candidates = [
            {"chunk_id": 1, "doc_id": 10, "text": "chunk A"},
            {"chunk_id": 2, "doc_id": 10, "text": "chunk B"},
        ]
        result = await rerank_chunks("query", candidates, top_n=2, score_threshold=0.0)
        assert len(result) == 2
        assert result[0]["rerank_score"] == 0.95
        assert result[1]["rerank_score"] == pytest.approx(0.80, rel=0.01)
        assert result[0]["chunk_id"] == 1
        assert result[0]["text"] == "chunk A"

    @pytest.mark.asyncio
    async def test_score_threshold_filters(self, mock_rerank):
        """低于阈值的候选被过滤。conftest mock: [0.95, 0.80]，threshold=0.9 只留 0.95。"""
        candidates = [
            {"chunk_id": 1, "doc_id": 10, "text": "A"},
            {"chunk_id": 2, "doc_id": 10, "text": "B"},
        ]
        result = await rerank_chunks("query", candidates, top_n=5, score_threshold=0.9)
        assert len(result) == 1
        assert result[0]["rerank_score"] == 0.95

    @pytest.mark.asyncio
    async def test_top_n_truncation(self, mock_rerank):
        """top_n 截断。10 个候选，top_n=3 → 只保留前 3。"""
        candidates = [{"chunk_id": i, "doc_id": 1, "text": f"c{i}"} for i in range(10)]
        result = await rerank_chunks("query", candidates, top_n=3, score_threshold=0.0)
        assert len(result) == 3
        assert result[0]["rerank_score"] > result[1]["rerank_score"]
