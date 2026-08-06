"""鉴权接口：注册（白名单拦门）+ 登录（验密码、签 JWT）。
同步 def，沿用统一响应 success/fail（HTTP 恒 200，业务码进 code）。
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from loguru import logger
from backend.core import auth
from backend.core.response import success, fail
from backend.store import auth_store as astore
from backend.core.deps import get_current_user, get_client_ip

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/register")
def register(req: RegisterRequest):
    username = req.username.strip()
    if not username or not req.password:
        return fail(code=400, msg="用户名和密码不能为空")
    if (err := auth.validate_password(req.password)) is not None:
        return fail(code=400, msg=err)
    if astore.get_user_by_username(username) is not None:
        return fail(code=409, msg="用户名已存在")
    uid = astore.create_user(username, auth.hash_pw(req.password), role="user")
    astore.add_whitelist(username, note="自助注册")  # 开放注册：注册即入白名单，登录侧回收能力保留
    logger.info("新用户注册: {} (id={}, role=user)", username, uid)
    return success({"id": uid, "username": username, "role": "user"})


@router.post("/login")
def login(req: LoginRequest, request: Request):
    username = req.username.strip()
    u = astore.get_user_with_hash(username)
    if u is None or not auth.verify_pw(req.password, u["password_hash"]):
        logger.warning("登录失败: {}", username)
        astore.write_audit(action="login_failed", username=username,
                           target="密码错误" if u else "用户不存在", ip=get_client_ip(request))
        return fail(code=401, msg="账号或密码错误")
    if u["role"] != "super_admin" and not astore.is_whitelisted(username):
        logger.warning("登录被拒（已移出白名单）: {}", username)
        astore.write_audit(action="login_denied", user_id=u["id"], username=username,
                           target="已移出白名单", ip=get_client_ip(request))
        return fail(code=403, msg="账号已被禁用")
    token = auth.create_access_token(username, token_version=u.get("token_version", 0))
    astore.write_audit(action="login", user_id=u["id"], username=username,
                       ip=get_client_ip(request))
    logger.info("登录成功: {} (role={})", username, u["role"])
    return success({"access_token": token, "token_type": "bearer",
                    "user": {"id": u["id"], "username": username, "role": u["role"]}})


@router.post("/logout")
def logout(user: dict = Depends(get_current_user)):
    """登出：自增 token_version，使当前用户所有已签发 JWT 立即失效。"""
    new_tv = astore.bump_token_version(user["id"])
    logger.info("用户登出: {} (id={}, new_tv={})", user["username"], user["id"], new_tv)
    return success({"msg": "已登出"})


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    """用 token 换回当前用户（前端刷新后恢复真实身份/角色）。无/失效 token → 真 401。"""
    return success(user)
