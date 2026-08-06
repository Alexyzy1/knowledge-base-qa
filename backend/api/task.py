"""任务中心接口：查询当前用户的异步任务列表 + 失败任务重试。
GET  /api/tasks?status=    — 列当前用户任务（最近 200 条）
POST /api/tasks/{id}/retry — 重试失败任务（重新入库）
"""
import os

from fastapi import APIRouter, BackgroundTasks, Depends
from loguru import logger

from backend.store import mysql_store as db
from backend.store import milvus_store
from backend.core.response import success, fail
from backend.core.deps import get_current_user

router = APIRouter(prefix="/api", tags=["task"])


@router.get("/tasks")
def list_tasks(status: str | None = None, user: dict = Depends(get_current_user)):
    tasks = db.list_tasks(user["id"], status=status)
    return success(tasks)


@router.post("/tasks/{task_id}/retry")
def retry_task(task_id: int, background_tasks: BackgroundTasks,
               user: dict = Depends(get_current_user)):
    task = db.get_task(task_id)
    if task is None or task.get("doc_id") is None:
        return fail(code=404, msg="任务不存在")

    # 只允许重试自己的失败任务
    from backend.store.mysql_store import Task as TaskModel
    from sqlalchemy.orm import Session
    from backend.store.mysql_store import engine as _engine
    with Session(_engine) as s:
        t = s.get(TaskModel, task_id)
        if t is None or t.user_id != user["id"]:
            return fail(code=404, msg="任务不存在")
        if t.status != "failed":
            return fail(code=400, msg="只能重试失败的任务")

    doc = db.get_document_storage(task["doc_id"])
    if not doc or not doc.get("storage_path"):
        return fail(code=400, msg="原文件不存在，无法重试")

    from pathlib import Path
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    abs_path = str(_PROJECT_ROOT / doc["storage_path"])
    if not os.path.isfile(abs_path):
        return fail(code=400, msg="原文件不存在，无法重试")

    # 清理上次失败留下的残余 chunk（MySQL + Milvus）
    doc_id = task["doc_id"]
    milvus_ids = db.get_chunk_milvus_ids(doc_id)
    if milvus_ids:
        try:
            milvus_store.delete(ids=milvus_ids)
        except Exception as e:
            logger.warning("retry: Milvus 清理失败 doc_id={}: {}", doc_id, e)
    from backend.store.mysql_store import Chunk, SessionLocal
    from sqlalchemy import delete as _delete
    with SessionLocal() as s:
        s.execute(_delete(Chunk).where(Chunk.doc_id == doc_id))
        s.commit()

    # 重置状态
    db.update_document_status(doc_id, "pending")
    db.update_task_status(task_id, "queued", 0, None)

    from backend.api.document import _run_ingest
    background_tasks.add_task(_run_ingest, abs_path, task["kb_id"], doc_id,
                              task_id=task_id, delete_after=False,
                              filename=doc.get("filename", ""))
    logger.info("用户 {} 重试 task_id={} doc_id={}", user["username"], task_id, doc_id)
    return success({"task_id": task_id, "status": "queued"})
