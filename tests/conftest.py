"""共享 fixtures：SQLite 内存库 + Mock 外部依赖 + FastAPI TestClient。"""
from __future__ import annotations

import os
import sys

# ── 测试环境变量：防止模块级代码尝试连接真实服务 ──
os.environ.setdefault("OPENAI_API_KEY", "test-key-for-testing")
os.environ.setdefault("MODEL_API_KEY", "test-key-for-testing")
os.environ.setdefault("RL_IP_CHAT", "9999")
os.environ.setdefault("RL_IP_LOGIN", "9999")
os.environ.setdefault("RL_IP_REGISTER", "9999")
os.environ.setdefault("RL_IP_DEFAULT", "9999")
os.environ.setdefault("RL_USER_CHAT", "9999")

# Mock pymilvus.MilvusClient 构造器，防止 import milvus_store 时尝试连接
try:
    import pymilvus
    pymilvus.MilvusClient.__init__ = lambda self, *args, **kwargs: None
except ImportError:
    pass

# Mock langgraph + langchain + agent 模块（测试环境未安装这些依赖）
# backend.agent.graph 在 chat.py 中被 import，需要在任何 test 收集前 mock 掉
_AGENT_DEPS = [
    "langgraph", "langgraph.graph", "langgraph.graph.state", "langgraph.graph.message",
    "langgraph.config", "langgraph.checkpoint", "langgraph.checkpoint.memory",
    "langgraph.prebuilt", "langgraph.types",
    "langchain_deepseek",
    "langchain_core", "langchain_core.messages", "langchain_core.output_parsers",
    "langchain_core.exceptions",
]
for _mod in _AGENT_DEPS:
    try:
        __import__(_mod)
    except ImportError:
        from unittest.mock import MagicMock
        sys.modules[_mod] = MagicMock()

# backend.agent.graph 本身也 mock 掉（它依赖上面那些）
if "backend.agent.graph" not in sys.modules:
    from unittest.mock import MagicMock
    _fake_graph = MagicMock()
    _fake_graph.compile.return_value = MagicMock()
    sys.modules["backend.agent.graph"] = _fake_graph
    sys.modules["backend.agent.state"] = MagicMock()
    sys.modules["backend.agent.checkpoint"] = MagicMock()
    sys.modules["backend.agent.tools"] = MagicMock()

import pytest
from sqlalchemy import create_engine, event, BigInteger
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from datetime import datetime, timezone

# ── SQLite 兼容：BigInteger 在 SQLite 不 autoincrement，必须强制输出 INTEGER ──
from sqlalchemy.ext.compiler import compiles


@compiles(BigInteger, "sqlite")
def _sqlite_bigint_to_integer(type_, compiler, **kw):
    """SQLite 中只有 INTEGER PRIMARY KEY 才能自增，BIGINT 不行。"""
    return "INTEGER"


@pytest.fixture(scope="function")
def test_engine():
    """SQLite 内存库：创建所有表，每个测试函数重建。"""
    eng = create_engine("sqlite:///:memory:", echo=False, poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _register_now(dbapi_connection, connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
        dbapi_connection.create_function(
            "now", 0,
            lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        )

    from backend.store.mysql_store import Base as MysqlBase
    from backend.store.auth_models import Base as AuthBase
    from backend.store.conversation_store import Base as ConvBase

    MysqlBase.metadata.create_all(eng)
    AuthBase.metadata.create_all(eng)
    ConvBase.metadata.create_all(eng)

    yield eng

    ConvBase.metadata.drop_all(eng)
    AuthBase.metadata.drop_all(eng)
    MysqlBase.metadata.drop_all(eng)


@pytest.fixture
def db_session(test_engine, mocker):
    """每个测试独立 session + patch 所有模块的 engine/SessionLocal 指向 SQLite。

    注意：
      - auth_store 使用 ``Session(engine)`` 直连，因此需 patch 其 ``engine`` 引用。
      - mysql_store / conversation_store 使用 ``SessionLocal()``，patch 其 ``SessionLocal``。
    """
    from backend.store import engine as store_engine
    from backend.store import mysql_store
    from backend.store import auth_store
    from backend.store import conversation_store

    SessionLocal = sessionmaker(bind=test_engine, expire_on_commit=False)

    # 直接赋值比 mocker.patch.object 更可靠，确保线程安全
    store_engine.engine = test_engine
    store_engine.SessionLocal = SessionLocal
    mysql_store.SessionLocal = SessionLocal
    auth_store.engine = test_engine
    conversation_store.SessionLocal = SessionLocal

    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def mock_llm(mocker):
    """Mock llm_client.chat → (answer, reasoning)。"""
    from backend.core import llm_client

    async def _fake(messages, temperature=0.7, model=None, max_tokens=None,
                    thinking=False, **kwargs):
        return ("这是测试回答。", "推理内容。")

    mocker.patch.object(llm_client, "chat", side_effect=_fake)
    return _fake


@pytest.fixture
def mock_embedding(mocker):
    """Mock embedding_client → 固定 2560 维向量。"""
    from backend.core import embedding_client

    async def _fake_embed(texts):
        return [[0.1] * 2560 for _ in texts]
    async def _fake_embed_one(text):
        return [0.1] * 2560

    mocker.patch.object(embedding_client, "embed", side_effect=_fake_embed)
    mocker.patch.object(embedding_client, "embed_one", side_effect=_fake_embed_one)


@pytest.fixture
def mock_milvus(mocker):
    """Mock milvus_store search/search_sparse/insert/delete。"""
    from backend.store import milvus_store

    def _search(qv=None, kb_id=None, kb_ids=None, top_k=3, **kwargs):
        return [
            {"kb_id": 1, "doc_id": 1, "chunk_id": i, "text": f"chunk {i}",
             "score": 0.9 - i * 0.1}
            for i in range(min(top_k, 5))
        ]

    mocker.patch.object(milvus_store, "search", side_effect=_search)
    mocker.patch.object(milvus_store, "search_sparse", side_effect=_search)
    mocker.patch.object(milvus_store, "search_similar", side_effect=_search)
    mocker.patch.object(milvus_store, "insert", side_effect=lambda rows: list(range(1000, 1000+len(rows))))
    mocker.patch.object(milvus_store, "delete", side_effect=lambda ids=None, filter_expr="": {"delete_count": len(ids) if ids else 0})


@pytest.fixture
def mock_rerank(mocker):
    """Mock rerank_client.rerank。"""
    from backend.core import rerank_client

    async def _fake(query, documents, top_n=None, score_threshold=0.0, **kwargs):
        results = [{"index": i, "score": 0.95 - i*0.15, "document": d}
                   for i, d in enumerate(documents)]
        results = [r for r in results if r["score"] >= score_threshold]
        return results[:top_n] if top_n else results

    mocker.patch.object(rerank_client, "rerank", side_effect=_fake)


@pytest.fixture
def sample_kb(db_session):
    """在测试 DB 中创建知识库并返回 kb_id。"""
    from backend.store import mysql_store
    kb_id = mysql_store.create_kb("测试知识库", "用于测试")
    mysql_store.create_kb_config(kb_id)
    return kb_id
