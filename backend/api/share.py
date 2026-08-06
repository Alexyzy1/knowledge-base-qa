"""分享接口：单文档只读链接。
- 管理组(router, /api/kb/{id}/share)：创建/列表/吊销，需 owner，挂组级登录依赖。
- 公开组(public_router, /api/share/{token})：免登录只读，main.py 注册时不挂组级依赖。
- 需登录组(auth_router, /api/share/{token})：导入到我的知识库，挂组级登录依赖。
公开访问返回文档原文件 URL（不查 chunks 表，单次返回原文件二元组信息即可）；
链接失效(吊销/过期) → code:404。
"""
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from loguru import logger
from backend.store import mysql_store as db
from backend.store import auth_store as astore
from backend.core.response import success, fail
from backend.core.deps import get_current_user, get_client_ip
from backend.core import rbac

router = APIRouter(prefix="/api/kb", tags=["share"])
public_router = APIRouter(prefix="/api/share", tags=["share_public"])
auth_router = APIRouter(prefix="/api/share", tags=["share_auth"])


class CreateShareRequest(BaseModel):
    doc_id: int
    expires_in_days: int | None = None


class BatchShareRequest(BaseModel):
    doc_ids: list[int]
    expires_in_days: int | None = None


class ImportShareRequest(BaseModel):
    kb_id: int
    doc_indices: list[int] | None = None   # None=导入全部；[0,2]=只导入索引0和2的文档
    target_folder_id: int | None = None


@router.post("/{kb_id}/share/batch")
def batch_create_share(kb_id: int, req: BatchShareRequest, request: Request,
                       user: dict = Depends(get_current_user)):
    """批量分享：为一个或多个文档生成一个分享链接。仅 owner。"""
    rbac.require_kb_role(user, kb_id, "owner")

    if not req.doc_ids:
        return fail(code=400, msg="请选择文档")

    # 验证所有文档属于该 KB
    docs_info = []
    for did in req.doc_ids:
        doc = db.get_document(did)
        if doc is None or doc["kb_id"] != kb_id:
            return fail(code=404, msg=f"文档 {did} 不存在或不属于该知识库")
        docs_info.append({"doc_id": did, "filename": doc["filename"]})

    created = db.create_batch_share(kb_id, req.doc_ids, user["id"], req.expires_in_days)
    astore.write_audit(action="create_batch_share", user_id=user["id"],
                       username=user["username"], kb_id=kb_id,
                       target=f"docs:{','.join(str(d) for d in req.doc_ids)}",
                       ip=get_client_ip(request))
    logger.info("用户 {} 创建批量分享 kb={} docs={} token={}",
                user["username"], kb_id, req.doc_ids, created["token"])
    return success({"id": created["id"], "token": created["token"],
                    "url": "/share/" + created["token"],
                    "expires_at": created["expires_at"],
                    "doc_count": created["doc_count"],
                    "docs": docs_info})


@router.post("/{kb_id}/share")
def create_share(kb_id: int, req: CreateShareRequest, request: Request,
                 user: dict = Depends(get_current_user)):
    rbac.require_kb_role(user, kb_id, "owner")        # 仅 owner 可分享
    doc = db.get_document(req.doc_id)
    if doc is None or doc["kb_id"] != kb_id:
        return fail(code=404, msg="文档不存在或不属于该知识库")
    created = db.create_share(kb_id, req.doc_id, user["id"], req.expires_in_days)
    astore.write_audit(action="create_share", user_id=user["id"], username=user["username"],
                       kb_id=kb_id, target="doc:"+str(req.doc_id), ip=get_client_ip(request))
    logger.info("用户 {} 创建分享 kb={} doc={} token={}",
                user["username"], kb_id, req.doc_id, created["token"])
    return success({"id": created["id"], "token": created["token"],
                    "url": "/share/" + created["token"],
                    "expires_at": created["expires_at"]})


