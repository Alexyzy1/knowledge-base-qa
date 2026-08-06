"""KB 批量导出：将选中的知识库（元数据、配置、文件夹、文档原文件）打包为 ZIP 下载。
RBAC：对每个选中 KB 校验 reader（super_admin 放行）。
"""
import io
import json
import os
import zipfile
from datetime import datetime, date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from loguru import logger

from backend.store import mysql_store as db
from backend.core.response import fail
from backend.core.deps import get_current_user
from backend.core import rbac
from backend.api.document import _content_disposition, _STORAGE_ROOT, _PROJECT_ROOT, _safe_ext

router = APIRouter(prefix="/api/kb", tags=["kb_export"])


def _build_manifest(kb_ids: list[int], username: str) -> dict:
    """查询 DB 构建导出 manifest。"""
    kbs = []
    for kb_id in kb_ids:
        basic = db.get_kb_basic(kb_id)
        if not basic:
            continue
        config = db.get_kb_config(kb_id) or {}
        folders = db.list_folders(kb_id)
        docs = db.list_documents(kb_id)

        doc_entries = []
        for d in docs:
            storage = d.get("storage_path")
            entry = {
                "filename": d["filename"],
                "tags": d.get("tags") or [],
                "folder_id": d.get("folder_id"),
                "size": d.get("file_size"),
                "uploaded_by": d.get("uploaded_by"),
                "uploaded_at": d.get("uploaded_at"),
            }
            if storage:
                # 在 ZIP 内的路径
                entry["file_path"] = "files/{}/{}{}".format(
                    kb_id, d["id"], _safe_ext(d["filename"])
                )
                entry["_storage_path"] = storage  # 用于读取本地文件
            doc_entries.append(entry)

        kbs.append({
            "kb": {"name": basic["name"], "description": basic.get("description", "")},
            "config": config,
            "folders": [{"id": f["id"], "name": f["name"], "parent_id": f["parent_id"]} for f in folders],
            "documents": doc_entries,
        })

    return {
        "version": 1,
        "exported_at": datetime.now().isoformat(),
        "exported_by": username,
        "knowledge_bases": kbs,
    }


def _zip_generator_export(manifest: dict):
    """流式生成 ZIP：先写 manifest.json，再逐个追加原始文件。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1) manifest.json
        manifest_str = json.dumps(manifest, ensure_ascii=False, indent=2)
        zf.writestr("manifest.json", manifest_str)

        # 2) 原始文件
        skipped = 0
        for kb_entry in manifest.get("knowledge_bases", []):
            for doc in kb_entry.get("documents", []):
                arcname = doc.get("file_path")
                storage_rel = doc.get("_storage_path")
                if not arcname or not storage_rel:
                    skipped += 1
                    continue
                abspath = _PROJECT_ROOT / storage_rel
                if not abspath.is_file():
                    logger.warning("导出跳过（文件不存在）: {}", str(abspath))
                    skipped += 1
                    continue
                zf.write(str(abspath), arcname)

    if skipped:
        logger.info("导出 ZIP：{} 个文档因缺少原文件被跳过", skipped)

    buf.seek(0)
    yield buf.read()


@router.get("/batch-export")
def batch_export(
    kb_ids: str = Query(..., description="逗号分隔的知识库 ID 列表"),
    user: dict = Depends(get_current_user),
):
    """批量导出知识库为 ZIP（含 manifest.json + 文档原文件）。"""
    # 解析 kb_ids
    try:
        ids = [int(x.strip()) for x in kb_ids.split(",") if x.strip()]
    except ValueError:
        return fail(code=400, msg="kb_ids 格式错误")

    if not ids:
        return fail(code=400, msg="请选择知识库")

    # RBAC: 对每个 KB 校验 reader
    try:
        rbac.require_kb_roles(user, ids, "reader")
    except Exception as e:
        return fail(code=403, msg=str(e))

    # 构建 manifest
    manifest = _build_manifest(ids, user["username"])

    total_docs = sum(len(kb["documents"]) for kb in manifest["knowledge_bases"])
    if total_docs == 0:
        logger.info("导出请求：{} 个 KB，0 个文档", len(ids))

    # 流式返回 ZIP
    filename = f"kb_export_{date.today().strftime('%Y%m%d')}.zip"
    disp = _content_disposition(filename, ".zip")

    return StreamingResponse(
        _zip_generator_export(manifest),
        media_type="application/zip",
        headers={
            "Content-Disposition": disp,
            "X-Exported-KBs": str(len(manifest["knowledge_bases"])),
            "X-Exported-Docs": str(total_docs),
        },
    )
