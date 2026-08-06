"""知识库管理接口：创建 / 列表 / 删除（级联清 Milvus）。
DB 走同步路线，接口用 def；RBAC 两轴判定见 core/rbac.py。
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from loguru import logger
import asyncio
from backend.store import mysql_store as db
from backend.store import milvus_store
from backend.store import auth_store as astore
from backend.core.response import success, fail
from backend.core.deps import get_current_user, get_client_ip
from backend.core import rbac
from backend.core import embedding_client

router = APIRouter(prefix="/api/kb", tags=["knowledge_base"])


class CreateKBRequest(BaseModel):
    name: str
    description: str = ""
    # 分段
    chunk_size: int = 500
    overlap: int = 50
    chunk_method: str = "recursive"
    # 检索
    retrieval_mode: str = "hybrid"
    recall_k: int = 20
    top_k: int = 5
    rerank_mode: str = "fusion"
    # 模型（None=走服务端默认）
    llm_model: str | None = None
    # 安全
    safety_enabled: bool = True
    safety_llm_check: bool = False


@router.post("")
def create_kb(req: CreateKBRequest, request: Request, user: dict = Depends(get_current_user)):
    rbac.require_global(user, "user")                 # guest 不能建库
    kb_id = db.create_kb(req.name, req.description)
    astore.add_kb_member(kb_id, user["id"], "owner")  # 创建者即 owner
    db.create_kb_config(kb_id,
                        chunk_size=req.chunk_size,
                        overlap=req.overlap,
                        chunk_method=req.chunk_method,
                        retrieval_mode=req.retrieval_mode,
                        recall_k=req.recall_k,
                        top_k=req.top_k,
                        rerank_mode=req.rerank_mode,
                        llm_model=req.llm_model,
                        safety_enabled=req.safety_enabled,
                        safety_llm_check=req.safety_llm_check)
    astore.write_audit(action="create_kb", user_id=user["id"], username=user["username"],
                       kb_id=kb_id, target="kb:"+str(kb_id), ip=get_client_ip(request))
    logger.info("用户 {} 创建 kb={} 并成为 owner", user["username"], kb_id)
    return success({"id": kb_id})


def _attach_role(kb_list: list[dict], user: dict) -> list[dict]:
    """给每个 kb 附加当前用户的资源角色（前端 kbRoleCache 据此判上传/删除权限）。
    super_admin 全标 owner；其余按 kb_member 查，无角色为 None。"""
    is_super = user["role"] == "super_admin"
    out = []
    for kb in kb_list:
        item = dict(kb)
        item["role"] = "owner" if is_super else astore.get_kb_role(kb["id"], user["id"])
        out.append(item)
    return out


@router.get("")
def list_kb(user: dict = Depends(get_current_user)):
    all_kb = db.list_kb()
    if user["role"] == "super_admin":
        kbs = all_kb
    else:
        visible = set(astore.list_visible_kb_ids(user["id"]))
        kbs = [k for k in all_kb if k["id"] in visible]
    owners = astore.get_kb_owners([k["id"] for k in kbs])
    for k in kbs:
        k["owner_username"] = owners.get(k["id"])
    return success(_attach_role(kbs, user))


@router.delete("/{kb_id}")
def delete_kb(kb_id: int, request: Request, user: dict = Depends(get_current_user)):
    rbac.require_kb_role(user, kb_id, "owner")        # 需 owner（super_admin 放行）
    docs = db.list_documents(kb_id)
    logger.info("用户 {} 删除 kb={}，级联 {} 个文档", user["username"], kb_id, len(docs))
    milvus_store.delete(filter_expr=f"kb_id == {kb_id}")
    for d in docs:
        db.delete_document(d["id"])
    n = db.delete_kb(kb_id)
    astore.write_audit(action="delete_kb", user_id=user["id"], username=user["username"],
                       kb_id=kb_id, target="kb:"+str(kb_id), ip=get_client_ip(request))
    return success({"deleted_kb": n, "deleted_docs": len(docs)})


@router.get("/{kb_id}/stats")
def kb_stats(kb_id: int, user: dict = Depends(get_current_user)):
    rbac.require_kb_role(user, kb_id, "reader")       # 概览统计需 reader
    return success({
        "doc_count":    db.count_documents(kb_id),
        "chunk_count":  db.count_chunks(kb_id),
        "member_count": len(astore.list_kb_members(kb_id)),
        "size_bytes":   db.sum_chunk_bytes(kb_id),
    })


class UpdateSettingsRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    chunk_size: int | None = None
    overlap: int | None = None
    chunk_method: str | None = None
    retrieval_mode: str | None = None
    recall_k: int | None = None
    top_k: int | None = None
    rerank_enabled: bool | None = None
    rerank_top_n: int | None = None
    score_threshold: float | None = None
    ocr_enabled: bool | None = None
    table_parse_enabled: bool | None = None
    formula_parse_enabled: bool | None = None
    llm_model: str | None = None
    rerank_model: str | None = None
    safety_enabled: bool | None = None
    safety_llm_check: bool | None = None
    rerank_mode: str | None = None                         # fusion | llm
    # 注意：故意不收 embedding_model（已锁定，服务端拒改）


def _assemble_settings(kb_id: int) -> dict | None:
    basic = db.get_kb_basic(kb_id)
    cfg = db.get_kb_config(kb_id)
    if basic is None or cfg is None:
        return None
    return {**basic, **cfg, "embedding_locked": True}


@router.get("/{kb_id}/settings")
def get_settings(kb_id: int, user: dict = Depends(get_current_user)):
    rbac.require_kb_role(user, kb_id, "reader")       # 看配置需 reader
    data = _assemble_settings(kb_id)
    if data is None:
        return fail(code=404, msg="知识库或配置不存在")
    return success(data)


@router.put("/{kb_id}/settings")
def put_settings(kb_id: int, req: UpdateSettingsRequest, request: Request,
                 user: dict = Depends(get_current_user)):
    rbac.require_kb_role(user, kb_id, "owner")        # 改配置需 owner
    body = req.model_dump(exclude_unset=True)         # 只取前端真正传了的字段
    if "description" in body:
        db.update_kb_description(kb_id, body["description"])
    db.update_kb_config(kb_id, body)                  # 内部过滤 embedding_model + 未知键
    data = _assemble_settings(kb_id)
    if data is None:
        return fail(code=404, msg="知识库或配置不存在")
    astore.write_audit(action="update_settings", user_id=user["id"], username=user["username"],
                       kb_id=kb_id, target="kb:"+str(kb_id), ip=get_client_ip(request))
    # 安全配置变更单独记录审计（关闭安全过滤属于高风险操作）
    if "safety_enabled" in body or "safety_llm_check" in body:
        detail = []
        if "safety_enabled" in body:
            detail.append("词库过滤=" + ("开" if body["safety_enabled"] else "关"))
        if "safety_llm_check" in body:
            detail.append("LLM审查=" + ("开" if body["safety_llm_check"] else "关"))
        astore.write_audit(action="safety_config", user_id=user["id"], username=user["username"],
                           kb_id=kb_id, target="; ".join(detail), ip=get_client_ip(request))
        logger.warning("用户 {} 修改 kb={} 安全配置: {}", user["username"], kb_id, detail)
    logger.info("用户 {} 更新 kb={} 配置: {}", user["username"], kb_id, list(body))
    return success(data)


CHUNK_METHODS = [
    {"value": "fixed", "label": "固定大小", "desc": "按字符数硬切 + 重叠。简单可靠，适合通用文本，但可能在句子中间断开。"},
    {"value": "recursive", "label": "递归切分", "desc": "优先段落→句子→逗号逐级回退。比固定大小更智能，生成的 chunk 语义更完整。"},
    {"value": "markdown", "label": "Markdown 标题感知", "desc": "按 # 标题层级切分，保留标题路径。适合结构化的笔记、文档、技术手册。"},
    {"value": "semantic", "label": "语义切分", "desc": "用 embedding 计算相邻句子相似度，在「意思变了」的地方断开。chunk 数量少但检索精度高。注意：入库较慢（需额外 embedding 调用）。"},
    {"value": "sentence_window", "label": "句子窗口", "desc": "每条句子独立成块，检索时附带前后句做上下文窗口。细粒度匹配，给 LLM 的上下文更聚焦。"},
    {"value": "speaker", "label": "说话人切分", "desc": "按 [说话人N] 或 [SpeakerN] 标记分段。适合会议录音、访谈、多人对话。需配合支持说话人标注的 ASR 引擎。（目前仅 Qwen ASR 支持，通过 prompt 标注）"},
]


@router.get("/chunk-methods")
def list_chunk_methods(user: dict = Depends(get_current_user)):
    """返回可用切分方式列表（含描述，供前端下拉选择）。"""
    return success(CHUNK_METHODS)


class SimilarRequest(BaseModel):
    text: str | None = None
    doc_id: int | None = None


_SIM_QUERY_MAXLEN = 2000   # 送 embedding 的查询文本上限，doc 模式拼 chunk 时截断


def _resolve_similar_query(req: "SimilarRequest") -> tuple[str | None, int | None]:
    """定出查询文本与待排除的源 doc。text 优先；否则用 doc_id 的 chunk 拼出文本。
    返回 (query_text, exclude_doc_id)；query_text 为 None 表示无有效输入。"""
    if req.text and req.text.strip():
        return req.text.strip()[:_SIM_QUERY_MAXLEN], None
    if req.doc_id is not None:
        chunks = db.get_chunks(req.doc_id)
        if not chunks:
            return None, req.doc_id
        joined = "\n".join(c["content"] for c in chunks)
        return joined[:_SIM_QUERY_MAXLEN], req.doc_id
    return None, None


@router.post("/{kb_id}/similar")
def similar(kb_id: int, req: SimilarRequest, user: dict = Depends(get_current_user)):
    rbac.require_kb_role(user, kb_id, "reader")       # 进门需当前库 reader

    query_text, exclude_doc_id = _resolve_similar_query(req)
    if not query_text:
        return fail(code=400, msg="请提供 text 或有效的 doc_id")

    # 可见库范围：super_admin 不限；其余取自己有成员关系的库
    if user["role"] == "super_admin":
        kb_ids = None
    else:
        kb_ids = astore.list_visible_kb_ids(user["id"])

    qv = asyncio.run(embedding_client.embed_one(query_text))
    hits = milvus_store.search_similar(qv, kb_ids=kb_ids,
                                       exclude_doc_id=exclude_doc_id, top_k=30)

    # doc 级聚合：每个 doc 取最高分 chunk（hits 已按分降序，首见即最高）
    best: dict[int, dict] = {}
    for h in hits:
        if h["doc_id"] not in best:
            best[h["doc_id"]] = h
    ranked = sorted(best.values(), key=lambda x: x["score"], reverse=True)[:10]

    # enrich：doc_name / kb_name（小表，逐条查；带缓存避免重复查同一个 kb）
    kb_name_cache: dict[int, str] = {}
    def _kb_name(kid: int) -> str:
        if kid not in kb_name_cache:
            basic = db.get_kb_basic(kid)
            kb_name_cache[kid] = basic["name"] if basic else ""
        return kb_name_cache[kid]

    data = []
    for h in ranked:
        doc = db.get_document(h["doc_id"])
        data.append({
            "doc_id":   h["doc_id"],
            "doc_name": doc["filename"] if doc else "(已删除)",
            "kb_id":    h["kb_id"],
            "kb_name":  _kb_name(h["kb_id"]),
            "similarity": round(float(h["score"]), 4),
            "snippet":  h["text"][:160],
            "highlight_range": None,
        })

    logger.info("用户 {} 找相似 kb={} → 返回 {} 个 doc", user["username"], kb_id, len(data))
    return success(data)