@router.get("/{kb_id}/share")
def list_shares(kb_id: int, user: dict = Depends(get_current_user)):
    rbac.require_kb_role(user, kb_id, "owner")
    return success(db.list_shares(kb_id))


@router.delete("/{kb_id}/share/{share_id}")
def revoke_share(kb_id: int, share_id: int, request: Request,
                 user: dict = Depends(get_current_user)):
    rbac.require_kb_role(user, kb_id, "owner")
    ok = db.revoke_share(share_id, kb_id)
    if not ok:
        return fail(code=404, msg="分享不存在或无权操作")
    astore.write_audit(action="revoke_share", user_id=user["id"], username=user["username"],
                       kb_id=kb_id, target="share:"+str(share_id), ip=get_client_ip(request))
    logger.info("用户 {} 吊销分享 id={}", user["username"], share_id)
    return success({"revoked": True})


# ── 文件夹分享 ──

class CreateFolderShareRequest(BaseModel):
    folder_id: int
    expires_in_days: int | None = None


@router.post("/{kb_id}/share/folder")
def create_folder_share(kb_id: int, req: CreateFolderShareRequest, request: Request,
                        user: dict = Depends(get_current_user)):
    """创建文件夹分享：递归收集该文件夹及其子文件夹下的所有文档，生成一个分享链接。仅 owner。"""
    rbac.require_kb_role(user, kb_id, "owner")

    fo = db.get_folder(req.folder_id)
    if fo is None or fo["kb_id"] != kb_id:
        return fail(code=404, msg="文件夹不存在或不属于该知识库")

    doc_ids = db.get_folder_doc_ids(kb_id, req.folder_id)
    if not doc_ids:
        return fail(code=400, msg="该文件夹（含子文件夹）下没有文档")

    # 验证文档名
    docs_info = []
    for did in doc_ids:
        doc = db.get_document(did)
        if doc:
            docs_info.append({"doc_id": did, "filename": doc["filename"]})

    created = db.create_batch_share(kb_id, doc_ids, user["id"], req.expires_in_days,
                                    folder_id=req.folder_id)
    astore.write_audit(action="create_folder_share", user_id=user["id"],
                       username=user["username"], kb_id=kb_id,
                       target=f"folder:{req.folder_id} docs:{len(doc_ids)}",
                       ip=get_client_ip(request))
    logger.info("用户 {} 创建文件夹分享 kb={} folder={} token={} docs={}",
                user["username"], kb_id, req.folder_id, created["token"], len(doc_ids))
    return success({"id": created["id"], "token": created["token"],
                    "url": "/share/" + created["token"],
                    "expires_at": created["expires_at"],
                    "doc_count": created["doc_count"],
                    "folder_name": fo["name"],
                    "docs": docs_info})


# ── 公开分享 ──

@public_router.get("/{token}")
def public_share(token: str):
    """公开只读访问，免登录。返回原文件 raw URL，不查 chunks 表。失效(吊销/过期/不存在) → 404。"""
    sh = db.get_share_by_token(token)
    if sh is None:
        return fail(code=404, msg="链接已失效")

    basic = db.get_kb_basic(sh["kb_id"])
    kb_name = basic["name"] if basic else ""

    # 批量分享：多个文档 — 每个列出原文件 raw URL
    if sh.get("doc_ids"):
        doc_infos = []
        for did in sh["doc_ids"]:
            doc = db.get_document(did)
            if doc is None:
                continue
            storage = db.get_document_storage(did)
            doc_infos.append({
                "doc_id": did,
                "filename": doc["filename"],
                "has_file": bool(storage and storage.get("storage_path")),
                "file_url": f"/api/share/{token}/raw/{did}" if (storage and storage.get("storage_path")) else None,
            })
        logger.info("公开访问批量分享 token={} docs={}", token, sh["doc_ids"])
        return success({
            "is_batch": True, "kb_name": kb_name,
            "docs": doc_infos, "expires_at": sh["expires_at"],
        })

    # 单文档分享：直接返回原文件 raw URL，前端用 iframe 内嵌
    doc = db.get_document(sh["doc_id"])
    if doc is None:
        return fail(code=404, msg="文档已删除")
    storage = db.get_document_storage(sh["doc_id"])
    has_file = bool(storage and storage.get("storage_path"))
    logger.info("公开访问分享 token={} doc={} has_file={}", token, sh["doc_id"], has_file)
    return success({
        "is_batch": False,
        "doc_id": sh["doc_id"], "doc_name": doc["filename"],
        "kb_name": kb_name, "expires_at": sh["expires_at"],
        "has_file": has_file,
        "file_url": f"/api/share/{token}/raw" if has_file else None,
    })


