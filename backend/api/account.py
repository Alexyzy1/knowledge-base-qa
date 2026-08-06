"""账户接口：改密。
PUT /api/account/password —— 验旧密码 → bcrypt 新哈希 → 落库。
需登录(端点级 Depends(get_current_user))；main.py 注册时不挂组级依赖，与 auth 同构。
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from loguru import logger
from backend.core import auth
from backend.core.response import success, fail
from backend.store import auth_store as astore
from backend.core.deps import get_current_user, get_client_ip

router = APIRouter(prefix="/api/account", tags=["account"])
keys_router = APIRouter(prefix="/api/keys", tags=["api_key"])


@router.get("")
def get_account(user: dict = Depends(get_current_user)):
    """读当前用户信息（id / username / role）。"""
    return success(user)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.put("/password")
def change_password(req: ChangePasswordRequest, request: Request,
                    user: dict = Depends(get_current_user)):
    if not req.old_password or not req.new_password:
        return fail(code=400, msg="原密码和新密码不能为空")
    if (err := auth.validate_password(req.new_password)) is not None:
        return fail(code=400, msg=err)

    # 取当前哈希验旧密码（user 来自 token，只有 username/id/role，需另查 hash）
    u = astore.get_user_with_hash(user["username"])
    if u is None:
        return fail(code=404, msg="用户不存在")
    if not auth.verify_pw(req.old_password, u["password_hash"]):
        logger.warning("改密失败（原密码错误）: {}", user["username"])
        return fail(code=403, msg="原密码错误")

    if auth.verify_pw(req.new_password, u["password_hash"]):
        return fail(code=400, msg="新密码不能与原密码相同")

    new_hash = auth.hash_pw(req.new_password)
    ok = astore.update_password(u["id"], new_hash)
    if not ok:
        return fail(code=404, msg="用户不存在")
    # 改密后自增 token_version，使所有旧 JWT 立即失效（强制重新登录）
    astore.bump_token_version(u["id"])
    astore.write_audit(action="change_password", user_id=u["id"], username=user["username"],
                       ip=get_client_ip(request))
    logger.info("用户 {} 修改密码成功", user["username"])
    return success({"updated": True})


# ── API Key 管理（挂 keys_router，路径 /api/keys）──
class CreateKeyRequest(BaseModel):
    name: str = ""


@keys_router.post("")
def create_key(req: CreateKeyRequest, request: Request, user: dict = Depends(get_current_user)):
    """签发新 key。明文只在本次响应返回一次，之后不可再取。"""
    created = astore.create_api_key(user["id"], req.name)
    astore.write_audit(action="create_key", user_id=user["id"], username=user["username"],
                       target="key:"+str(created["id"]), ip=get_client_ip(request))
    logger.info("用户 {} 签发 API Key id={}", user["username"], created["id"])
    # plain 即明文 key，原样返回；前端需提示用户立即保存
    return success({"id": created["id"], "name": created["name"],
                    "key_prefix": created["key_prefix"], "key": created["plain"]})


@keys_router.get("")
def list_keys(user: dict = Depends(get_current_user)):
    """列出当前用户的 key（不含明文，只有前缀）。"""
    return success(astore.list_api_keys(user["id"]))


@keys_router.delete("/{key_id}")
def revoke_key(key_id: int, request: Request, user: dict = Depends(get_current_user)):
    """吊销 key。只能吊销自己的；不存在/非本人 → 404。"""
    ok = astore.revoke_api_key(key_id, user["id"])
    if not ok:
        return fail(code=404, msg="Key 不存在或无权操作")
    astore.write_audit(action="revoke_key", user_id=user["id"], username=user["username"],
                       target="key:"+str(key_id), ip=get_client_ip(request))
    logger.info("用户 {} 吊销 API Key id={}", user["username"], key_id)
    return success({"revoked": True})
