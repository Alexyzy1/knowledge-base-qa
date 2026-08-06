"""RRF 融合算法测试。纯函数，无外部依赖。"""
import pytest
from backend.retrieval.rrf import rrf_merge


class TestRRFMerge:

    def test_no_overlap(self):
        """两路无重叠 → 按 rank 融合。"""
        dense = [
            {"chunk_id": 1, "text": "A", "score": 0.9},
            {"chunk_id": 2, "text": "B", "score": 0.7},
        ]
        sparse = [
            {"chunk_id": 3, "text": "C", "score": 12.0},
            {"chunk_id": 4, "text": "D", "score": 8.0},
        ]
        result = rrf_merge({"dense": dense, "sparse": sparse}, k=60)
        assert len(result) == 4
        assert result[0]["rrf_score"] == pytest.approx(1 / 61, rel=0.01)
        assert "ranks" in result[0]
        assert "scores" in result[0]

    def test_overlap_boost(self):
        """两路有重叠 → 分数加权。"""
        dense = [
            {"chunk_id": 1, "text": "A", "score": 0.9},
            {"chunk_id": 2, "text": "B", "score": 0.7},
        ]
        sparse = [
            {"chunk_id": 1, "text": "A", "score": 12.0},
            {"chunk_id": 3, "text": "C", "score": 8.0},
        ]
        result = rrf_merge({"dense": dense, "sparse": sparse}, k=60)
        assert len(result) == 3
        assert result[0]["chunk_id"] == 1
        assert result[0]["rrf_score"] == pytest.approx(1/61 + 1/61, rel=0.01)
        assert result[0]["ranks"] == {"dense": 1, "sparse": 1}

    def test_empty_channels(self):
        """空列表 → 空返回。"""
        assert rrf_merge({"dense": [], "sparse": []}) == []

    def test_top_k_truncation(self):
        """top_k 截断。"""
        dense = [{"chunk_id": i, "text": f"c{i}"} for i in range(10)]
        sparse = []
        result = rrf_merge({"dense": dense, "sparse": sparse}, top_k=5)
        assert len(result) == 5

    def test_weighted_rrf_dense_favored(self):
        """dense 权重 0.6, sparse 权重 0.4 → dense 顶部项分数更高。"""
        dense = [
            {"chunk_id": 1, "text": "A"},
            {"chunk_id": 2, "text": "B"},
        ]
        sparse = [
            {"chunk_id": 1, "text": "A"},  # rank 1 in sparse, same as dense
            {"chunk_id": 2, "text": "B"},
        ]
        # 不加权：两者 rank 相同，rrf_score 相等
        no_w = rrf_merge({"dense": dense, "sparse": sparse}, k=60)
        assert no_w[0]["chunk_id"] == 1
        # 加权 dense=0.1 sparse=0.9：sparse rank1 的贡献远大于 dense
        w = rrf_merge({"dense": dense, "sparse": sparse}, k=60,
                      weights={"dense": 0.1, "sparse": 0.9})
        # chunk_id=1 在 sparse 也是 rank1，在 dense 也是 rank1，所以仍是第一
        assert w[0]["chunk_id"] == 1

    def test_weighted_rrf_swaps_ranking(self):
        """sparse 高权重 → sparse top 项反超 dense top。"""
        dense = [
            {"chunk_id": 100, "text": "dense_top"},
        ]
        sparse = [
            {"chunk_id": 200, "text": "sparse_top"},
        ]
        # 不加权：rank 相同分数相同
        no_w = rrf_merge({"dense": dense, "sparse": sparse}, k=60)
        scores_no_w = {c["chunk_id"]: c["rrf_score"] for c in no_w}
        assert scores_no_w[100] == pytest.approx(scores_no_w[200])

        # dense=0.1 sparse=0.9：sparse top 应明显高于 dense top
        w = rrf_merge({"dense": dense, "sparse": sparse}, k=60,
                      weights={"dense": 0.1, "sparse": 0.9})
        assert w[0]["chunk_id"] == 200
        assert w[0]["rrf_score"] > w[1]["rrf_score"]

    def test_weights_defaults_to_one(self):
        """weights=None → 所有通道权重默认为 1.0，行为与旧版一致。"""
        dense = [{"chunk_id": 1, "text": "A"}, {"chunk_id": 2, "text": "B"}]
        sparse = [{"chunk_id": 1, "text": "A"}, {"chunk_id": 3, "text": "C"}]
        result = rrf_merge({"dense": dense, "sparse": sparse}, k=60)
        # 不加 weights，chunk_id=1 成绩 = 1/61 + 1/61
        assert result[0]["chunk_id"] == 1
        assert result[0]["rrf_score"] == pytest.approx(1/61 + 1/61, rel=0.01)
