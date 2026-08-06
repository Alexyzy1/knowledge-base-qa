"""KB 导入：从导出的 ZIP 文件恢复知识库（创建 KB → 恢复配置 → 重建文件夹 → 恢复文档并排队入库）。
RBAC：需登录（global user 及以上），guest 不可导入。
"""
import json
import os
import tempfile
import zipfile
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, Depends, Request
from loguru import logger

from backend.store import mysql_store as db
from backend.store import auth_store as astore
from backend.core.response import success, fail
from backend.core.deps import get_current_user, get_client_ip
from backend.core import rbac
from backend.api.document import _store_original_bytes, _run_ingest, _safe_ext

router = APIRouter(prefix="/api/kb", tags=["kb_import"])


def _recreate_folders(kb_id: int, folders: list[dict]) -> dict[int, int]:
    """按 parent_id 依赖顺序创建文件夹，返回 old_id → new_id 映射。"""
    if not folders:
        return {}

    # 按深度排序（先创建没有 parent 的，再创建子文件夹）
    # folders 包含 {id, name, parent_id}
    mapping: dict[int, int] = {}
    remaining = list(folders)
    max_iter = len(remaining) + 1  # 防止死循环
    while remaining and max_iter > 0:
        max_iter -= 1
        next_round = []
        for f in remaining:
            old_parent = f.get("parent_id")
            if old_parent is None or old_parent in mapping:
                new_parent = mapping.get(old_parent) if old_parent else None
                new_id = db.create_folder(kb_id, f["name"], new_parent)
                mapping[f["id"]] = new_id
            else:
                next_round.append(f)
        remaining = next_round

    if remaining:
        logger.warning("文件夹重建：{} 个文件夹因父级缺失未能创建", len(remaining))

    return mapping


def _import_documents(
    zf: zipfile.ZipFile,
    kb_id: int,
    documents: list[dict],
    folder_map: dict[int, int],
    user_id: int,
    username: str,
    background_tasks: BackgroundTasks,
) -> dict:
    """批量恢复文档：从 ZIP 读取原始文件 → 落盘 → 创建 DB 记录 → 排队入库。"""
    total = len(documents)
    created = 0
    errors = []

    for doc in documents:
        arcname = doc.get("file_path")
        filename = doc.get("filename", "unknown")
        try:
            # 1) 从 ZIP 读取文件内容
            data = None
            if arcname:
                try:
                    data = zf.read(arcname)
                except KeyError:
                    logger.warning("导入跳过（ZIP 中无此文件）: {} → {}", filename, arcname)
                    errors.append({"filename": filename, "reason": "ZIP 中缺少文件"})
                    continue

            # 2) 创建文档记录
            doc_id = db.create_document(
                kb_id, filename, "pending",
                uploaded_by=doc.get("uploaded_by", username),
                uploaded_at=datetime.now(),
            )

            # 3) 文件夹映射
            old_folder = doc.get("folder_id")
            if old_folder is not None and old_folder in folder_map:
                db.set_document_folder(doc_id, folder_map[old_folder])

            # 4) 标签
            tags = doc.get("tags")
            if tags:
                db.update_document_tags(doc_id, tags)

            # 5) 存储原文件 + 排队入库
            if data:
                info = _store_original_bytes(data, kb_id, doc_id, filename)
                db.update_document_storage(doc_id, info["storage_path"], info["size"], info["mime"])

                # 写入临时文件供 ingest pipeline 使用
                fd, tmp_path = tempfile.mkstemp(suffix=_safe_ext(filename), prefix="import_")
                with os.fdopen(fd, "wb") as f:
                    f.write(data)

                task_id = db.create_task(user_id, kb_id, doc_id, filename)
                background_tasks.add_task(
                    _run_ingest, tmp_path, kb_id, doc_id, task_id=task_id, filename=filename
                )
            else:
                # 无原文件：标记为完成（可能是仅元数据的备注文档）
                db.update_document_status(doc_id, "done")

            created += 1
        except Exception as e:
            logger.exception("导入文档失败 kb_id={} filename={}: {}", kb_id, filename, e)
            errors.append({"filename": filename, "reason": str(e)[:200]})

    return {"total": total, "created": created, "errors": errors}