# ── 原文件流式端点（公开，免登录）──

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STORAGE_ROOT = _PROJECT_ROOT / "storage"


@public_router.head("/{token}/raw")
@public_router.get("/{token}/raw")
def public_share_raw(token: str):
    """公开分享的原文件流式输出（单文档），免登录。Content-Type 走 DB mime。"""
    sh = db.get_share_by_token(token)
    if sh is None:
        return fail(code=404, msg="链接已失效")
    if sh.get("doc_ids"):
        return fail(code=400, msg="批量分享请使用 /raw/{doc_id} 路径")
    doc = db.get_document(sh["doc_id"])
    if doc is None:
        return fail(code=404, msg="文档已删除")
    return _stream_doc_file(doc, token)


@public_router.head("/{token}/raw/{doc_id}")
@public_router.get("/{token}/raw/{doc_id}")
def public_share_raw_doc(token: str, doc_id: int):
    """公开分享的原文件流式输出（批量分享中的单篇），免登录。"""
    sh = db.get_share_by_token(token)
    if sh is None:
        return fail(code=404, msg="链接已失效")
    if not sh.get("doc_ids") or doc_id not in sh["doc_ids"]:
        return fail(code=404, msg="文档不在此分享中")
    doc = db.get_document(doc_id)
    if doc is None:
        return fail(code=404, msg="文档已删除")
    return _stream_doc_file(doc, token)


def _stream_doc_file(doc: dict, token: str) -> FileResponse:
    """从 storage 路径流式输出原文件。无原文件 → 404。"""
    storage = db.get_document_storage(doc["id"])
    if not storage or not storage.get("storage_path"):
        return fail(code=404, msg="原文件不存在（该文档上传于持久化功能之前）")

    abspath = os.path.realpath(os.path.join(str(_PROJECT_ROOT), storage["storage_path"]))
    root = os.path.realpath(str(_STORAGE_ROOT))
    if not (abspath == root or abspath.startswith(root + os.sep)):
        logger.error("分享文件路径逃逸 doc_id={} path={}", doc["id"], storage["storage_path"])
        return fail(code=404, msg="原文件不存在")
    if not os.path.isfile(abspath):
        return fail(code=404, msg="原文件不存在")

    ext = Path(doc["filename"] or "").suffix.lower() if doc.get("filename") else ""
    ascii_fb = (doc.get("filename") or "download").encode("ascii", "ignore").decode("ascii")
    ascii_fb = ascii_fb.replace('"', "").replace("\r", "").replace("\n", "")
    if not ascii_fb.strip() or ascii_fb.strip() == ext:
        ascii_fb = "download" + (ext or "")
    disp = f'inline; filename="{ascii_fb}"; filename*=UTF-8\'\'{quote(doc["filename"] or "download", safe="")}'

    logger.info("分享原文件流式输出 token={} doc_id={} → {}", token, doc["id"], storage["storage_path"])
    return FileResponse(abspath, media_type=storage.get("mime") or "application/octet-stream",
                        headers={"Content-Disposition": disp})


# ── Helpers for import ──

