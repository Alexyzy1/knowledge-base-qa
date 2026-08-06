"""Checkpoint 持久化 — MemorySaver 保存 Agent 执行历史。

Server 环境无 SqliteSaver（langgraph-checkpoint 4.0.3 未含 sqlite 子包），
用 MemorySaver 在进程内存中保存，单次服务周期内有效。

后续如需持久化（重启不丢），安装 langgraph-checkpoint-sqlite 后自动切换：
    pip install langgraph-checkpoint-sqlite

使用方式：
    from backend.agent.checkpoint import get_checkpointer
    from backend.agent.graph import compile_graph

    checkpointer = get_checkpointer()
    graph = compile_graph(checkpointer=checkpointer)

    config = {"configurable": {"thread_id": str(conv_id)}}
    result = await graph.ainvoke(initial_state, config=config)

    # 回溯历史
    states = list(graph.get_state_history(config))
"""
from __future__ import annotations

from loguru import logger

# 优先用 MemorySaver（langgraph 内置，零依赖）
from langgraph.checkpoint.memory import MemorySaver

_checkpointer: MemorySaver | None = None


def get_checkpointer() -> MemorySaver:
    """获取全局单例 MemorySaver。

    如果后续安装了 langgraph-checkpoint-sqlite，可在此切换为 SqliteSaver。
    """
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    _checkpointer = MemorySaver()
    logger.info("Agent Checkpointer 已初始化（MemorySaver，进程内存储）")
    return _checkpointer


def get_db_path() -> str:
    """返回 checkpoint 存储位置描述。MemorySaver 无文件路径。"""
    return "memory:// (MemorySaver, 重启后丢失)"
