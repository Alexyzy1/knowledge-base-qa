"""问答接口：安全拦截 → 检索改写 → hybrid 召回 → RRF 融合 → rerank 精排 → 组 Prompt → LLM 生成。

支持 stream 参数：
- stream=False：等 LLM 全部生成完，返回统一 {code,msg,data}，data 含 answer + sources。
- stream=True ：SSE 流式（text/event-stream），逐 token 推；末尾追发 `[SOURCES]` 与 `[DONE]`。
RBAC：问答前判对目标库的 reader 权限（super_admin 放行）。

本轮新增能力：
- 安全词拦截(任务7)：命中色情/暴力等 → 返回固定安全话术，且该轮不进入后续上下文。
- 上下文能力(任务8)：前端传 history，后端用它把当前问题改写成可独立检索的 query。
- 问答边界(任务6)：仅当召回为空时直接拒答「知识库中未找到相关内容」，不调 LLM、不编造。
- 来源引用(任务5)：上下文按文件编号 [1][2]，回答内引用角标，sources 带文件名。
- max_tokens(任务4)：回答生成设上限，省算力、防跑飞。
"""
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, model_validator
from loguru import logger
from backend import config
from backend.retrieval.retriever import retrieve, diversify_chunks
from backend.retrieval.reranker import rerank_chunks
from backend.retrieval import query_rewriter
from backend.core import llm_client, safety, embedding_client
from backend.store import mysql_store as db
from backend.store import auth_store as astore
from backend.store import conversation_store as cstore
from backend.core.response import success
from backend.core.deps import get_current_user
from backend.core import rbac
from backend.agent.graph import graph as agent_graph
from backend.agent.state import AgentState
router = APIRouter(prefix="/api", tags=["chat"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    kb_id: int | None = None         # 单库（向后兼容）
    kb_ids: list[int] | None = None  # 多库（新增，优先于 kb_id）
    query: str
    stream: bool = False
    llm_model: int | None = None
    model: int | None = None
    rerank_enabled: bool | None = None
    history: list[ChatMessage] | None = None
    thinking: bool = False
    conversation_id: int | None = None  # 对话记录 ID（继续已有对话）

    @model_validator(mode='after')
    def _validate_kb_selection(self):
        if self.kb_id is None and (self.kb_ids is None or len(self.kb_ids) == 0):
            raise ValueError("必须指定 kb_id 或 kb_ids")
        return self


class AgentChatRequest(BaseModel):
    """Agentic RAG 问答请求。与 ChatRequest 字段对齐，agent 图内部自主决定检索策略。"""
    kb_id: int | None = None
    kb_ids: list[int] | None = None
    query: str
    stream: bool = True
    history: list[ChatMessage] | None = None
    conversation_id: int | None = None
    thinking: bool = False

    @model_validator(mode='after')
    def _validate_kb_selection(self):
        if self.kb_id is None and (self.kb_ids is None or len(self.kb_ids) == 0):
            raise ValueError("必须指定 kb_id 或 kb_ids")
        return self


SYSTEM_PROMPT = (
    "你是一个知识库问答助手。回答用户问题时，请按以下格式输出：\n"
    "\n"
    "<thinking>\n"
    "在这里写下你的分析、推理、查阅知识库的过程。\n"
    "可以包括：用户问题的关键词提取、相关知识点匹配、推理链条、需要验证的假设。\n"
    "</thinking>\n"
    "\n"
    "<answer>\n"
    "只输出最终给用户看的简洁回答。\n"
    "不要包含任何思考过程、分析步骤或\"我认为\"等字样。\n"
    "</answer>\n"
    "\n"
    "重要规则：\n"
    "1. 严格依据下面提供的【上下文】回答用户问题\n"
    "2. 每段上下文前都有形如 [1]、[2] 的来源编号，回答时在引用处标注对应角标，如「地铁票价按里程计费[1]」\n"
    "3. 即使上下文不完整，也根据已有信息回答你能回答的部分，标注不确定之处。只有当上下文确实完全不相关时，才说明\"知识库中未找到相关内容\"。\n"
    "4. 用户永远看不到 <thinking> 部分的内容\n"
    "5. <answer> 部分必须是完整、可直接展示的最终答案"
)

NO_CONTEXT_REPLY = "知识库中未找到相关内容。"


def _filter_thinking(text: str, state: dict) -> tuple[str, str]:
    """从流式文本中分离 <thinking> 和 <answer> 内容。
    返回 (think_text, visible_text) — 严格取标签内的文本，其余丢弃。
    所有模式均有前缀缓冲，防止标签被 chunk 拆散。
    多轮对话时 LLM 可能不输出标签（历史中 assistant 内容无标签），
    此时将全部内容作为 visible 输出。"""
    state.setdefault("buf", "")
    state.setdefault("mode", "idle")  # idle | think | answer
    state.setdefault("ever_tagged", False)  # 是否曾进入过 think/answer 模式
    buf = state["buf"] + text
    think_parts: list[str] = []
    out: list[str] = []

    def _is_prefix(s, tag):
        """s 是否以 tag 的前缀开头（忽略 s 开头的非 '<' 字符）"""
        lt = s.find("<")
        if lt == -1:
            return False
        rest = s[lt:]
        for n in range(1, len(tag)):
            if rest == tag[:n]:
                return True
        return False

    while buf:
        if state["mode"] == "think":
            idx = buf.find("</thinking>")
            if idx == -1:
                # 检查末尾是否可能是 </thinking> 的前缀
                tail = ""
                for n in range(len("</thinking>") - 1, 0, -1):
                    if buf.endswith("</thinking>"[:n]):
                        tail = buf[-n:]
                        break
                if tail:
                    think_parts.append(buf[:-len(tail)])
                    state["buf"] = tail
                else:
                    think_parts.append(buf)
                    state["buf"] = ""
                break
            think_parts.append(buf[:idx])
            buf = buf[idx + len("</thinking>"):]
            state["mode"] = "idle"
            state["buf"] = buf
        elif state["mode"] == "answer":
            idx = buf.find("</answer>")
            if idx == -1:
                tail = ""
                for n in range(len("</answer>") - 1, 0, -1):
                    if buf.endswith("</answer>"[:n]):
                        tail = buf[-n:]
                        break
                if tail:
                    out.append(buf[:-len(tail)])
                    state["buf"] = tail
                else:
                    out.append(buf)
                    state["buf"] = ""
                break
            out.append(buf[:idx])
            buf = buf[idx + len("</answer>"):]
            state["mode"] = "idle"
            state["buf"] = buf
        else:  # idle — 等待 <thinking> 或 <answer>
            idx_think = buf.find("<thinking>")
            idx_ans = buf.find("<answer>")
            if idx_think == -1 and idx_ans == -1:
                if _is_prefix(buf, "<thinking>") or _is_prefix(buf, "<answer>"):
                    state["buf"] = buf
                else:
                    # 丢弃标签外文字，但保留在 untagged 中以备兜底
                    state.setdefault("untagged", "")
                    state["untagged"] += buf
                    state["buf"] = ""
                break
            state["ever_tagged"] = True
            if idx_think != -1 and (idx_ans == -1 or idx_think < idx_ans):
                # 标签前可能有前缀文字，丢弃
                buf = buf[idx_think + len("<thinking>"):]
                state["mode"] = "think"
                state["buf"] = buf
            else:
                buf = buf[idx_ans + len("<answer>"):]
                state["mode"] = "answer"
                state["buf"] = buf

    # 兜底：从未匹配到任何标签，将累积的 untagged 内容作为 visible 输出
    if not state.get("ever_tagged") and state.get("untagged") and state.get("mode") == "idle":
        out.append(state.pop("untagged"))
        state["buf"] = ""

    return "".join(think_parts), "".join(out)


def _resolve_sources(chunks: list[dict]) -> list[dict]:
    """按 doc_id 去重并分配引用编号(首次出现顺序)，关联文件名和知识库名。"""
    order: list[int] = []
    by_doc: dict[int, dict] = {}
    name_cache: dict[int, str] = {}
    kb_cache: dict[int, str] = {}
    for c in chunks:
        did = c.get("doc_id")
        if did not in by_doc:
            if did not in name_cache:
                doc = db.get_document(did) if did is not None else None
                name_cache[did] = (doc or {}).get("filename") or f"文档#{did}"
            # kb_name 查找（带缓存）
            kid = c.get("kb_id")
            if kid is not None and kid not in kb_cache:
                basic = db.get_kb_basic(kid)
                kb_cache[kid] = basic["name"] if basic else f"KB#{kid}"
            by_doc[did] = {"cite": len(order) + 1, "doc_id": did,
                           "filename": name_cache[did], "chunk_ids": [],
                           "kb_id": kid,
                           "kb_name": kb_cache.get(kid) if kid is not None else None,
                           "rerank_score": c.get("rerank_score")}
            order.append(did)
        by_doc[did]["chunk_ids"].append(c.get("chunk_id"))
    return [by_doc[d] for d in order]


def _cite_labels(sources: list[dict], is_multi_kb: bool = False) -> list[str]:
    result: list[str] = []
    for s in sources:
        label = f"[{s['cite']}] {s['filename']}"
        if is_multi_kb and s.get("kb_name"):
            label += f" ({s['kb_name']})"
        result.append(label)
    return result


def _build_messages(query: str, chunks: list[dict], sources: list[dict],
                    history: list[dict] | None) -> list[dict]:
    """组 OpenAI 风格 messages：system → (历史) → 带编号上下文的 user。"""
    cite_of = {s["doc_id"]: s["cite"] for s in sources}
    parts = []
    for c in chunks:
        cite = cite_of.get(c.get("doc_id"))
        fname = next((s["filename"] for s in sources if s["doc_id"] == c.get("doc_id")), "")
        head = f"[{cite}] (来源文件：{fname})"
        # 去掉 chunk 文本中的 [filename] 前缀（来源标注已包含文件名，避免重复）
        text = c["text"]
        if fname:
            prefix = f"[{fname}]\n"
            if text.startswith(prefix):
                text = text[len(prefix):]
            prefix2 = f"[{fname}]"
            if text.startswith(prefix2):
                text = text[len(prefix2):]
        parts.append(head + "\n" + text)
    context = "\n\n".join(parts) if parts else "（无相关上下文）"
    user_content = f"【上下文】\n{context}\n\n【问题】\n{query}"

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        for m in history:
            if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip():
                messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": user_content})
    return messages


def _resolve_rerank(req_val: bool | None, kb_ids: list[int]) -> bool:
    if req_val is not None:
        return req_val
    # 单库时取该库配置，多库时默认开启
    if len(kb_ids) == 1:
        cfg = db.get_kb_config(kb_ids[0])
        if cfg is not None and cfg.get("rerank_enabled") is not None:
            return bool(cfg["rerank_enabled"])
    return True


def _resolve_rerank_mode(kb_ids: list[int]) -> str:
    """从知识库配置读取 rerank_mode，默认 fusion。"""
    if len(kb_ids) >= 1:
        cfg = db.get_kb_config(kb_ids[0])
        if cfg is not None:
            mode = cfg.get("rerank_mode")
            if mode in ("fusion", "llm"):
                return mode
    return "fusion"


def _persist_conversation(conv_id: int, query: str, answer: str, reasoning: str | None, sources_json: str):
    """在后台线程中保存对话记录，避免阻塞流式响应 [DONE] 发送。"""
    cstore.add_message(conv_id, "user", query)
    cstore.add_message(conv_id, "assistant", answer,
                       model=f"agent:{config.LLM_MODEL}", sources=sources_json,
                       thinking=reasoning or None)
    cstore.touch_conversation(conv_id)


def _safe_history(history: list[ChatMessage] | None) -> list[dict]:
    if not history:
        return []
    out = []
    for m in history:
        if m.role == "user" and safety.quick_check(m.content) is not None:
            logger.info("历史中剔除一条命中安全词的 user 轮次")
            continue
        out.append({"role": m.role, "content": m.content})
    return out


def _sse(text: str) -> str:
    safe = text.replace('\n', '\\n')
    return f"data: {safe}\n\n"


@router.post("/chat")
async def chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    # 解析目标库：kb_ids 优先，回退到 kb_id（向后兼容）
    if req.kb_ids:
        target_kb_ids = req.kb_ids
        is_multi = len(req.kb_ids) > 1
    elif req.kb_id is not None:
        target_kb_ids = [req.kb_id]
        is_multi = False
    else:
        target_kb_ids = []
        is_multi = False

    # RBAC：逐库校验 reader 权限
    rbac.require_kb_roles(user, target_kb_ids, "reader")

    # 安全配置取第一个库
    primary_kb = target_kb_ids[0] if target_kb_ids else 0
    kcfg = db.get_kb_config(primary_kb) or {}
    blocked, reason = await safety.is_blocked(
        req.query,
        word_check=kcfg.get("safety_enabled", True),
        use_llm=kcfg.get("safety_llm_check", False),
    )
    # 审计：记录问答（安全拦截的也记录）
    audit_target = req.query[:100]
    if is_multi:
        audit_target = f"[kbs:{','.join(str(i) for i in target_kb_ids)}] {audit_target}"
    astore.write_audit(action="chat", user_id=user["id"], username=user["username"],
                       kb_id=primary_kb, target=audit_target)
    if blocked:
        logger.warning("问答被安全拦截 kbs={} reason={}", target_kb_ids, reason)
        if req.stream:
            async def blocked_gen():
                yield _sse(config.SAFETY_BLOCK_REPLY)
                yield _sse("[DONE]")
            return StreamingResponse(blocked_gen(), media_type="text/event-stream")
        return success({"answer": config.SAFETY_BLOCK_REPLY, "sources": [],
                        "safety_blocked": True})

    # ── 对话记录：解析或新建 conversation ──
    kb_ids_str = ",".join(str(i) for i in target_kb_ids) if target_kb_ids else None
    conv_id = req.conversation_id
    if conv_id:
        conv = cstore.get_conversation(conv_id)
        if conv is None or conv["user_id"] != user["id"]:
            conv_id = cstore.create_conversation(user["id"], kb_ids_str, req.query[:80])
        # else: 继续已有对话
    else:
        conv_id = cstore.create_conversation(user["id"], kb_ids_str, req.query[:80])

    do_rerank = _resolve_rerank(req.rerank_enabled, target_kb_ids)
    rerank_mode = _resolve_rerank_mode(target_kb_ids)
    model_id = req.llm_model if req.llm_model is not None else req.model
    model_name = db.get_model_name(model_id) if model_id is not None else None
    logger.info("chat kbs={} model_id={} -> name={} rerank={} mode={} conv_id={} [v2: top_k=15]",
                target_kb_ids, model_id, model_name, do_rerank, rerank_mode, conv_id)

    history = _safe_history(req.history)
    # 如果前端没传 history 但有 conversation_id，从 DB 加载最近历史
    if not history and req.conversation_id:
        history = cstore.get_recent_history(conv_id)
    search_query = await query_rewriter.rewrite(req.query, history)

    # ── Query Enhancement + Unified Retrieval（新） ──
    from backend.retrieval.query_enhancer import enhance_query
    from backend.retrieval.unified_retrieval import unified_retrieve, RetrievalRequest

    enhanced = await enhance_query(search_query, history)
    retrieval_result = await unified_retrieve(RetrievalRequest(
        queries=enhanced.sub_queries,
        kb_ids=target_kb_ids,
        rerank_mode=rerank_mode,
        do_rerank=do_rerank,
        dense_weight=enhanced.dense_weight,
        sparse_weight=enhanced.sparse_weight,
        hyde_embedding=enhanced.hyde_embedding,
    ))
    chunks = retrieval_result.chunks

    if not chunks:
        logger.info("召回为空，直接拒答 kbs={} query={!r}", target_kb_ids, search_query)
        # 保存对话记录（用户问题 + 拒答）
        cstore.add_message(conv_id, "user", req.query)
        cstore.add_message(conv_id, "assistant", NO_CONTEXT_REPLY)
        cstore.touch_conversation(conv_id)
        if req.stream:
            async def empty_gen():
                yield _sse(NO_CONTEXT_REPLY)
                yield _sse("[CONV_ID]" + str(conv_id))
                yield _sse("[DONE]")
            return StreamingResponse(empty_gen(), media_type="text/event-stream")
        return success({"answer": NO_CONTEXT_REPLY, "sources": [],
                        "conversation_id": conv_id})

    sources = _resolve_sources(chunks)
    messages = _build_messages(req.query, chunks, sources, history)
    # 调试：记录完整上下文（可在 logs/ 中查看 LLM 实际收到了什么）
    logger.info("LLM 上下文: 共 {} 个 chunk，来自 {} 个文件\n{}",
                len(chunks), len(sources),
                messages[-1]["content"] if messages else "")

    if req.stream:
        labels = _cite_labels(sources, is_multi_kb=is_multi)

        async def sse_generator():
            token_count = 0
            think_buf: list[str] = []
            full_answer_parts: list[str] = []  # 累积完整回答，用于存库
            filter_state: dict = {}
            think_sent = False
            is_qwen = "qwen" in (model_name or "").lower()
            if req.thinking:
                yield _sse("__THINKING_ON__")
            try:
                if is_qwen:
                    # Qwen: 输出全在 model_extra["reasoning"]，用 stream() 合并 → _filter_thinking 分离
                    async for text in llm_client.stream(
                        messages, model=model_name,
                        max_tokens=config.LLM_ANSWER_MAX_TOKENS,
                        thinking=req.thinking,
                    ):
                        think_part, visible = _filter_thinking(text, filter_state)
                        if req.thinking and think_part:
                            think_buf.append(think_part)
                        if visible:
                            if req.thinking and not think_sent and think_buf:
                                yield _sse("__THINK__:" + "".join(think_buf))
                                think_sent = True
                            yield _sse(visible)
                            full_answer_parts.append(visible)
                            token_count += 1
                else:
                    # DeepSeek: stream_with_thinking + _filter_thinking
                    async for kind, text in llm_client.stream_with_thinking(
                        messages, model=model_name,
                        max_tokens=config.LLM_ANSWER_MAX_TOKENS,
                        thinking=req.thinking,
                    ):
                        if kind == "think":
                            if not req.thinking:
                                continue
                            think_buf.append(text)
                            continue
                        think_part, visible = _filter_thinking(text, filter_state)
                        if req.thinking and think_part:
                            think_buf.append(think_part)
                        if visible:
                            if req.thinking and not think_sent and think_buf:
                                yield _sse("__THINK__:" + "".join(think_buf))
                                think_sent = True
                            yield _sse(visible)
                            full_answer_parts.append(visible)
                            token_count += 1

                # 流结束 — 处理 filter_state 残留
                think_part, leftover = _filter_thinking("", filter_state)
                if req.thinking and think_part:
                    think_buf.append(think_part)
                if req.thinking and not think_sent and think_buf:
                    yield _sse("__THINK__:" + "".join(think_buf))
                    think_sent = True
                if leftover:
                    yield _sse(leftover)
                    full_answer_parts.append(leftover)
                    token_count += 1

                if token_count == 0 and think_buf:
                    fallback = "".join(think_buf)
                    logger.info("兜底使用 thinking 内容, {} 字", len(fallback))
                    yield _sse(fallback)
                    full_answer_parts.append(fallback)

                # ── 保存对话记录 ──
                final_answer = "".join(full_answer_parts)
                thinking_str = "".join(think_buf) if think_buf else None
                sources_json = json.dumps(labels, ensure_ascii=False)
                cstore.add_message(conv_id, "user", req.query)
                cstore.add_message(conv_id, "assistant", final_answer,
                                   model=model_name, sources=sources_json,
                                   thinking=thinking_str)
                cstore.touch_conversation(conv_id)
                yield _sse("[CONV_ID]" + str(conv_id))
                yield _sse("[SOURCES]" + json.dumps(labels, ensure_ascii=False))
            except Exception as e:
                logger.exception("流式生成异常: {}", e)
                yield _sse(f"[ERROR] {e}")
            if token_count == 0:
                yield _sse(NO_CONTEXT_REPLY)
            yield _sse("[DONE]")

        return StreamingResponse(sse_generator(), media_type="text/event-stream")

    answer, api_reasoning = await llm_client.chat(messages, model=model_name,
                                                   max_tokens=config.LLM_ANSWER_MAX_TOKENS,
                                                   thinking=req.thinking)
    # 提取思考内容：优先用 API 级 reasoning，其次从 <thinking> 标签提取
    thinking_content = api_reasoning if req.thinking else ""
    if not thinking_content:
        think_part, answer = _filter_thinking(answer, {})
        if think_part:
            thinking_content = think_part
    else:
        _, answer = _filter_thinking(answer, {})
    # ── 保存对话记录 ──
    sources_json = json.dumps(sources, ensure_ascii=False, default=str)
    cstore.add_message(conv_id, "user", req.query)
    cstore.add_message(conv_id, "assistant", answer,
                       model=model_name, sources=sources_json,
                       thinking=thinking_content or None)
    cstore.touch_conversation(conv_id)
    result_data = {"answer": answer, "sources": sources, "conversation_id": conv_id}
    if thinking_content:
        result_data["thinking"] = thinking_content
    return success(result_data)


# ═══════════════════════════════════════════════════════════════════════════════
# Agentic RAG 端点（LangGraph）
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/chat/agent")
async def agent_chat(req: AgentChatRequest, user: dict = Depends(get_current_user)):
    """Agentic RAG 问答端点。

    与 /api/chat 并行存在。Agent 图内 LLM 自主决定检索策略：
      Planner → Searcher → Generator → Verifier（可循环回溯 Searcher）
    """
    # ── 解析目标库 ──
    if req.kb_ids:
        target_kb_ids = req.kb_ids
        is_multi = len(req.kb_ids) > 1
    elif req.kb_id is not None:
        target_kb_ids = [req.kb_id]
        is_multi = False
    else:
        target_kb_ids = []
        is_multi = False

    # ── RBAC ──
    rbac.require_kb_roles(user, target_kb_ids, "reader")

    # ── 安全 ──
    primary_kb = target_kb_ids[0] if target_kb_ids else 0
    kcfg = db.get_kb_config(primary_kb) or {}
    blocked, reason = await safety.is_blocked(
        req.query,
        word_check=kcfg.get("safety_enabled", True),
        use_llm=kcfg.get("safety_llm_check", False),
    )
    astore.write_audit(action="agent_chat", user_id=user["id"], username=user["username"],
                       kb_id=primary_kb, target=req.query[:100])
    if blocked:
        logger.warning("Agent 问答被安全拦截 kbs={} reason={}", target_kb_ids, reason)
        if req.stream:
            async def blocked_gen():
                yield _sse(config.SAFETY_BLOCK_REPLY)
                yield _sse("[DONE]")
            return StreamingResponse(blocked_gen(), media_type="text/event-stream")
        return success({"answer": config.SAFETY_BLOCK_REPLY, "sources": [],
                        "safety_blocked": True})

    # ── 对话记录 ──
    kb_ids_str = ",".join(str(i) for i in target_kb_ids) if target_kb_ids else None
    conv_id = req.conversation_id
    if conv_id:
        conv = cstore.get_conversation(conv_id)
        if conv is None or conv["user_id"] != user["id"]:
            conv_id = cstore.create_conversation(user["id"], kb_ids_str, req.query[:80])
    else:
        conv_id = cstore.create_conversation(user["id"], kb_ids_str, req.query[:80])

    # ── 构建初始状态 ──
    history = _safe_history(req.history)
    if not history and req.conversation_id:
        history = cstore.get_recent_history(conv_id)

    initial_state: AgentState = {
        "query": req.query,
        "kb_ids": target_kb_ids,
        "history": history or [],
    }
    logger.info("agent_chat kbs={} conv_id={} query={!r}", target_kb_ids, conv_id, req.query[:80])

    # ── 非流式 ──
    if not req.stream:
        try:
            result = await agent_graph.ainvoke(initial_state)
        except Exception as exc:
            logger.exception("Agent 图执行异常: {}", exc)
            return success({"answer": f"Agent 执行出错: {exc}", "sources": [],
                            "conversation_id": conv_id, "agent_error": True})

        answer = result.get("answer") or ""
        chunks = result.get("chunks") or []
        reasoning = result.get("reasoning") or ""
        sources = _resolve_sources(chunks) if chunks else []
        labels = _cite_labels(sources, is_multi_kb=is_multi)

        # 保存对话
        sources_json = json.dumps(labels, ensure_ascii=False)
        cstore.add_message(conv_id, "user", req.query)
        cstore.add_message(conv_id, "assistant", answer,
                           model=f"agent:{config.LLM_MODEL}", sources=sources_json,
                           thinking=reasoning or None)
        cstore.touch_conversation(conv_id)

        result_data = {"answer": answer, "sources": sources, "conversation_id": conv_id}
        if reasoning:
            result_data["reasoning"] = reasoning
        passed = result.get("passed")
        if passed is not None:
            result_data["verified"] = passed
        issues = result.get("issues")
        if issues:
            result_data["issues"] = issues
        feedback = result.get("verifier_feedback")
        if feedback:
            result_data["verifier_feedback"] = feedback
        return success(result_data)

    # ── 流式 ──
    async def agent_sse_generator():
        full_answer = ""
        full_reasoning = ""
        all_chunks: list[dict] = []
        verified = None
        issues_list: list[str] = []

        try:
            async for chunk in agent_graph.astream(initial_state):
                node_name = next(iter(chunk.keys()))
                node_output = chunk[node_name]

                if node_name == "planner":
                    reasoning = node_output.get("reasoning") or ""
                    queries = node_output.get("search_queries") or []
                    full_reasoning = reasoning
                    # 思考模式：发送 Planner 推理过程
                    if req.thinking and reasoning:
                        yield _sse("__THINKING_ON__")
                        yield _sse(f"__THINK__:{reasoning}")
                    yield _sse("[PLANNER]" + json.dumps({
                        "reasoning": reasoning,
                        "queries": queries,
                    }, ensure_ascii=False))
                    if not queries:
                        yield _sse("[INFO]问题无需检索，直接回答")

                elif node_name == "searcher":
                    chunks_found = node_output.get("chunks") or []
                    all_chunks = chunks_found
                    yield _sse("[SEARCHER]" + json.dumps({
                        "chunks_found": len(chunks_found),
                        "context_len": len(node_output.get("context") or ""),
                    }, ensure_ascii=False))

                elif node_name == "generator":
                    answer_text = node_output.get("answer") or ""
                    full_answer = answer_text
                    # 分成小段推送，模拟流式效果
                    chunk_size = 60
                    for i in range(0, len(answer_text), chunk_size):
                        yield _sse(answer_text[i:i + chunk_size])

                elif node_name == "verifier":
                    verified = node_output.get("passed")
                    issues_list = node_output.get("issues") or []
                    yield _sse("[VERIFIER]" + json.dumps({
                        "passed": verified,
                        "issues": issues_list,
                        "iteration": node_output.get("iteration", 0),
                    }, ensure_ascii=False))

            # ── 保存对话（在 yield [DONE] 之前异步写入，避免前端等待）──
            sources = _resolve_sources(all_chunks) if all_chunks else []
            labels = _cite_labels(sources, is_multi_kb=is_multi)
            sources_json = json.dumps(labels, ensure_ascii=False)
            import asyncio as _asyncio
            _asyncio.ensure_future(_asyncio.to_thread(_persist_conversation, conv_id, req.query, full_answer, full_reasoning, sources_json))

            yield _sse("[CONV_ID]" + str(conv_id))
            yield _sse("[SOURCES]" + json.dumps(labels, ensure_ascii=False))
            if verified is not None:
                yield _sse("[VERIFIED]" + json.dumps({
                    "passed": verified,
                    "issues": issues_list,
                }, ensure_ascii=False))

        except Exception as exc:
            logger.exception("Agent 流式执行异常: {}", exc)
            yield _sse(f"[ERROR] {exc}")

        yield _sse("[DONE]")

    return StreamingResponse(agent_sse_generator(), media_type="text/event-stream")


# ── Time Travel / Checkpoint 回溯 API ──

@router.get("/chat/agent/{conv_id}/timeline")
def agent_timeline(conv_id: int, user: dict = Depends(get_current_user)):
    """查看 Agent 执行时间线。

    返回每一步的状态快照列表，包含节点名、输入输出、时间戳。
    需要 checkpoint 支持。
    """
    conv = cstore.get_conversation(conv_id)
    if conv is None or conv["user_id"] != user["id"]:
        return success({"error": "对话不存在或无权访问", "timeline": []})

    try:
        from backend.agent.checkpoint import get_checkpointer
        checkpointer = get_checkpointer()
        config = {"configurable": {"thread_id": str(conv_id)}}
        states = list(checkpointer.list(config))
        if not states:
            return success({"timeline": [], "note": "该对话无 Agent 执行记录（可能未使用 agent 模式或未启用 checkpoint）"})
        timeline = []
        for s in states:
            meta = getattr(s, "metadata", None) or {}
            checkpoint = getattr(s, "checkpoint", None) or {}
            timeline.append({
                "checkpoint_id": getattr(s, "id", None),
                "step": meta.get("step"),
                "source": meta.get("source"),
                "timestamp": str(meta.get("timestamp", "")),
            })
        return success({"conv_id": conv_id, "timeline": timeline})
    except Exception as exc:
        logger.warning("获取 Agent timeline 失败 conv_id={}: {}", conv_id, exc)
        return success({"error": str(exc), "timeline": []})


@router.get("/chat/agent/{conv_id}/state")
def agent_state(conv_id: int, user: dict = Depends(get_current_user)):
    """查看 Agent 当前状态快照。"""
    conv = cstore.get_conversation(conv_id)
    if conv is None or conv["user_id"] != user["id"]:
        return success({"error": "对话不存在或无权访问"})

    try:
        from backend.agent.checkpoint import get_checkpointer
        checkpointer = get_checkpointer()
        config = {"configurable": {"thread_id": str(conv_id)}}
        state = agent_graph.get_state(config)
        if state is None:
            return success({"state": None, "note": "无 checkpoint 记录"})
        values = getattr(state, "values", None) or {}
        # 只返回前端关心的字段
        return success({
            "conv_id": conv_id,
            "state": {
                "query": values.get("query"),
                "search_queries": values.get("search_queries"),
                "reasoning": values.get("reasoning"),
                "answer": values.get("answer"),
                "passed": values.get("passed"),
                "issues": values.get("issues"),
                "iteration": values.get("iteration"),
                "context_len": len(values.get("context") or ""),
                "chunks_count": len(values.get("chunks") or []),
            },
        })
    except Exception as exc:
        logger.warning("获取 Agent state 失败 conv_id={}: {}", conv_id, exc)
        return success({"error": str(exc)})


@router.post("/chat/agent/{conv_id}/replay")
async def agent_replay(conv_id: int,
                       checkpoint_id: str | None = None,
                       user: dict = Depends(get_current_user)):
    """从指定 checkpoint 重新执行 Agent。

    传入 checkpoint_id 则从该 checkpoint 分叉；
    不传则从最新状态继续（若 Verifier 未通过）。
    """
    conv = cstore.get_conversation(conv_id)
    if conv is None or conv["user_id"] != user["id"]:
        return success({"error": "对话不存在或无权访问"})

    try:
        from backend.agent.checkpoint import get_checkpointer
        checkpointer = get_checkpointer()

        # 重建带 checkpoint 的图
        from backend.agent.graph import compile_graph
        graph_with_cp = compile_graph(checkpointer=checkpointer)

        config = {"configurable": {"thread_id": str(conv_id)}}

        if checkpoint_id:
            # 从指定 checkpoint 恢复状态
            state_snapshot = graph_with_cp.get_state(config)
            if state_snapshot is None:
                return success({"error": "未找到 checkpoint 记录"})
            # 从该 checkpoint 继续执行
            result = await graph_with_cp.ainvoke(None, config=config)
        else:
            # 从最新状态继续
            state_snapshot = graph_with_cp.get_state(config)
            if state_snapshot is None:
                return success({"error": "无 checkpoint 记录，请先发起一次 agent 问答"})
            result = await graph_with_cp.ainvoke(None, config=config)

        answer = result.get("answer") or ""
        chunks = result.get("chunks") or []
        sources = _resolve_sources(chunks) if chunks else []

        return success({
            "conv_id": conv_id,
            "answer": answer,
            "sources": sources,
            "reasoning": result.get("reasoning"),
            "passed": result.get("passed"),
            "issues": result.get("issues"),
        })
    except Exception as exc:
        logger.exception("Agent replay 失败 conv_id={}: {}", conv_id, exc)
        return success({"error": str(exc)})