def _get_share_markdown_docs(sh: dict) -> list[dict]:
    """从分享记录提取 (filename, markdown) 列表，支持单文档和批量。"""
    if sh.get("doc_ids"):
        docs = []
        for did in sh["doc_ids"]:
            doc = db.get_document(did)
            if doc is None:
                continue
            chunks = db.get_chunks(did)
            text = "\n".join(c["content"] for c in chunks)
            docs.append({"filename": doc["filename"], "markdown": text})
        return docs

    # 单文档分享
    doc = db.get_document(sh["doc_id"])
    if doc is None:
        return []
    chunks = db.get_chunks(sh["doc_id"])
    text = "\n".join(c["content"] for c in chunks)
    return [{"filename": doc["filename"], "markdown": text}]


# ── Import endpoint (authenticated) ──

@auth_router.post("/{token}/import")
def import_share(token: str, req: ImportShareRequest, request: Request,
                 background_tasks: BackgroundTasks,
                 user: dict = Depends(get_current_user)):
    """将分享的文档导入到目标知识库。需 editor+ 权限。支持按索引选择性导入和指定目标文件夹。"""
    # 1. 验证 token
    sh = db.get_share_by_token(token)
    if sh is None:
        return fail(code=404, msg="链接已失效")

    # 2. RBAC: 目标 KB 需 editor+
    rbac.require_kb_role(user, req.kb_id, "editor")

    # 2b. 若指定了文件夹，验证文件夹属于目标 KB
    if req.target_folder_id is not None:
        fo = db.get_folder(req.target_folder_id)
        if fo is None or fo["kb_id"] != req.kb_id:
            return fail(code=400, msg="目标文件夹不存在或不属于该知识库")

    # 3. 提取文档列表
    docs = _get_share_markdown_docs(sh)
    if not docs:
        return fail(code=404, msg="分享文档已被删除")

    # 3b. 按索引过滤（doc_indices 为空则导入全部）
    if req.doc_indices:
        try:
            docs = [docs[i] for i in req.doc_indices if 0 <= i < len(docs)]
        except (IndexError, TypeError):
            return fail(code=400, msg="doc_indices 中存在无效索引")
    if not docs:
        return fail(code=400, msg="没有可导入的文档")

    # 4. 导入每个文档
    from backend.api.document import _run_ingest, _store_original_bytes

    imported = 0
    doc_ids = []
    task_ids = []

    for d in docs:
        doc_id = db.create_document(req.kb_id, d["filename"], "pending",
                                     uploaded_by=user["username"],
                                     uploaded_at=datetime.now(timezone.utc),
                                     folder_id=req.target_folder_id)
        content = d["markdown"] or ""

        # 写临时 .md 喂给入库管线
        fd, tmp_path = tempfile.mkstemp(suffix=".md", prefix="share_import_")
        with os.fdopen(fd, "w", encoding="utf-8") as fobj:
            fobj.write(content)

        # 持久化原文件到 storage
        try:
            info = _store_original_bytes(content.encode("utf-8"), req.kb_id, doc_id, d["filename"])
            db.update_document_storage(doc_id, info["storage_path"], info["size"], info["mime"])
        except Exception as e:
            logger.error("分享导入原文件落盘失败 doc_id={}: {}（不阻断入库）", doc_id, e)

        task_id = db.create_task(user["id"], req.kb_id, doc_id, d["filename"])
        background_tasks.add_task(_run_ingest, tmp_path, req.kb_id, doc_id,
                                  task_id=task_id, filename=d["filename"])

        imported += 1
        doc_ids.append(doc_id)
        task_ids.append(task_id)

    # 5. 审计
    astore.write_audit(action="import_share", user_id=user["id"],
                       username=user["username"], kb_id=req.kb_id,
                       target=f"share:{token} docs:{','.join(str(d) for d in doc_ids)}" +
                              (f" folder:{req.target_folder_id}" if req.target_folder_id else ""),
                       ip=get_client_ip(request))
    logger.info("用户 {} 从分享 token={} 导入 {} 个文档到 kb={} folder={} doc_ids={}",
                user["username"], token, imported, req.kb_id, req.target_folder_id, doc_ids)

    return success({"imported": imported, "doc_ids": doc_ids, "task_ids": task_ids})
