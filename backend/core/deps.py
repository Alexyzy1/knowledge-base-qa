"""FastAPI 依赖：从 token 解出当前用户。
token 只装 sub，这里用 sub 现查 DB 拿当前 role/id —— 降权/删用户即时生效。
鉴权失败返回真 HTTP 401（带 WWW-Authenticate: Bearer），与 OAuth2/Swagger 对齐。

两个依赖：
- get_current_user：严格，仅认 Authorization: Bearer 头（全站默认）。
- get_current_user_lax：header 优先，缺失时兜底读 query ?token=，
  仅用于浏览器直接发起、无法自定义请求头的二进制端点（download / preview/raw）。
"""
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from backend.core.auth import decode_token
from backend.store import auth_store

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

_CRED_EXC = HTTPException(status_code=401, detail="无效或过期的凭证",
                          headers={"WWW-Authenticate": "Bearer"})


def _user_from_token(token: str | None) -> dict:
    """凭证 → user dict；任何失败抛真 401。
    凭证有两种：以 sk- 开头视为 API Key（查表反解属主）；否则按 JWT token 解码。"""
    if not token:
        raise _CRED_EXC
    # API Key 分支：sk- 开头 → 查 api_key 表反解用户（无效/已吊销 → 401）
    if token.startswith("sk-"):
        user = auth_store.get_user_by_api_key(token)
        if user is None:
            raise _CRED_EXC
        return user
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        raise _CRED_EXC
    user = auth_store.get_user_by_username(payload["sub"])
    if user is None:
        raise _CRED_EXC
    # token_version 校验：签发后若被 bump 过，旧 token 立即拒绝
    token_tv = payload.get("tv", 0)
    if token_tv != user.get("token_version", 0):
        raise _CRED_EXC
    return user


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    return _user_from_token(token)


def get_current_user_lax(request: Request) -> dict:
    """header 优先，缺失时读 query ?token=。仅挂在浏览器直发的二进制端点。"""
    token = None
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        token = auth[7:].strip() or None
    if token is None:
        qt = request.query_params.get("token")
        token = qt.strip() if qt else None
    return _user_from_token(token)


def get_client_ip(request: Request) -> str | None:
    """取真实客户端 IP。

    策略：
    1. 如果有信任代理，从 X-Forwarded-For 最右取真实客户端（谁连接了代理）。
    2. 无信任代理或客户端直连，直接取 request.client.host。
    3. 信任代理通过环境变量 RL_TRUSTED_PROXY 指定（逗号分隔的 IP 列表）。
       未设置时，X-Forwarded-For 不被信任（防伪造）。
    """
    import os
    trusted_raw = os.getenv("RL_TRUSTED_PROXY", "")
    trusted = {t.strip() for t in trusted_raw.split(",") if t.strip()}

    client_host = request.client.host if request.client else None

    # 只有在请求来自信任代理时，才采纳 X-Forwarded-For
    if trusted and client_host in trusted:
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            # X-Forwarded-For: client, proxy1, proxy2 → 最左是原始客户端
            first = xff.split(",")[0].strip()
            if first:
                return first

    # 备选：X-Real-IP（部分代理使用单 IP 头）
    if trusted and client_host in trusted:
        xri = request.headers.get("X-Real-IP")
        if xri and xri.strip():
            return xri.strip()

    return client_host
