"""文件夹接口：列树 / 建 / 删（安全删）。
列树需 reader；建/删需 editor。删除策略：文档回根 + 子文件夹上提。
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from loguru import logger
from backend.store import mysql_store as db
from backend.store import auth_store as astore
from backend.core.response import success, fail
from backend.core.deps import get_current_user, get_client_ip
from backend.core import rbac

router = APIRouter(prefix="/api/kb", tags=["folder"])


class CreateFolderRequest(BaseModel):
    name: str
    parent_id: int | None = None


@router.get("/{kb_id}/folders")
def list_folders(kb_id: int, user: dict = Depends(get_current_user)):
    rbac.require_kb_role(user, kb_id, "reader")
    return success(db.list_folders(kb_id))


@router.post("/{kb_id}/folders")
def create_folder(kb_id: int, req: CreateFolderRequest, request: Request,
                  user: dict = Depends(get_current_user)):
    rbac.require_kb_role(user, kb_id, "editor")
    name = (req.name or "").strip()
    if not name:
        return fail(code=400, msg="文件夹名不能为空")
    # parent_id 若给定，校验它属于本 kb（防跨库挂载）
    if req.parent_id is not None:
        parent = db.get_folder(req.parent_id)
        if parent is None or parent["kb_id"] != kb_id:
            return fail(code=400, msg="父文件夹不存在或不属于本知识库")
    fid = db.create_folder(kb_id, name, req.parent_id)
    astore.write_audit(action="create_folder", user_id=user["id"], username=user["username"],
                       kb_id=kb_id, target="folder:"+str(fid), ip=get_client_ip(request))
    logger.info("用户 {} 在 kb={} 建文件夹 {} (id={})", user["username"], kb_id, name, fid)
    return success({"id": fid, "name": name, "parent_id": req.parent_id})


@router.delete("/{kb_id}/folders/{folder_id}")
def delete_folder(kb_id: int, folder_id: int, request: Request,
                  user: dict = Depends(get_current_user)):
    rbac.require_kb_role(user, kb_id, "editor")
    fo = db.get_folder(folder_id)
    if fo is None or fo["kb_id"] != kb_id:
        return fail(code=404, msg="文件夹不存在")
    db.delete_folder_safe(folder_id)
    astore.write_audit(action="delete_folder", user_id=user["id"], username=user["username"],
                       kb_id=kb_id, target="folder:"+str(folder_id), ip=get_client_ip(request))
    return success({"deleted": folder_id})
