#!/usr/bin/env python3
"""服务器端独立冒烟测试 —— 无需 pytest，直接运行验证 langgraph 集成的各个环节。

用法（在容器内）：
    cd yuanzy-kb
    python tests/test_agent_smoke.py

每步成功打印 ✓，失败打印 ✗ + 详细信息。
"""
from __future__ import annotations
import sys
import os
import traceback

# 确保项目根在 sys.path 中（无论从哪个目录执行）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 冒烟测试需要的最小环境：set dummy API key 以防止模块级 AsyncOpenAI 初始化报错
os.environ.setdefault("MODEL_API_KEY", "smoke-test-dummy-key")

PASS = 0
FAIL = 0


def check(name: str, fn, *args, **kwargs):
    global PASS, FAIL
    try:
        fn(*args, **kwargs)
        print(f"  ✓ {name}")
        PASS += 1
    except Exception as e:
        print(f"  ✗ {name}: {e}")
        traceback.print_exc()
        FAIL += 1


def main():
    global PASS, FAIL

    print("=" * 60)
    print("Agentic RAG 冒烟测试")
    print("=" * 60)

    # ── 1. 语法检查 ──
    print("\n[1] 语法检查")
    import ast
    agent_dir = os.path.join(os.path.dirname(__file__), "..", "backend", "agent")
    for fname in ["__init__.py", "state.py", "tools.py", "graph.py", "checkpoint.py"]:
        fpath = os.path.join(agent_dir, fname)
        check(fname, lambda p: ast.parse(open(p, encoding="utf-8").read()), fpath)
    chat_path = os.path.join(os.path.dirname(__file__), "..", "backend", "api", "chat.py")
    check("chat.py", lambda p: ast.parse(open(p, encoding="utf-8").read()), chat_path)

    # ── 2. 依赖检查 ──
    print("\n[2] 依赖检查")
    check("langgraph", lambda: __import__("langgraph"))
    check("langchain_deepseek", lambda: __import__("langchain_deepseek"))
    check("langgraph.checkpoint.memory", lambda: __import__("langgraph.checkpoint.memory"))

    # ── 3. 模块导入 ──
    print("\n[3] 模块导入")
    check("AgentState", lambda: __import__("backend.agent.state", fromlist=["AgentState"]))
    check("tools", lambda: __import__("backend.agent.tools"))
    check("checkpoint", lambda: __import__("backend.agent.checkpoint"))
    check("graph", lambda: __import__("backend.agent.graph"))

    # ── 4. 图编译 ──
    print("\n[4] 图编译")
    from backend.agent.graph import graph
    nodes = graph.get_graph().nodes
    check("planner 节点", lambda: "planner" in nodes)
    check("searcher 节点", lambda: "searcher" in nodes)
    check("generator 节点", lambda: "generator" in nodes)
    check("verifier 节点", lambda: "verifier" in nodes)
    print(f"    图节点: {sorted(nodes)}")

    # ── 5. Checkpoint ──
    print("\n[5] Checkpoint")
    from backend.agent.checkpoint import get_checkpointer, get_db_path
    cp = get_checkpointer()
    check("MemorySaver 创建", lambda: cp)
    check("存储方式", lambda: print(f"    {get_db_path()}"))

    # ── 6. Checkpoint 图编译 ──
    print("\n[6] 带 Checkpoint 的图编译")
    from backend.agent.graph import compile_graph
    g = compile_graph(checkpointer=cp)
    check("compile with checkpointer", lambda: g)

    # ── 7. 路由逻辑 ──
    print("\n[7] 路由逻辑")
    from backend.agent.graph import route_after_planner, route_after_verifier
    from langgraph.graph import END

    check("planner→search", lambda: route_after_planner({"search_queries": ["x"]}) == "searcher")
    check("planner→answer", lambda: route_after_planner({"search_queries": []}) == "generator")
    check("verifier pass→END", lambda: route_after_verifier(
        {"passed": True, "iteration": 1, "search_queries": ["x"]}) == END)
    check("verifier fail+retry→searcher",
          lambda: route_after_verifier(
              {"passed": False, "iteration": 0, "search_queries": ["x"]}) == "searcher")
    check("verifier fail+max→END",
          lambda: route_after_verifier(
              {"passed": False, "iteration": 2, "search_queries": ["x"]}) == END)

    # ── 8. Tool 签名 ──
    print("\n[8] Tool 签名")
    from backend.agent.tools import search_knowledge_base, rewrite_query_tool, list_knowledge_bases
    check("search_knowledge_base", lambda: search_knowledge_base.name == "search_knowledge_base")
    check("rewrite_query_tool", lambda: rewrite_query_tool.name == "rewrite_query_tool")
    check("list_knowledge_bases", lambda: list_knowledge_bases.name == "list_knowledge_bases")

    # ── 汇总 ──
    print("\n" + "=" * 60)
    total = PASS + FAIL
    print(f"结果: {PASS}/{total} 通过, {FAIL}/{total} 失败")
    if FAIL == 0:
        print("✅ 冒烟测试全部通过，可以部署")
    else:
        print("❌ 存在失败项，请检查以上 ✗ 输出")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
