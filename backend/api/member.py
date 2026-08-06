"""授权管理接口：注册白名单（admin 及以上）+ kb 成员/资源角色（对该库 owner，或 super_admin）。"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from loguru import logger

from backend.store import auth_store as astore
from backend.core.response import success, fail
from backend.core.deps import get_current_user, get_client_ip
from backend.core import rbac

router = APIRouter(prefix="/api", tags=["authz"])

_KB_ROLES = {"reader", "editor", "owner"}


# ── 白名单管理（admin 及以上）──
class WhitelistRequest(BaseModel):
    username: str
    note: str | None = None


@router.post("/whitelist")
def add_whitelist(req: WhitelistRequest, request: Request,
                  user: dict = Depends(get_current_user)):
    rbac.require_global(user, "admin")
    username = req.username.strip()
    if not username:
        return fail(code=400, msg="username 不能为空")
    added = astore.add_whitelist(username, req.note)
    astore.write_audit(action="add_whitelist", user_id=user["id"], username=user["username"],
                       target="user:"+username, ip=get_client_ip(request))
    logger.info("{} 把 {} 加入白名单 (new={})", user["username"], username, added)
    return success({"username": username, "added": added})


@router.get("/whitelist")
def list_whitelist(user: dict = Depends(get_current_user)):
    rbac.require_global(user, "admin")
    return success(astore.list_whitelist())


@router.delete("/whitelist/{username}")
def remove_whitelist(username: str, request: Request,
                     user: dict = Depends(get_current_user)):
    rbac.require_global(user, "admin")
    n = astore.remove_whitelist(username)
    astore.write_audit(action="remove_whitelist", user_id=user["id"], username=user["username"],
                       target="user:"+username, ip=get_client_ip(request))
    logger.info("{} 把 {} 移出白名单 (deleted={})", user["username"], username, n)
    return success({"username": username, "removed": n})


# ── kb 成员管理（对该库 owner，或 super_admin）──
class MemberRequest(BaseModel):
    username: str
    role: str


@router.post("/kb/{kb_id}/members")
def add_member(kb_id: int, req: MemberRequest, request: Request,
               user: dict = Depends(get_current_user)):
    rbac.require_kb_role(user, kb_id, "owner")
    if req.role not in _KB_ROLES:
        return fail(code=400, msg="role 必须是 reader/editor/owner 之一")
    target = astore.get_user_by_username(req.username.strip())
    if target is None:
        return fail(code=404, msg="用户不存在（需先注册）")
    astore.add_kb_member(kb_id, target["id"], req.role)
    astore.write_audit(action="add_member", user_id=user["id"], username=user["username"],
                       kb_id=kb_id, target=f"user:{target['id']}={req.role}",
                       ip=get_client_ip(request))
    logger.info("{} 给 kb={} 授 {}={}", user["username"], kb_id, target["username"], req.role)
    return success({"kb_id": kb_id, "user_id": target["id"],
                    "username": target["username"], "role": req.role})


@router.get("/kb/{kb_id}/members")
def list_members(kb_id: int, user: dict = Depends(get_current_user)):
    rbac.require_kb_role(user, kb_id, "owner")
    return success(astore.list_kb_members(kb_id))


@router.delete("/kb/{kb_id}/members/{user_id}")
def remove_member(kb_id: int, user_id: int, request: Request,
                  user: dict = Depends(get_current_user)):
    rbac.require_kb_role(user, kb_id, "owner")
    # 保护1：不能移除自己
    if user_id == user["id"]:
        return fail(code=400, msg="不能移除自己")
    # 保护2：不能移除最后一个 owner
    members = astore.list_kb_members(kb_id)
    target_role = next((m["role"] for m in members if m["user_id"] == user_id), None)
    if target_role is None:
        return fail(code=404, msg="该成员不属于此知识库")
    if target_role == "owner":
        owner_count = sum(1 for m in members if m["role"] == "owner")
        if owner_count <= 1:
            return fail(code=400, msg="不能移除知识库的最后一个 owner")
    n = astore.remove_kb_member(kb_id, user_id)
    astore.write_audit(action="remove_member", user_id=user["id"], username=user["username"],
                       kb_id=kb_id, target="user:"+str(user_id), ip=get_client_ip(request))
    logger.info("{} 从 kb={} 移除 user_id={} (deleted={})", user["username"], kb_id, user_id, n)
    return success({"kb_id": kb_id, "user_id": user_id, "removed": n})
