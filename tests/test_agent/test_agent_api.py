"""Agent API 端点集成测试。Mock 全部外部依赖。"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock


def _setup_agent_mocks(mocker, planner_queries=None, planner_reasoning="",
                        generator_answer="", verifier_passed=True,
                        verifier_issues=None, verifier_suggested=None):
    """统一 mock _make_llm + with_structured_output，返回可控的结构化输出。

    图内有 3 次 LLM 调用（Planner / Generator / Verifier）。
    Planner 和 Verifier 走 with_structured_output → 返回 Pydantic 模型。
    Generator 走 _make_llm → ainvoke → AIMessage。
    """
    from langchain_core.messages import AIMessage
    from backend.agent.graph import PlannerOutput, VerifierOutput

    # ── Planner 链 ──
    planner_chain = MagicMock()
    planner_chain.ainvoke = AsyncMock(return_value=PlannerOutput(
        queries=planner_queries if planner_queries is not None else ["测试查询"],
        reasoning=planner_reasoning or "需要检索",
    ))

    # ── Verifier 链 ──
    verifier_chain = MagicMock()
    verifier_chain.ainvoke = AsyncMock(return_value=VerifierOutput(
        passed=verifier_passed,
        issues=verifier_issues or [],
        suggested_queries=verifier_suggested or [],
    ))

    # ── Generator LLM ──
    gen_llm = MagicMock()
    gen_llm.ainvoke = AsyncMock(return_value=AIMessage(
        content=generator_answer or "这是测试回答。"
    ))

    # ── with_structured_output 分发 ──
    _output_types = {}

    def _fake_with_structured_output(output_type, method=None):
        _output_types[output_type] = True
        if output_type is PlannerOutput:
            return planner_chain
        if output_type is VerifierOutput:
            return verifier_chain
        return MagicMock()

    # ── _make_llm 分发 ──
    def _fake_make_llm(temperature=0.3, max_tokens=2048):
        llm = MagicMock()
        llm.with_structured_output = _fake_with_structured_output
        if temperature == 0.7:  # Generator uses 0.7
            return gen_llm
        return llm

    mocker.patch("backend.agent.graph._make_llm", side_effect=_fake_make_llm)
    return dict(planner=planner_chain, verifier=verifier_chain, generator=gen_llm)


class TestAgentChatAPI:

    @pytest.fixture
    def client_and_kb(self, db_session, mock_llm, mock_embedding, mock_milvus, mock_rerank):
        """创建 TestClient + 测试 KB + super_admin 用户。"""
        from backend.core.auth import hash_pw
        from backend.store.auth_models import User, Whitelist, KbMember
        from backend.store import mysql_store

        s = db_session
        pw = hash_pw("Test1234")
        u = User(username="agent_tester", password_hash=pw, role="super_admin")
        s.add(u)
        s.add(Whitelist(username="agent_tester", note="test"))
        s.commit()
        user_id = u.id

        kb_id = mysql_store.create_kb("Agent测试库")
        mysql_store.create_kb_config(kb_id)
        s.add(KbMember(kb_id=kb_id, user_id=user_id, role="owner"))
        s.commit()

        from backend.main import app
        tc = TestClient(app)

        login_resp = tc.post("/api/auth/login", json={
            "username": "agent_tester", "password": "Test1234",
        })
        token = login_resp.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        return tc, kb_id, headers

    def test_agent_chat_non_stream(self, client_and_kb, mocker):
        """Agent 非流式问答。"""
        _setup_agent_mocks(mocker, planner_queries=["测试查询"],
                          generator_answer="这是测试回答完整内容。")

        tc, kb_id, headers = client_and_kb
        resp = tc.post("/api/chat/agent", json={
            "kb_id": kb_id, "query": "测试问题", "stream": False,
        }, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "answer" in data["data"]
        assert "sources" in data["data"]
        assert data["data"]["answer"] == "这是测试回答完整内容。"

    def test_agent_chat_stream(self, client_and_kb, mocker):
        """Agent 流式 SSE 输出。"""
        _setup_agent_mocks(mocker, planner_queries=["流式测试"],
                          generator_answer="流式回答内容")

        tc, kb_id, headers = client_and_kb
        resp = tc.post("/api/chat/agent", json={
            "kb_id": kb_id, "query": "流式测试", "stream": True,
        }, headers=headers)
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_agent_chat_safety_blocked(self, client_and_kb, mocker):
        """Agent 安全词拦截。"""
        from backend.core import safety

        async def _fake_blocked(text, word_check=True, use_llm=None):
            return True, "keyword:test"

        mocker.patch.object(safety, "is_blocked", side_effect=_fake_blocked)

        tc, kb_id, headers = client_and_kb
        resp = tc.post("/api/chat/agent", json={
            "kb_id": kb_id, "query": "不当内容", "stream": False,
        }, headers=headers)
        data = resp.json()
        assert data["data"]["safety_blocked"] is True

    def test_agent_chat_no_permission(self, client_and_kb, db_session):
        """Agent 无权限库 → 403。"""
        from backend.core.auth import hash_pw
        from backend.store.auth_models import User, Whitelist
        from backend.store import mysql_store

        s = db_session
        pw = hash_pw("NoPerm456")
        u = User(username="agent_noperm", password_hash=pw, role="user")
        s.add(u)
        s.add(Whitelist(username="agent_noperm", note="test"))
        s.commit()

        kb_id = mysql_store.create_kb("Agent无权限库")
        mysql_store.create_kb_config(kb_id)
        s.commit()

        from backend.main import app
        tc = TestClient(app)
        login_resp = tc.post("/api/auth/login", json={
            "username": "agent_noperm", "password": "NoPerm456",
        })
        token = login_resp.json()["data"]["access_token"]
        resp = tc.post("/api/chat/agent", json={
            "kb_id": kb_id, "query": "测试", "stream": False,
        }, headers={"Authorization": f"Bearer {token}"})
        data = resp.json()
        assert data["code"] == 403

    def test_agent_chat_direct_answer(self, client_and_kb, mocker):
        """Planner 判断无需检索 → 直接生成回答。"""
        _setup_agent_mocks(mocker, planner_queries=[],
                          planner_reasoning="打招呼无需检索",
                          generator_answer="你好！我是知识库问答助手。")

        tc, kb_id, headers = client_and_kb
        resp = tc.post("/api/chat/agent", json={
            "kb_id": kb_id, "query": "你好", "stream": False,
        }, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert "你好" in data["data"]["answer"]

    def test_agent_timeline(self, client_and_kb):
        """Agent timeline 端点 200。"""
        tc, kb_id, headers = client_and_kb
        resp = tc.get(f"/api/chat/agent/99999/timeline", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    def test_agent_state(self, client_and_kb):
        """Agent state 端点 200。"""
        tc, kb_id, headers = client_and_kb
        resp = tc.get(f"/api/chat/agent/99999/state", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    def test_agent_chat_verifier_retry(self, client_and_kb, mocker):
        """Verifier 未通过但有建议词 → 回 Searcher 重试。"""
        _setup_agent_mocks(mocker,
                          planner_queries=["初次检索"],
                          generator_answer="部分回答",
                          verifier_passed=False,
                          verifier_issues=["缺少关键信息"],
                          verifier_suggested=["补充检索词"])

        tc, kb_id, headers = client_and_kb
        resp = tc.post("/api/chat/agent", json={
            "kb_id": kb_id, "query": "复杂问题", "stream": False,
        }, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        # Verifier 未通过标记应在响应中
        assert data["data"].get("verified") is False