@router.post("/import")
async def kb_import(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    new_name: str | None = Form(None),
    user: dict = Depends(get_current_user),
):
    """从导出的 ZIP 文件导入知识库。

    参数：
    - file: 导出的 .zip 文件（必须含 manifest.json）
    - new_name: 可选，指定新 KB 名称（留空则使用导出时的名称）
    """
    # RBAC: guest 不可导入
    try:
        rbac.require_global(user, "user")
    except Exception as e:
        return fail(code=403, msg=str(e))

    # 校验文件扩展名
    if not file.filename or not file.filename.lower().endswith(".zip"):
        return fail(code=400, msg="请上传 .zip 格式的导出文件")

    # 读取上传内容到临时文件
    raw = await file.read()
    if len(raw) == 0:
        return fail(code=400, msg="上传文件为空")

    tmp_zip = None
    try:
        fd, tmp_zip = tempfile.mkstemp(suffix=".zip", prefix="kb_import_")
        with os.fdopen(fd, "wb") as f:
            f.write(raw)

        # 校验并解析 ZIP
        if not zipfile.is_zipfile(tmp_zip):
            return fail(code=400, msg="文件不是有效的 ZIP 格式")

        with zipfile.ZipFile(tmp_zip, "r") as zf:
            # 1) 读取 manifest
            try:
                manifest_raw = zf.read("manifest.json")
            except KeyError:
                return fail(code=400, msg="无效的导出文件：缺少 manifest.json")

            try:
                manifest = json.loads(manifest_raw)
            except json.JSONDecodeError as e:
                return fail(code=400, msg=f"无效的导出文件：manifest.json 格式错误 ({e})")

            if "knowledge_bases" not in manifest:
                return fail(code=400, msg="无效的导出文件：manifest 缺少 knowledge_bases 字段")

            # 2) 逐个恢复 KB
            kb_ids = []
            total_docs = 0
            all_errors = []

            for kb_entry in manifest["knowledge_bases"]:
                kb_info = kb_entry.get("kb", {})
                kb_config = kb_entry.get("config", {})
                kb_folders = kb_entry.get("folders", [])
                kb_docs = kb_entry.get("documents", [])

                # KB 名称：优先用用户指定的，否则用导出的
                kb_name = new_name or kb_info.get("name", "导入的知识库")
                kb_desc = kb_info.get("description", "")

                # 创建 KB
                kb_id = db.create_kb(kb_name, kb_desc)
                kb_ids.append(kb_id)

                # 导入者成为 owner
                astore.add_kb_member(kb_id, user["id"], "owner")

                # 恢复配置
                if kb_config:
                    # 过滤掉不在 KB_CONFIG_FIELDS 中的字段
                    allowed = set(db.KB_CONFIG_FIELDS)
                    clean_config = {k: v for k, v in kb_config.items() if k in allowed and k != "embedding_model"}
                    db.create_kb_config(kb_id, **clean_config)

                # 重建文件夹
                folder_map = _recreate_folders(kb_id, kb_folders)

                # 恢复文档
                result = _import_documents(zf, kb_id, kb_docs, folder_map, user["id"], user["username"], background_tasks)
                total_docs += result["created"]
                all_errors.extend(result["errors"])

                # 审计日志
                astore.write_audit(
                    action="import_kb",
                    user_id=user["id"],
                    username=user["username"],
                    kb_id=kb_id,
                    target=f"name={kb_name} docs={result['created']}/{result['total']}",
                    ip=get_client_ip(request),
                )

                logger.info(
                    "导入 KB 完成 kb_id={} name={} docs={}/{} errors={}",
                    kb_id, kb_name, result["created"], result["total"], len(result["errors"]),
                )

            return success({
                "kb_ids": kb_ids,
                "kb_count": len(kb_ids),
                "doc_count": total_docs,
                "errors": all_errors,
            })

    except Exception as e:
        logger.exception("导入 KB 异常")
        return fail(code=500, msg=f"导入失败：{e}")
    finally:
        if tmp_zip and os.path.isfile(tmp_zip):
            try:
                os.remove(tmp_zip)
            except OSError:
                pass
