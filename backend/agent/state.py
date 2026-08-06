"""AgentState — LangGraph 图的全局状态 TypedDict。

各节点只读写自己关心的字段，但整个 state 在所有节点间共享传递。
"""
from typing import TypedDict


class AgentState(TypedDict, total=False):
    # ── 输入（API 端点写入）──
    query: str                 # 用户原始问题
    kb_ids: list[int]          # 目标知识库 ID 列表
    history: list[dict]        # 对话历史 [{"role":"user","content":"..."}, ...]

    # ── Planner 产出 ──
    search_queries: list[str]  # Planner 决定要搜索的关键词列表
    reasoning: str             # Planner 的思考过程（给前端展示）

    # ── Searcher 产出 ──
    chunks: list[dict]         # 召回 + 精排后的 chunk 列表
    context: str               # 格式化后的上下文（带 [1][2] 来源编号）

    # ── Generator 产出 ──
    answer: str                # 最终回答文本

    # ── Verifier 产出 ──
    passed: bool               # 质检是否通过
    issues: list[str]          # 质检发现的问题列表

    # ── 控制 ──
    iteration: int             # 当前 Verifier→Searcher 循环次数（防无限）

    # ── C4: 自适应迭代 ──
    complexity: str            # simple | medium | complex（Planner 判断）
    max_iterations: int        # 最大 Verifier 重试次数（根据 complexity 计算）
    verify_enabled: bool       # 是否启用 Verifier（simple → False）
