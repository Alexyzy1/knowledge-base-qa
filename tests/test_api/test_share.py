"""分享接口测试：公开访问 + 管理操作。"""
import pytest
from fastapi.testclient import TestClient


class TestPublicShare:
    """公开分享端点 /api/share/{token} —— 免登录只读。"""

    @pytest.fixture
    def client(self, db_session, mock_milvus, mocker):
        from backend.store import mysql_store
        from backend.store import auth_store
        # 建 KB + 文档 + 分享
        kb_id = mysql_store.create_kb("分享测试KB", "测试")
        mysql_store.create_kb_config(kb_id)
        doc_id = mysql_store.create_document(kb_id, "testfile.pdf")
        self.kb_id = kb_id
        self.doc_id = doc_id
        # 写入假 chunks（防止 public_share 拼接 markdown 时报错）
        mysql_store.insert_chunks(doc_id, kb_id, [
            {"content": "# 测试内容\n\n这是分享测试文档。", "chunk_index": 0},
        ])
        created = mysql_store.create_share(kb_id, doc_id, created_by=1)
        self.token = created["token"]

        from backend.main import app
        return TestClient(app)

    def test_valid_token_returns_document(self, client):
        resp = client.get(f"/api/share/{self.token}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["doc_id"] == self.doc_id
        assert "测试内容" in data["data"]["markdown"]

    def test_invalid_token_returns_404(self, client):
        resp = client.get("/api/share/NONEXISTENT_TOKEN")
        data = resp.json()
        assert data["code"] == 404

    def test_public_share_no_auth_required(self, client):
        """公开端点不需要 Authorization header。"""
        resp = client.get(f"/api/share/{self.token}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    def test_revoked_share_returns_404(self, client):
        from backend.store import mysql_store
        mysql_store.revoke_share(1, self.kb_id)
        resp = client.get(f"/api/share/{self.token}")
        data = resp.json()
        assert data["code"] == 404


class TestShareManagement:
    """分享管理端点 —— 需 owner 权限。"""

    @pytest.fixture
    def client(self, db_session, mock_milvus):
        from backend.store import mysql_store
        from backend.store import auth_store
        from backend.core import auth as auth_core
        # 创建 super_admin 用户
        pw_hash = auth_core.hash_pw("AdminPass123")
        uid = auth_store.create_user("share_admin", pw_hash, role="super_admin")
        auth_store.add_whitelist("share_admin", note="test")
        kb_id = mysql_store.create_kb("管理测试KB", "测试")
        mysql_store.create_kb_config(kb_id)
        doc_id = mysql_store.create_document(kb_id, "test.pdf")
        self.kb_id = kb_id
        self.doc_id = doc_id

        from backend.main import app
        client = TestClient(app)
        # 登录
        resp = client.post("/api/auth/login", json={
            "username": "share_admin", "password": "AdminPass123",
        })
        token = resp.json()["data"]["access_token"]
        self.auth_headers = {"Authorization": f"Bearer {token}"}
        return client

    def test_create_share(self, client):
        resp = client.post(
            f"/api/kb/{self.kb_id}/share",
            json={"doc_id": self.doc_id},
            headers=self.auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "token" in data["data"]
        assert "url" in data["data"]

    def test_list_shares(self, client):
        resp = client.get(
            f"/api/kb/{self.kb_id}/share",
            headers=self.auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    def test_revoke_share(self, client):
        from backend.store import mysql_store
        created = mysql_store.create_share(self.kb_id, self.doc_id, created_by=1)
        resp = client.delete(
            f"/api/kb/{self.kb_id}/share/{created['id']}",
            headers=self.auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    def test_create_share_no_auth_returns_401(self, client):
        resp = client.post(
            f"/api/kb/{self.kb_id}/share",
            json={"doc_id": self.doc_id},
        )
        assert resp.status_code == 401
