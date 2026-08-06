"""健康检查端点测试。"""
import pytest
from fastapi.testclient import TestClient


class TestHealth:

    @pytest.fixture
    def client(self, db_session, mocker):
        """Mock LLM + Milvus，只测端点结构和 MySQL 分支。"""
        # Mock LLM client
        from backend.core import llm_client
        mocker.patch.object(llm_client._client.models, "list",
                          side_effect=Exception("mock: LLM unreachable"))

        # Mock Milvus client
        from backend.store import milvus_store
        mocker.patch.object(milvus_store, "client", create=True)
        milvus_store.client.list_collections.side_effect = Exception("mock: Milvus unreachable")

        from backend.main import app
        return TestClient(app)

    def test_health_returns_checks(self, client):
        """GET /api/health 应返回 status + checks（MySQL ok，Milvus/LLM degraded）。"""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "checks" in data["data"]
        checks = data["data"]["checks"]
        # MySQL 应通过（SQLite in-memory）
        assert checks["mysql"] == "ok"
        # Milvus / LLM 已 Mock 为异常
        assert "error" in checks["milvus"]
        assert "error" in checks["llm"]
        # status 应为 degraded（至少一项非 ok）
        assert data["data"]["status"] == "degraded"
