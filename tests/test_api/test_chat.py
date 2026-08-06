"""问答 API 测试。Mock 全部外部依赖。"""
import pytest
from fastapi.testclient import TestClient


class TestChatAPI:

    @pytest.fixture
    def client_and_kb(self, db_session, mock_llm, mock_embedding, mock_milvus, mock_rerank):
        """创建 TestClient + 测试 KB + super_admin 用户。"""
        from backend.core.auth import hash_pw
        from backend.store.auth_models import User, Whitelist, KbMember
        from backend.store import mysql_store

        s = db_session
        pw = hash_pw("Test1234")
        u = User(username="chat_tester", password_hash=pw, role="super_admin")
        s.add(u)
        s.add(Whitelist(username="chat_tester", note="test"))
        s.commit()
        user_id = u.id

        kb_id = mysql_store.create_kb("Chat测试库")
        mysql_store.create_kb_config(kb_id)
        s.add(KbMember(kb_id=kb_id, user_id=user_id, role="owner"))
        s.commit()

        from backend.main import app
        tc = TestClient(app)

        # 登录拿 token
        login_resp = tc.post("/api/auth/login", json={
            "username": "chat_tester", "password": "Test1234",
        })
        token = login_resp.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        return tc, kb_id, headers

    def test_chat_non_stream(self, client_and_kb):
        """非流式正常问答。"""
        tc, kb_id, headers = client_and_kb
        resp = tc.post("/api/chat", json={
            "kb_id": kb_id, "query": "测试问题", "stream": False,
        }, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "answer" in data["data"]
        assert "sources" in data["data"]

    def test_chat_stream(self, client_and_kb):
        """流式 SSE 输出。"""
        tc, kb_id, headers = client_and_kb
        resp = tc.post("/api/chat", json={
            "kb_id": kb_id, "query": "测试", "stream": True,
        }, headers=headers)
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_chat_empty_recall(self, client_and_kb, mocker):
        """召回为空 → 返回固定拒答话术。"""
        from backend.store import milvus_store
        mocker.patch.object(milvus_store, "search", return_value=[])
        mocker.patch.object(milvus_store, "search_sparse", return_value=[])

        tc, kb_id, headers = client_and_kb
        resp = tc.post("/api/chat", json={
            "kb_id": kb_id, "query": "不存在的知识", "stream": False,
        }, headers=headers)
        data = resp.json()
        assert data["code"] == 0
        assert "未找到相关内容" in data["data"]["answer"]

    def test_chat_safety_blocked(self, client_and_kb, mocker):
        """安全词拦截 → 返回安全话术。"""
        from backend.core import safety

        async def _fake_blocked(text, word_check=True, use_llm=None):
            return True, "keyword:test"

        mocker.patch.object(safety, "is_blocked", side_effect=_fake_blocked)

        tc, kb_id, headers = client_and_kb
        resp = tc.post("/api/chat", json={
            "kb_id": kb_id, "query": "不当内容", "stream": False,
        }, headers=headers)
        data = resp.json()
        assert data["data"]["safety_blocked"] is True

    def test_chat_multi_kb(self, client_and_kb):
        """多库 kb_ids 问答。"""
        tc, kb_id, headers = client_and_kb
        resp = tc.post("/api/chat", json={
            "kb_ids": [kb_id], "query": "多库测试", "stream": False,
        }, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    def test_chat_no_permission(self, client_and_kb, db_session):
        """无权限库 → 403。"""
        from backend.core.auth import hash_pw
        from backend.store.auth_models import User, Whitelist
        from backend.store import mysql_store

        s = db_session
        pw = hash_pw("NoPerm123")
        u = User(username="noperm", password_hash=pw, role="user")
        s.add(u)
        s.add(Whitelist(username="noperm", note="test"))
        s.commit()

        kb_id = mysql_store.create_kb("无权限库")
        mysql_store.create_kb_config(kb_id)
        s.commit()

        from backend.main import app
        tc = TestClient(app)
        login_resp = tc.post("/api/auth/login", json={
            "username": "noperm", "password": "NoPerm123",
        })
        token = login_resp.json()["data"]["access_token"]
        resp = tc.post("/api/chat", json={
            "kb_id": kb_id, "query": "测试", "stream": False,
        }, headers={"Authorization": f"Bearer {token}"})
        data = resp.json()
        assert data["code"] == 403
