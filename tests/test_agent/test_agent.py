"""Agent 模块单元测试。Mock 全部外部依赖（LLM/Milvus/MySQL），测试图节点逻辑。"""
import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# AgentState
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentState:
    """AgentState TypedDict 字段正确性。"""

    def test_state_defaults(self):
        from backend.agent.state import AgentState
        state: AgentState = {"query": "test", "kb_ids": [1]}
        assert state["query"] == "test"
        assert state["kb_ids"] == [1]
        # 可选字段默认不存在
        assert state.get("search_queries") is None

    def test_state_all_fields(self):
        from backend.agent.state import AgentState
        state: AgentState = {
            "query": "什么是RAG",
            "kb_ids": [1, 2],
            "history": [{"role": "user", "content": "你好"}],
            "search_queries": ["RAG定义", "检索增强生成"],
            "reasoning": "需要搜索RAG相关概念",
            "chunks": [{"chunk_id": 1, "text": "RAG是...", "doc_id": 1}],
            "context": "[1] (来源：doc.pdf)\nRAG是...",
            "answer": "RAG是检索增强生成技术",
            "passed": True,
            "issues": [],
            "iteration": 1,
        }
        assert len(state["search_queries"]) == 2
        assert state["iteration"] == 1
        assert state["passed"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Tools
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentTools:

    @pytest.mark.asyncio
    async def test_search_kb_returns_formatted_text(self, mock_embedding, mock_milvus, mock_rerank, db_session):
        """search_knowledge_base 返回带编号的格式化文本。"""
        from backend.store import mysql_store
        kb_id = mysql_store.create_kb("测试库")
        mysql_store.create_kb_config(kb_id)
        # 创建文档用于引用
        mysql_store.create_document(kb_id, "test.pdf", status="done")

        from backend.agent.tools import search_knowledge_base
        result = await search_knowledge_base.ainvoke({"query": "测试查询", "kb_ids": [kb_id]})
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_search_kb_empty_kb_ids(self):
        """kb_ids 为空 → 返回提示。"""
        from backend.agent.tools import search_knowledge_base
        result = await search_knowledge_base.ainvoke({"query": "测试", "kb_ids": []})
        assert "未指定" in result

    @pytest.mark.asyncio
    async def test_rewrite_query_tool_no_history(self):
        """无历史 → 原样返回。"""
        from backend.agent.tools import rewrite_query_tool
        result = await rewrite_query_tool.ainvoke({"query": "测试问题", "history": None})
        assert result == "测试问题"

    @pytest.mark.asyncio
    async def test_rewrite_query_tool_with_history(self, mocker):
        """有历史 → 触发改写。"""
        from backend.core import llm_client

        async def _fake_chat(messages, **kwargs):
            return ("测试问题的完整表述", "")

        mocker.patch.object(llm_client, "chat", side_effect=_fake_chat)

        from backend.agent.tools import rewrite_query_tool
        result = await rewrite_query_tool.ainvoke({
            "query": "它是什么",
            "history": [{"role": "user", "content": "介绍一下RAG"}],
        })
        assert result == "测试问题的完整表述"

    def test_list_kb(self, db_session):
        """列出知识库。"""
        from backend.store import mysql_store
        kb_id = mysql_store.create_kb("Agent测试库", "用于Agent测试")
        mysql_store.create_kb_config(kb_id)

        from backend.agent.tools import list_knowledge_bases
        result = list_knowledge_bases.invoke({})
        assert "Agent测试库" in result
        assert "知识库" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Graph 结构
# ═══════════════════════════════════════════════════════════════════════════════

class TestGraphStructure:

    def test_graph_compiles(self):
        """图可编译（不含 checkpointer）。"""
        from backend.agent.graph import graph
        assert graph is not None
        # 图有节点
        nodes = graph.get_graph().nodes
        assert "planner" in nodes
        assert "searcher" in nodes
        assert "generator" in nodes
        assert "verifier" in nodes

    def test_graph_compile_with_checkpointer(self):
        """图可带 checkpointer 编译。"""
        from backend.agent.checkpoint import get_checkpointer
        from backend.agent.graph import compile_graph
        cp = get_checkpointer()
        g = compile_graph(checkpointer=cp)
        assert g is not None

    def test_route_after_planner_search(self):
        """Planner 产出搜索词 → route 到 searcher。"""
        from backend.agent.graph import route_after_planner
        result = route_after_planner({"search_queries": ["关键词"]})
        assert result == "searcher"

    def test_route_after_planner_answer(self):
        """Planner 无搜索词 → route 到 generator。"""
        from backend.agent.graph import route_after_planner
        result = route_after_planner({"search_queries": []})
        assert result == "generator"

    def test_route_after_verifier_pass(self):
        """Verifier 通过 → END。"""
        from backend.agent.graph import route_after_verifier
        from langgraph.graph import END
        result = route_after_verifier({
            "passed": True, "iteration": 1, "search_queries": ["x"],
        })
        assert result == END

    def test_route_after_verifier_fail_retry(self):
        """Verifier 未通过且有建议词 → 回 searcher。"""
        from backend.agent.graph import route_after_verifier
        result = route_after_verifier({
            "passed": False, "iteration": 0, "search_queries": ["补搜词"],
        })
        assert result == "searcher"

    def test_route_after_verifier_fail_max_iter(self):
        """Verifier 失败但 iteration >= 2 → 强制放行。"""
        from backend.agent.graph import route_after_verifier
        from langgraph.graph import END
        result = route_after_verifier({
            "passed": False, "iteration": 2, "search_queries": ["x"],
        })
        assert result == END

    def test_route_after_verifier_fail_no_suggestions(self):
        """Verifier 失败但无建议词 → 强制放行。"""
        from backend.agent.graph import route_after_verifier
        from langgraph.graph import END
        result = route_after_verifier({
            "passed": False, "iteration": 0, "search_queries": [],
        })
        assert result == END


# ═══════════════════════════════════════════════════════════════════════════════
# Checkpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckpoint:

    def test_get_checkpointer_singleton(self, mocker):
        """get_checkpointer 返回单例。"""
        import backend.agent.checkpoint as cp_module
        mocker.patch.object(cp_module, "_checkpointer", None)

        cp1 = cp_module.get_checkpointer()
        cp2 = cp_module.get_checkpointer()
        assert cp1 is cp2

    def test_get_db_path(self):
        from backend.agent.checkpoint import get_db_path
        path = get_db_path()
        assert "memory" in path.lower() or "MemorySaver" in path
