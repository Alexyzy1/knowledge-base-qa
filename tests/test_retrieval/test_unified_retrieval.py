"""统一检索测试 —— 需 mock Milvus + Rerank + MySQL filename search。"""
import pytest
from backend.retrieval.unified_retrieval import unified_retrieve, RetrievalRequest, RetrievalResult


class TestUnifiedRetrieve:

    @pytest.mark.asyncio
    async def test_single_query_basic(self, mocker, mock_milvus, mock_rerank, mock_embedding, db_session, sample_kb):
        """单查询 → 正常返回 chunks + context。"""
        # Mock filename search 返回空
        from backend.store import mysql_store

        mocker.patch.object(mysql_store, "search_documents_by_filename", return_value=[])

        result = await unified_retrieve(RetrievalRequest(
            queries=["什么是SVD"],
            kb_ids=[sample_kb],
            rerank_mode="fusion",
            do_rerank=True,
        ))
        assert isinstance(result, RetrievalResult)
        assert len(result.chunks) > 0
        assert len(result.context) > 0
        assert "来源文件" in result.context

    @pytest.mark.asyncio
    async def test_multi_query_merge(self, mocker, mock_milvus, mock_rerank, mock_embedding, db_session, sample_kb):
        """多查询 → 结果合并去重。"""
        from backend.store import mysql_store

        mocker.patch.object(mysql_store, "search_documents_by_filename", return_value=[])

        result = await unified_retrieve(RetrievalRequest(
            queries=["SVD", "奇异值分解", "矩阵分解方法"],
            kb_ids=[sample_kb],
            rerank_mode="fusion",
            do_rerank=True,
        ))
        assert len(result.chunks) > 0
        # stats 中有合并信息
        assert "total_queries" in result.stats
        assert result.stats["total_queries"] == 3

    @pytest.mark.asyncio
    async def test_no_results(self, mocker, mock_embedding, db_session, sample_kb):
        """检索无结果 → 空 chunks。"""
        from backend.store import milvus_store
        from backend.store import mysql_store

        mocker.patch.object(milvus_store, "search", return_value=[])
        mocker.patch.object(milvus_store, "search_sparse", return_value=[])
        mocker.patch.object(mysql_store, "search_documents_by_filename", return_value=[])

        result = await unified_retrieve(RetrievalRequest(
            queries=["zzz不存在的查询zzz"],
            kb_ids=[sample_kb],
            do_rerank=False,
        ))
        assert len(result.chunks) == 0
        assert "未找到" in result.context

    @pytest.mark.asyncio
    async def test_filename_boost_applied(self, mocker, mock_milvus, mock_rerank, mock_embedding, db_session, sample_kb):
        """文件名匹配到的文档 → chunks 带 boost 分数。"""
        from backend.store import mysql_store

        mocker.patch.object(mysql_store, "search_documents_by_filename", return_value=[1])

        result = await unified_retrieve(RetrievalRequest(
            queries=["lec8"],
            kb_ids=[sample_kb],
            do_filename_match=True,
            do_rerank=True,
        ))
        assert len(result.chunks) > 0
        assert result.stats.get("filename_matches", 0) > 0

    @pytest.mark.asyncio
    async def test_hyde_embedding_channel(self, mocker, mock_milvus, mock_rerank, mock_embedding, db_session, sample_kb):
        """HyDE embedding 传入 → 作为额外 dense 通道参与检索。"""
        from backend.store import mysql_store

        mocker.patch.object(mysql_store, "search_documents_by_filename", return_value=[])

        result = await unified_retrieve(RetrievalRequest(
            queries=["SVD是什么"],
            kb_ids=[sample_kb],
            hyde_embedding=[0.1] * 2560,
            do_rerank=True,
        ))
        assert len(result.chunks) > 0
        assert result.stats.get("hyde_enabled", False) is True

    @pytest.mark.asyncio
    async def test_empty_kb_ids(self, mocker):
        """kb_ids 为空 → 空结果。"""
        result = await unified_retrieve(RetrievalRequest(
            queries=["test"],
            kb_ids=[],
            do_rerank=False,
        ))
        assert len(result.chunks) == 0
