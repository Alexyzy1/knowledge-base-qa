import json
from datetime import datetime
from sqlalchemy import (String, Text, Integer, BigInteger,
                        Float, Boolean, DateTime, func, select, update, delete)
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column)
from loguru import logger
from backend.store.engine import engine, SessionLocal
from backend import config


class Base(DeclarativeBase):
    pass


class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"
    __table_args__ = {"mysql_charset": "utf8mb4"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Document(Base):
    __tablename__ = "document"
    __table_args__ = {"mysql_charset": "utf8mb4"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(BigInteger, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(50), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    storage_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    folder_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Folder(Base):
    __tablename__ = "folder"
    __table_args__ = {"mysql_charset": "utf8mb4"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(255))
    parent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Chunk(Base):
    __tablename__ = "chunk"
    __table_args__ = {"mysql_charset": "utf8mb4"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    doc_id: Mapped[int] = mapped_column(BigInteger, index=True)
    kb_id: Mapped[int] = mapped_column(BigInteger, index=True)
    content: Mapped[str] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column(Integer)
    milvus_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


def init_tables():
    Base.metadata.create_all(engine)
    logger.info("MySQL 表已就绪: {}", list(Base.metadata.tables))


def create_kb(name: str, description: str = "") -> int:
    with SessionLocal() as s:
        kb = KnowledgeBase(name=name, description=description)
        s.add(kb); s.flush(); kb_id = kb.id; s.commit()
    logger.info("创建 knowledge_base id={} name={}", kb_id, name)
    return kb_id


def list_kb() -> list[dict]:
    with SessionLocal() as s:
        rows = s.execute(select(KnowledgeBase).order_by(KnowledgeBase.id)).scalars().all()
        return [{"id": k.id, "name": k.name, "description": k.description,
                 "created_at": k.created_at.isoformat() if k.created_at else None} for k in rows]


def create_document(kb_id: int, filename: str, status: str = "pending",
                    uploaded_by: str | None = None,
                    uploaded_at: datetime | None = None,
                    folder_id: int | None = None) -> int:
    with SessionLocal() as s:
        doc = Document(kb_id=kb_id, filename=filename, status=status,
                       uploaded_by=uploaded_by, uploaded_at=uploaded_at,
                       folder_id=folder_id)
        s.add(doc); s.flush(); doc_id = doc.id; s.commit()
    logger.info("创建 document id={} kb_id={} status={} folder_id={}", doc_id, kb_id, status, folder_id)
    return doc_id


def search_documents_by_filename(kb_ids: list[int], query: str) -> list[int]:
    """根据查询关键词在文件名中模糊匹配，返回匹配的 doc_id 列表（按匹配度排序）。
    用于两阶段检索：先定位相关文件，再定向检索文件内容。"""
    if not kb_ids or not query.strip():
        return []
    # 把查询拆成单词，每个词单独 LIKE 匹配
    words = [w.strip() for w in query.split() if len(w.strip()) >= 1]
    if not words:
        return []
    with SessionLocal() as s:
        from sqlalchemy import or_, and_
        conditions = [Document.filename.like(f"%{w}%") for w in words[:6]]  # 最多 6 个词
        # 匹配词数越多越靠前（简单评分）
        stmt = (
            select(Document.id, Document.filename)
            .where(Document.kb_id.in_(kb_ids))
            .where(or_(*conditions))
            .where(Document.status == "done")
        )
        rows = s.execute(stmt).all()
    # 按匹配词数降序排列
    scored = []
    for doc_id, fname in rows:
        score = sum(1 for w in words if w.lower() in (fname or "").lower())
        scored.append((score, doc_id))
    scored.sort(key=lambda x: x[0], reverse=True)
    doc_ids = [did for _, did in scored]
    logger.info("文件名搜索 kb_ids={} query={!r} → {} 个匹配文档", kb_ids, query[:60], len(doc_ids))
    return doc_ids


def update_document_status(doc_id: int, status: str):
    with SessionLocal() as s:
        s.execute(update(Document).where(Document.id == doc_id).values(status=status))
        s.commit()
    logger.info("document id={} 状态 → {}", doc_id, status)


def reset_stuck_documents() -> list[int]:
    """启动恢复：将卡在 processing 的文档重置为 failed。
    同时将关联的 queued/processing 任务也标记为 failed。

    服务器重启/崩溃时 BackgroundTasks 中的入库任务会丢失，
    文档永久卡在 processing；此函数在 lifespan 启动阶段调用，使其可被重试。
    返回被重置的 doc_id 列表。"""
    with SessionLocal() as s:
        # 查询所有卡住的文档
        stuck_docs = s.execute(
            select(Document.id).where(Document.status == "processing")
        ).scalars().all()
        doc_ids = list(stuck_docs)
        if doc_ids:
            # 清理孤儿 chunk（入库中途崩溃时 MySQL 已写 chunk 但 Milvus 未写）
            chunk_count = 0
            for did in doc_ids:
                n = s.execute(delete(Chunk).where(Chunk.doc_id == did)).rowcount
                chunk_count += n
            if chunk_count:
                logger.info("启动恢复：清理 {} 个孤儿 chunk ({} 个文档)", chunk_count, len(doc_ids))

            s.execute(
                update(Document).where(Document.id.in_(doc_ids)).values(status="failed")
            )
            # 同时把关联的未完成任务也标记为 failed
            s.execute(
                update(Task).where(
                    Task.doc_id.in_(doc_ids),
                    Task.status.in_(["queued", "processing"]),
                ).values(status="failed", error_msg="服务器重启，任务中断")
            )
            s.commit()
        return doc_ids


def get_document(doc_id: int) -> dict | None:
    with SessionLocal() as s:
        d = s.get(Document, doc_id)
        return None if d is None else {"id": d.id, "kb_id": d.kb_id,
                                       "filename": d.filename, "status": d.status,
                                       "file_size": d.size,
                                       "storage_path": d.storage_path,
                                       "folder_id": d.folder_id,
                                       "uploaded_by": d.uploaded_by,
                                       "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
                                       "tags": _load_tags(d.tags)}


def list_documents(kb_id: int, tag: str | None = None,
                   folder_id: int | None = None) -> list[dict]:
    with SessionLocal() as s:
        stmt = select(Document).where(Document.kb_id == kb_id)
        if folder_id is not None:
            stmt = stmt.where(Document.folder_id == folder_id)
        rows = s.execute(stmt.order_by(Document.id)).scalars().all()
        out = []
        for d in rows:
            tags = _load_tags(d.tags)
            if tag is not None and tag not in tags:   # 应用层过滤
                continue
            out.append({"id": d.id, "filename": d.filename, "status": d.status,
                        "tags": tags, "folder_id": d.folder_id,
                        "file_size": d.size,
                        "storage_path": d.storage_path,
                        "uploaded_by": d.uploaded_by,
                        "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None})
        return out


def delete_chunks_by_doc_id(doc_id: int) -> int:
    """仅删 chunk 行（入库回滚用，不删 document 本身）。"""
    with SessionLocal() as s:
        n = s.execute(delete(Chunk).where(Chunk.doc_id == doc_id)).rowcount
        s.commit()
    logger.info("MySQL 回滚删除 chunk doc_id={} 共 {} 条", doc_id, n)
    return n


def delete_document(doc_id: int) -> int:
    with SessionLocal() as s:
        n = s.execute(delete(Chunk).where(Chunk.doc_id == doc_id)).rowcount
        s.execute(delete(Document).where(Document.id == doc_id))
        s.commit()
    logger.info("MySQL 删除 document id={} 及其 {} 条 chunk", doc_id, n)
    return n


def insert_chunks(doc_id: int, kb_id: int, items: list[dict]) -> list[int]:
    with SessionLocal() as s:
        objs = [Chunk(doc_id=doc_id, kb_id=kb_id, content=it["content"],
                      chunk_index=it["chunk_index"], milvus_id=None) for it in items]
        s.add_all(objs); s.flush()
        ids = [o.id for o in objs]
        s.commit()
    logger.info("MySQL 插入 {} 条 chunk, doc_id={}", len(ids), doc_id)
    return ids


def update_chunk_milvus_ids(mapping: dict):
    if not mapping:
        return
    with SessionLocal() as s:
        s.execute(update(Chunk), [{"id": cid, "milvus_id": mid} for cid, mid in mapping.items()])
        s.commit()
    logger.info("回写 milvus_id 完成, {} 条", len(mapping))


def get_chunks(doc_id: int) -> list[dict]:
    with SessionLocal() as s:
        rows = s.execute(select(Chunk).where(Chunk.doc_id == doc_id)
                         .order_by(Chunk.chunk_index)).scalars().all()
        return [{"id": c.id, "chunk_index": c.chunk_index,
                 "content": c.content, "milvus_id": c.milvus_id} for c in rows]


def get_chunk_milvus_ids(doc_id: int) -> list[int]:
    with SessionLocal() as s:
        rows = s.execute(select(Chunk.milvus_id).where(Chunk.doc_id == doc_id)).scalars().all()
        return [r for r in rows if r is not None]


def delete_kb(kb_id: int) -> int:
    """只删 knowledge_base 表那一行。该 kb 下的 document/chunk 由调用方先逐个 delete_document 清理。"""
    with SessionLocal() as s:
        n = s.execute(delete(KnowledgeBase).where(KnowledgeBase.id == kb_id)).rowcount
        s.commit()
    logger.info("MySQL 删除 knowledge_base id={}", kb_id)
    return n


def count_documents(kb_id: int) -> int:
    with SessionLocal() as s:
        return s.execute(select(func.count()).select_from(Document)
                         .where(Document.kb_id == kb_id)).scalar_one()


def count_chunks(kb_id: int) -> int:
    with SessionLocal() as s:
        return s.execute(select(func.count()).select_from(Chunk)
                         .where(Chunk.kb_id == kb_id)).scalar_one()


def sum_chunk_bytes(kb_id: int) -> int:
    """阶段八未持久化原文件，size_bytes 先按 chunk content 字节估（MySQL LENGTH 按字节）。"""
    with SessionLocal() as s:
        return int(s.execute(
            select(func.coalesce(func.sum(func.length(Chunk.content)), 0))
            .where(Chunk.kb_id == kb_id)).scalar_one())


class Model(Base):
    __tablename__ = "model"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(32))          # llm | rerank | embedding
    endpoint: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Share(Base):
    __tablename__ = "share"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kb_id: Mapped[int] = mapped_column(BigInteger, index=True)
    doc_id: Mapped[int] = mapped_column(BigInteger, index=True)
    doc_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # 批量分享的文档ID列表(JSON数组)，空=单文档分享
    folder_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)  # 文件夹分享来源，NULL=普通分享
    created_by: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class KbConfig(Base):
    """知识库配置：与 knowledge_base 1:1，kb_id 作主键（非自增，建库时由调用方写入）。"""
    __tablename__ = "kb_config"
    __table_args__ = {"mysql_charset": "utf8mb4"}
    kb_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    chunk_size: Mapped[int] = mapped_column(Integer, default=500)
    overlap: Mapped[int] = mapped_column(Integer, default=50)
    chunk_method: Mapped[str] = mapped_column(String(20), default="recursive")   # fixed | recursive | markdown | semantic | sentence_window
    retrieval_mode: Mapped[str] = mapped_column(String(20), default="hybrid")
    recall_k: Mapped[int] = mapped_column(Integer, default=20)
    top_k: Mapped[int] = mapped_column(Integer, default=5)
    rerank_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rerank_top_n: Mapped[int] = mapped_column(Integer, default=3)
    score_threshold: Mapped[float] = mapped_column(Float, default=0.5)
    ocr_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    table_parse_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    formula_parse_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    llm_model: Mapped[str] = mapped_column(String(255), default="")
    rerank_model: Mapped[str] = mapped_column(String(255), default="")
    embedding_model: Mapped[str] = mapped_column(String(255), default="")
    safety_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    safety_llm_check: Mapped[bool] = mapped_column(Boolean, default=False)
    rerank_mode: Mapped[str] = mapped_column(String(20), default="fusion")  # fusion | llm
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# settings 的配置字段全集（GET 输出 + PUT 可改）；embedding_model 单独锁定不可改
KB_CONFIG_FIELDS = ["chunk_size", "overlap", "chunk_method", "retrieval_mode", "recall_k", "top_k",
                    "rerank_enabled", "rerank_top_n", "score_threshold", "ocr_enabled",
                    "table_parse_enabled", "formula_parse_enabled", "llm_model",
                    "rerank_model", "embedding_model", "safety_enabled",
                    "safety_llm_check", "rerank_mode"]


def create_kb_config(kb_id: int, **overrides):
    """建库时写入配置。overrides 来自 CreateKBRequest 的可配置字段。
    未传的字段使用 KbConfig 列默认值（由 SQLAlchemy column default 兜底）。"""
    # 白名单：前端可覆盖的字段
    allowed = {"chunk_size", "overlap", "chunk_method", "retrieval_mode",
               "recall_k", "top_k", "rerank_mode",
               "llm_model", "safety_enabled", "safety_llm_check"}
    values = {}
    for k in allowed:
        if k in overrides and overrides[k] is not None:
            values[k] = overrides[k]
    # 从 rerank_mode 推导 rerank_enabled
    if "rerank_mode" in values:
        values["rerank_enabled"] = values["rerank_mode"] != "off"
    # 服务端默认模型（前端未传时使用）
    if "llm_model" not in values:
        values["llm_model"] = config.LLM_MODEL
    values["rerank_model"] = config.LLM_MODEL       # rerank 走 LLM
    values["embedding_model"] = config.EMBEDDING_MODEL

    with SessionLocal() as s:
        if s.get(KbConfig, kb_id):
            return
        s.add(KbConfig(kb_id=kb_id, **values))
        s.commit()
    logger.info("创建 kb_config kb_id={} 字段={}", kb_id, list(values))


def get_kb_config(kb_id: int) -> dict | None:
    with SessionLocal() as s:
        c = s.get(KbConfig, kb_id)
        return None if c is None else {f: getattr(c, f) for f in KB_CONFIG_FIELDS}


def update_kb_config(kb_id: int, fields: dict) -> bool:
    """只更新传入且属于 KB_CONFIG_FIELDS 的字段；embedding_model 一律忽略（已锁定）。"""
    clean = {k: v for k, v in fields.items()
             if k in KB_CONFIG_FIELDS and k != "embedding_model"}
    if not clean:
        return False
    with SessionLocal() as s:
        if s.get(KbConfig, kb_id) is None:
            return False
        s.execute(update(KbConfig).where(KbConfig.kb_id == kb_id).values(**clean))
        s.commit()
    logger.info("更新 kb_config kb_id={} 字段={}", kb_id, list(clean))
    return True


def get_kb_basic(kb_id: int) -> dict | None:
    """取主表的 name/description（settings GET 要合并进来）。"""
    with SessionLocal() as s:
        k = s.get(KnowledgeBase, kb_id)
        return None if k is None else {"name": k.name, "description": k.description}


def update_kb_description(kb_id: int, description: str):
    with SessionLocal() as s:
        s.execute(update(KnowledgeBase).where(KnowledgeBase.id == kb_id)
                  .values(description=description))
        s.commit()


def update_document_storage(doc_id: int, storage_path: str, size: int, mime: str):
    """回填原文件持久化信息（storage_path 为相对项目根的路径）。"""
    with SessionLocal() as s:
        s.execute(update(Document).where(Document.id == doc_id)
                  .values(storage_path=storage_path, size=size, mime=mime))
        s.commit()
    logger.info("回填原文件信息 doc_id={} path={} size={}", doc_id, storage_path, size)


def get_document_storage(doc_id: int) -> dict | None:
    """取文档的原文件持久化信息（下载用）。"""
    with SessionLocal() as s:
        d = s.get(Document, doc_id)
        return None if d is None else {"storage_path": d.storage_path,
                                       "size": d.size, "mime": d.mime}


def _norm_tags(tags) -> list[str]:
    """去空、去重、保序。"""
    seen, out = set(), []
    for t in (tags or []):
        t = str(t).strip()
        if t and t not in seen:
            seen.add(t); out.append(t)
    return out


def _load_tags(raw) -> list[str]:
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def update_document_tags(doc_id: int, tags) -> list[str] | None:
    """更新文档标签（存 JSON 字符串）。返回标准化后的 tags；doc 不存在返 None。"""
    clean = _norm_tags(tags)
    with SessionLocal() as s:
        d = s.get(Document, doc_id)
        if d is None:
            return None
        d.tags = json.dumps(clean, ensure_ascii=False)
        s.commit()
    logger.info("更新 document tags doc_id={} tags={}", doc_id, clean)
    return clean


def create_folder(kb_id: int, name: str, parent_id: int | None = None) -> int:
    with SessionLocal() as s:
        fo = Folder(kb_id=kb_id, name=name, parent_id=parent_id)
        s.add(fo); s.flush(); fid = fo.id; s.commit()
    logger.info("创建 folder id={} kb_id={} name={} parent={}", fid, kb_id, name, parent_id)
    return fid


def list_folders(kb_id: int) -> list[dict]:
    """按树序(DFS)返回，带 depth，供前端缩进渲染。"""
    with SessionLocal() as s:
        rows = s.execute(select(Folder).where(Folder.kb_id == kb_id)).scalars().all()
        flat = [{"id": f.id, "name": f.name, "parent_id": f.parent_id} for f in rows]
    children = {}
    for f in flat:
        children.setdefault(f["parent_id"], []).append(f)
    for k in children:
        children[k].sort(key=lambda x: x["id"])
    out = []
    def dfs(pid, depth):
        for f in children.get(pid, []):
            out.append({"id": f["id"], "name": f["name"],
                        "depth": depth, "parent_id": f["parent_id"]})
            dfs(f["id"], depth + 1)
    dfs(None, 0)
    return out


def delete_folder_safe(folder_id: int) -> bool:
    """安全删：其下文档 folder_id→None；直接子文件夹 parent_id→被删者的父级；删该行。"""
    with SessionLocal() as s:
        target = s.get(Folder, folder_id)
        if target is None:
            return False
        grandparent = target.parent_id
        s.execute(update(Document).where(Document.folder_id == folder_id)
                  .values(folder_id=None))
        s.execute(update(Folder).where(Folder.parent_id == folder_id)
                  .values(parent_id=grandparent))
        s.execute(delete(Folder).where(Folder.id == folder_id))
        s.commit()
    logger.info("安全删 folder id={}（文档回根，子文件夹上提到 {}）", folder_id, grandparent)
    return True


def set_document_folder(doc_id: int, folder_id: int | None):
    with SessionLocal() as s:
        s.execute(update(Document).where(Document.id == doc_id)
                  .values(folder_id=folder_id))
        s.commit()
    logger.info("文档 doc_id={} 归属 folder_id={}", doc_id, folder_id)


def get_folder(folder_id: int) -> dict | None:
    with SessionLocal() as s:
        f = s.get(Folder, folder_id)
        return None if f is None else {"id": f.id, "kb_id": f.kb_id, "name": f.name, "parent_id": f.parent_id}


# ---------------- model 注册表 CRUD ----------------
def list_models(type: str | None = None, only_enabled: bool = False) -> list[dict]:
    """列模型。type 过滤可选；only_enabled=True 时只返启用的(供下拉)。"""
    with SessionLocal() as s:
        stmt = select(Model)
        if type is not None:
            stmt = stmt.where(Model.type == type)
        if only_enabled:
            stmt = stmt.where(Model.enabled == True)   # noqa: E712
        stmt = stmt.order_by(Model.id)
        rows = s.execute(stmt).scalars().all()
        return [{"id": m.id, "name": m.name, "type": m.type,
                 "endpoint": m.endpoint, "enabled": bool(m.enabled)} for m in rows]


def get_model(model_id: int) -> dict | None:
    with SessionLocal() as s:
        m = s.get(Model, model_id)
        return None if m is None else {
            "id": m.id, "name": m.name, "type": m.type,
            "endpoint": m.endpoint, "enabled": bool(m.enabled)}


def create_model(name: str, type: str, endpoint: str | None = None,
                 enabled: bool = True) -> int:
    with SessionLocal() as s:
        m = Model(name=name, type=type, endpoint=endpoint, enabled=enabled)
        s.add(m); s.commit(); s.refresh(m)
        return m.id


def update_model(model_id: int, fields: dict) -> bool:
    """部分更新：只改传入的合法字段(name/type/endpoint/enabled)。"""
    allowed = {"name", "type", "endpoint", "enabled"}
    patch = {k: v for k, v in fields.items() if k in allowed}
    if not patch:
        return get_model(model_id) is not None
    with SessionLocal() as s:
        if s.get(Model, model_id) is None:
            return False
        s.execute(update(Model).where(Model.id == model_id).values(**patch))
        s.commit()
        return True


def get_model_name(model_id: int) -> str | None:
    """供 chat 参数化：拿 enabled 的模型名；停用或不存在返 None。"""
    with SessionLocal() as s:
        m = s.get(Model, model_id)
        return m.name if (m is not None and m.enabled) else None


# ---------------- 分享 share ----------------
import secrets as _secrets
from datetime import timezone as _tz, timedelta as _td


def create_share(kb_id: int, doc_id: int, created_by: int,
                 expires_in_days: int | None = None) -> dict:
    """创建分享链接。expires_in_days=None 表示永久。返回 {id, token, expires_at}。"""
    token = _secrets.token_urlsafe(24)
    expires_at = None
    if expires_in_days is not None and expires_in_days > 0:
        expires_at = datetime.now(_tz.utc) + _td(days=expires_in_days)
    with SessionLocal() as s:
        sh = Share(token=token, kb_id=kb_id, doc_id=doc_id,
                   created_by=created_by, expires_at=expires_at)
        s.add(sh); s.commit(); s.refresh(sh)
        return {"id": sh.id, "token": token,
                "expires_at": expires_at.isoformat() if expires_at else None}


def create_batch_share(kb_id: int, doc_ids: list[int], created_by: int,
                       expires_in_days: int | None = None,
                       folder_id: int | None = None) -> dict:
    """创建批量分享链接（一个 token 覆盖多个文档）。
    expires_in_days=None 表示永久。folder_id 非空表示文件夹分享。
    返回 {id, token, expires_at, doc_count}。
    """
    token = _secrets.token_urlsafe(24)
    expires_at = None
    if expires_in_days is not None and expires_in_days > 0:
        expires_at = datetime.now(_tz.utc) + _td(days=expires_in_days)
    with SessionLocal() as s:
        sh = Share(token=token, kb_id=kb_id, doc_id=0,
                   doc_ids=json.dumps(doc_ids, ensure_ascii=False),
                   folder_id=folder_id,
                   created_by=created_by, expires_at=expires_at)
        s.add(sh); s.commit(); s.refresh(sh)
        return {"id": sh.id, "token": token,
                "expires_at": expires_at.isoformat() if expires_at else None,
                "doc_count": len(doc_ids)}


def get_folder_doc_ids(kb_id: int, folder_id: int) -> list[int]:
    """递归查文件夹及其所有子孙文件夹下的文档 ID 列表。"""
    with SessionLocal() as s:
        # 收集该文件夹下的所有子孙文件夹 ID
        child_folder_ids: set[int] = {folder_id}
        queue = [folder_id]
        while queue:
            parent = queue.pop(0)
            children = s.execute(
                select(Folder.id).where(Folder.parent_id == parent)
            ).scalars().all()
            for cid in children:
                if cid not in child_folder_ids:
                    child_folder_ids.add(cid)
                    queue.append(cid)

        # 查这些文件夹下的所有文档
        doc_ids = s.execute(
            select(Document.id).where(
                Document.kb_id == kb_id,
                Document.folder_id.in_(child_folder_ids),
            )
        ).scalars().all()
        return list(doc_ids)


def list_shares(kb_id: int) -> list[dict]:
    """列某库的分享链接（含已吊销/过期，前端自行标注状态）。"""
    with SessionLocal() as s:
        rows = s.execute(select(Share).where(Share.kb_id == kb_id)
                         .order_by(Share.id.desc())).scalars().all()
        return [{"id": sh.id, "token": sh.token, "doc_id": sh.doc_id,
                 "doc_ids": _load_tags(sh.doc_ids) if sh.doc_ids else None,
                 "folder_id": sh.folder_id,
                 "expires_at": sh.expires_at.isoformat() if sh.expires_at else None,
                 "revoked": sh.revoked_at.isoformat() if sh.revoked_at else None,
                 "created_at": sh.created_at.isoformat() if sh.created_at else None}
                for sh in rows]


def get_share_by_token(token: str) -> dict | None:
    """公开访问用：按 token 取有效分享。已吊销/已过期 → None。"""
    with SessionLocal() as s:
        sh = s.scalar(select(Share).where(Share.token == token))
        if sh is None or sh.revoked_at is not None:
            return None
        if sh.expires_at is not None:
            exp = sh.expires_at
            if exp.tzinfo is None:           # 库里取出可能无时区，补 UTC 再比
                exp = exp.replace(tzinfo=_tz.utc)
            if exp < datetime.now(_tz.utc):
                return None
        return {"id": sh.id, "kb_id": sh.kb_id, "doc_id": sh.doc_id,
                "doc_ids": _load_tags(sh.doc_ids) if sh.doc_ids else None,
                "folder_id": sh.folder_id,
                "expires_at": sh.expires_at.isoformat() if sh.expires_at else None}


def revoke_share(share_id: int, kb_id: int) -> bool:
    """吊销分享（标记 revoked_at）。限本库；不存在/不属本库 → False。"""
    with SessionLocal() as s:
        sh = s.get(Share, share_id)
        if sh is None or sh.kb_id != kb_id:
            return False
        if sh.revoked_at is None:
            sh.revoked_at = datetime.now(_tz.utc)
            s.commit()
        return True


# ---------------- 异步任务 task ----------------

class Task(Base):
    __tablename__ = "task"
    __table_args__ = {"mysql_charset": "utf8mb4"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    kb_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    doc_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, default="upload")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


def create_task(user_id: int, kb_id: int, doc_id: int, filename: str,
                task_type: str = "upload") -> int:
    with SessionLocal() as s:
        t = Task(user_id=user_id, kb_id=kb_id, doc_id=doc_id,
                 filename=filename, task_type=task_type,
                 status="queued", progress=0,
                 started_at=datetime.now())
        s.add(t); s.flush(); tid = t.id; s.commit()
    logger.info("创建 task id={} doc_id={} type={}", tid, doc_id, task_type)
    return tid


def update_task_status(task_id: int, status: str, progress: int = 0,
                       error_msg: str | None = None):
    if task_id is None:
        return
    vals: dict = {"status": status, "progress": progress}
    if status in ("done", "failed"):
        vals["completed_at"] = datetime.now()
    if error_msg is not None:
        vals["error_msg"] = error_msg
    with SessionLocal() as s:
        s.execute(update(Task).where(Task.id == task_id).values(**vals))
        s.commit()


def get_task(task_id: int) -> dict | None:
    with SessionLocal() as s:
        t = s.get(Task, task_id)
        if t is None:
            return None
        kb = s.get(KnowledgeBase, t.kb_id)
        return _task_dict(t, kb.name if kb else "")


def list_tasks(user_id: int, status: str | None = None) -> list[dict]:
    with SessionLocal() as s:
        stmt = select(Task).where(Task.user_id == user_id)
        if status:
            stmt = stmt.where(Task.status == status)
        stmt = stmt.order_by(Task.id.desc()).limit(200)
        rows = s.execute(stmt).scalars().all()
        kb_ids = list({t.kb_id for t in rows})
        kb_names: dict[int, str] = {}
        if kb_ids:
            kbs = s.execute(select(KnowledgeBase).where(
                KnowledgeBase.id.in_(kb_ids))).scalars().all()
            kb_names = {k.id: k.name for k in kbs}
        return [_task_dict(t, kb_names.get(t.kb_id, "")) for t in rows]


def get_latest_task_by_doc_id(doc_id: int) -> dict | None:
    """获取某文档最近一条任务（用于文档维度的重试入口）。"""
    with SessionLocal() as s:
        t = s.execute(
            select(Task).where(Task.doc_id == doc_id).order_by(Task.id.desc()).limit(1)
        ).scalars().first()
        if t is None:
            return None
        kb = s.get(KnowledgeBase, t.kb_id)
        return _task_dict(t, kb.name if kb else "")


def _task_dict(t: Task, kb_name: str) -> dict:
    return {
        "id": t.id,
        "task_type": t.task_type,
        "kb_id": t.kb_id,
        "kb_name": kb_name,
        "doc_id": t.doc_id,
        "filename": t.filename,
        "status": t.status,
        "progress": t.progress,
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        "error_msg": t.error_msg,
    }
