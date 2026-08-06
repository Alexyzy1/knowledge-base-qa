"""密码哈希（bcrypt）+ JWT 签发/解码 helper。"""
from datetime import datetime, timedelta, timezone
import bcrypt
import jwt
from backend.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_HOURS


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def verify_pw(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except (ValueError, TypeError):
        return False


def validate_password(pw: str) -> str | None:
    """校验密码复杂度。返回 None 表示通过，否则返回中文错误提示。"""
    if not pw or len(pw) < 8:
        return "密码至少 8 位"
    if not any(c.isupper() for c in pw):
        return "密码需包含至少一个大写字母"
    if not any(c.isdigit() for c in pw):
        return "密码需包含至少一个数字"
    return None


def create_access_token(username: str, token_version: int = 0) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": username, "iat": now,
               "exp": now + timedelta(hours=JWT_EXPIRE_HOURS),
               "tv": token_version}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    """合法返回 payload；过期/篡改/非法一律返回 None（不抛）。"""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
