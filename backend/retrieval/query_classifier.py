"""查询分类器 —— 判断 query 类型与复杂度，指导后续增强步骤的策略选择。"""
from __future__ import annotations

import json
from dataclasses import dataclass

from loguru import logger

from backend.core import llm_client

CLASSIFIER_SYSTEM = (
    "你是查询分类器。分析用户问题，输出类型和复杂度。\n\n"
    "类型定义：\n"
    "  - keyword：术语/编号/文件名查询（如 lec8、SVD、BM25、CS188）\n"
    "  - concept：概念解释、定义类问题（如 SVD是什么、强化学习定义）\n"
    "  - comparative：对比分析（如 A和B的区别、X比Y好在哪）\n"
    "  - procedural：步骤/方法/操作指引（如 怎么做X、如何实现Y）\n"
    "  - chitchat：打招呼、询问能力、闲聊（如 你好、你能做什么）\n\n"
    "复杂度定义：\n"
    "  - simple：单一概念、明确可在一个段落中找到答案\n"
    "  - medium：需要综合多个知识点或段落\n"
    "  - complex：需要跨文档对比、多步推理\n\n"
    "输出严格的 JSON，字段：query_type, complexity, reasoning（一句话）。\n"
    "不要输出任何 JSON 以外的内容。"
)


@dataclass
class ClassifyResult:
    query_type: str    # keyword | concept | comparative | procedural | chitchat
    complexity: str    # simple | medium | complex
    reasoning: str


async def classify_query(query: str, history: list[dict] | None = None) -> ClassifyResult:
    """对 query 做类型+复杂度分类。LLM 调用失败 → 保守默认值。"""
    user_msg = f"用户问题：{query}"
    if history:
        recent = history[-4:]
        hist_text = "\n".join(
            f"{'用户' if m['role'] == 'user' else '助手'}：{m['content'][:100]}"
            for m in recent
        )
        user_msg = f"对话历史：\n{hist_text}\n\n{user_msg}"

    messages = [
        {"role": "system", "content": CLASSIFIER_SYSTEM},
        {"role": "user", "content": user_msg},
    ]

    try:
        result_str, _ = await llm_client.chat(
            messages, temperature=0, max_tokens=128,
        )
        result_str = (result_str or "").strip()

        # 容错：去掉可能的 markdown code fence
        if result_str.startswith("```"):
            lines = result_str.split("\n")
            result_str = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        data = json.loads(result_str)
        return ClassifyResult(
            query_type=data.get("query_type", "concept"),
            complexity=data.get("complexity", "medium"),
            reasoning=data.get("reasoning", ""),
        )
    except Exception as exc:
        logger.warning("查询分类失败，回退默认值 concept/medium: {}", exc)
        return ClassifyResult(query_type="concept", complexity="medium", reasoning="")
