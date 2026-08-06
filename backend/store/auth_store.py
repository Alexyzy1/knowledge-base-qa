"""auth 表（user / whitelist / kb_member）数据访问层。
与 mysql_store 同构：函数式接口，只回纯 dict/int/bool，不外抛 Session/ORM 对象。
共享 engine（backend.store.engine），与 mysql_store 统一连接池。
"""
from sqlalchemy import select, delete, update
from sqlalchemy.orm import Session
from backend.store.engine import engine
from backend.store.auth_models import User, Whitelist, KbMember, ApiKey, AuditLog
import secrets, hashlib
from datetime import datetime, timezone


def _user_dict(u: User) -> dict:
    return {"id": u.id, "username": u.username, "role": u.role, "token_version": u.token_version}


# ── 用户 ──
def is_whitelisted(username: str) -> bool:
    with Session(engine) as s:
        return s.scalar(select(Whitelist).where(Whitelist.username == username)) is not None


def get_user_by_username(username: str) -> dict | None:
    """通用查询，不带 password_hash（避免哈希到处流）。"""
    with Session(engine) as s:
        u = s.scalar(select(User).where(User.username == username))
        return _user_dict(u) if u else None


def get_user_with_hash(username: str) -> dict | None:
    """仅登录校验用，额外带 password_hash。"""
    with Session(engine) as s:
        u = s.scalar(select(User).where(User.username == username))
        if not u:
            return None
        d = _user_dict(u)
        d["password_hash"] = u.password_hash
        return d


def get_user_by_id(user_id: int) -> dict | None:
    with Session(engine) as s:
        u = s.get(User, user_id)
        return _user_dict(u) if u else None


def create_user(username: str, password_hash: str, role: str = "user") -> int:
    with Session(engine) as s:
        u = User(username=username, password_hash=password_hash, role=role)
        s.add(u)
        s.commit()
        return u.id


def update_password(user_id: int, new_hash: str) -> bool:
    """改密：更新 user.password_hash。用户不存在返 False。"""
    with Session(engine) as s:
        if s.get(User, user_id) is None:
            return False
        s.execute(update(User).where(User.id == user_id).values(password_hash=new_hash))
        s.commit()
        return True


def bump_token_version(user_id: int) -> int:
    """自增 user.token_version，使该用户所有已签发 JWT 立即失效。返回新版本号。"""
    with Session(engine) as s:
        s.execute(update(User).where(User.id == user_id).values(
            token_version=User.token_version + 1))
        s.commit()
        new_version = s.scalar(select(User.token_version).where(User.id == user_id))
        return new_version or 0


# ── 白名单 ──
def add_whitelist(username: str, note: str | None = None) -> bool:
    """加入白名单；已存在返回 False（幂等），新增返回 True。"""
    with Session(engine) as s:
        if s.scalar(select(Whitelist).where(Whitelist.username == username)) is not None:
            return False
        s.add(Whitelist(username=username, note=note))
        s.commit()
        return True


def list_whitelist() -> list[dict]:
    with Session(engine) as s:
        rows = s.scalars(select(Whitelist).order_by(Whitelist.id)).all()
        return [{"id": w.id, "username": w.username, "note": w.note} for w in rows]


def remove_whitelist(username: str) -> int:
    with Session(engine) as s:
        n = s.execute(delete(Whitelist).where(Whitelist.username == username)).rowcount
        s.commit()
    return n


# ── kb 成员（资源角色）──
def get_kb_role(kb_id: int, user_id: int) -> str | None:
    with Session(engine) as s:
        m = s.scalar(select(KbMember).where(KbMember.kb_id == kb_id,
                                            KbMember.user_id == user_id))
        return m.role if m else None


def add_kb_member(kb_id: int, user_id: int, role: str) -> None:
    """upsert：不存在则新增，存在则改角色（reader→editor 等）。"""
    with Session(engine) as s:
        m = s.scalar(select(KbMember).where(KbMember.kb_id == kb_id,
                                            KbMember.user_id == user_id))
        if m is None:
            s.add(KbMember(kb_id=kb_id, user_id=user_id, role=role))
        else:
            m.role = role
        s.commit()


def remove_kb_member(kb_id: int, user_id: int) -> int:
    with Session(engine) as s:
        n = s.execute(delete(KbMember).where(KbMember.kb_id == kb_id,
                                             KbMember.user_id == user_id)).rowcount
        s.commit()
    return n


def list_kb_members(kb_id: int) -> list[dict]:
    with Session(engine) as s:
        rows = s.execute(
            select(KbMember.user_id, KbMember.role, User.username)
            .join(User, User.id == KbMember.user_id)
            .where(KbMember.kb_id == kb_id)
            .order_by(KbMember.id)
        ).all()
        return [{"user_id": r.user_id, "username": r.username, "role": r.role} for r in rows]


def list_visible_kb_ids(user_id: int) -> list[int]:
    with Session(engine) as s:
        rows = s.scalars(select(KbMember.kb_id).where(KbMember.user_id == user_id)).all()
        return list(rows)


def get_kb_owners(kb_ids: list[int]) -> dict[int, str]:
    """批量取 {kb_id: owner_username}，一次查询。"""
    if not kb_ids:
        return {}
    with Session(engine) as s:
        rows = s.execute(
            select(KbMember.kb_id, User.username)
            .join(User, User.id == KbMember.user_id)
            .where(KbMember.kb_id.in_(kb_ids), KbMember.role == "owner")
        ).all()
        return {r.kb_id: r.username for r in rows}


# ── API Key ──
def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_api_key(user_id: int, name: str = "") -> dict:
    """签发新 key。返回含明文(plain)的 dict —— 明文只此一次，不再可取。"""
    raw = "sk-" + secrets.token_hex(32)
    prefix = raw[:12]
    with Session(engine) as s:
        k = ApiKey(user_id=user_id, name=name or "", key_prefix=prefix,
                   key_hash=_hash_key(raw))
        s.add(k)
        s.commit()
        return {"id": k.id, "name": k.name, "key_prefix": prefix, "plain": raw}


def list_api_keys(user_id: int) -> list[dict]:
    """列某用户的 key（不含明文/哈希）。revoked=吊销时间(None 表示有效)。"""
    with Session(engine) as s:
        rows = s.scalars(
            select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.id)
        ).all()
        return [{"id": k.id, "name": k.name, "key_prefix": k.key_prefix,
                 "revoked": k.revoked_at.isoformat() if k.revoked_at else None,
                 "created_at": k.created_at.isoformat() if k.created_at else None}
                for k in rows]


def get_user_by_api_key(raw: str) -> dict | None:
    """认证用：拿 key 明文反查属主 user。无效/已吊销 → None。"""
    h = _hash_key(raw)
    with Session(engine) as s:
        k = s.scalar(select(ApiKey).where(ApiKey.key_hash == h))
        if k is None or k.revoked_at is not None:
            return None
        u = s.get(User, k.user_id)
        return _user_dict(u) if u else None


def revoke_api_key(key_id: int, user_id: int) -> bool:
    """吊销 key（标记 revoked_at）。只能吊销自己的；不存在/非本人 → False。"""
    with Session(engine) as s:
        k = s.get(ApiKey, key_id)
        if k is None or k.user_id != user_id:
            return False
        if k.revoked_at is None:
            k.revoked_at = datetime.now(timezone.utc)
            s.commit()
        return True


# -- 审计日志 --
def write_audit(action, user_id=None, username="", kb_id=None, target=None, ip=None):
    """写一条审计。容错：审计失败绝不影响主流程(吞异常仅记日志)。"""
    try:
        with Session(engine) as s:
            s.add(AuditLog(action=action, user_id=user_id, username=username or "",
                           kb_id=kb_id, target=target, ip=ip))
            s.commit()
    except Exception as e:
        from loguru import logger
        logger.warning("审计写入失败(不影响主流程): {}", e)


def _parse_date(label: str, value: str | None):
    """安全解析 ISO 日期字符串。非法值返回 None 并记警告。"""
    if not value:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError) as e:
        from loguru import logger
        logger.warning("审计日期参数 {}={!r} 非法，已忽略: {}", label, value, e)
        return None


def query_audit(kb_id=None, action=None, user=None, limit=100, offset=0,
                date_from=None, date_to=None):
    """查审计。支持分页(limit/offset)和日期范围过滤。返回 (items, total)。"""
    from sqlalchemy import func
    with Session(engine) as s:
        base = select(AuditLog)
        if kb_id is not None:
            base = base.where(AuditLog.kb_id == kb_id)
        if action:
            base = base.where(AuditLog.action == action)
        if user:
            base = base.where(AuditLog.username == user)
        dt_from = _parse_date("date_from", date_from)
        if dt_from is not None:
            base = base.where(AuditLog.created_at >= dt_from)
        dt_to = _parse_date("date_to", date_to)
        if dt_to is not None:
            base = base.where(AuditLog.created_at <= dt_to)
        # 总数
        total = s.scalar(select(func.count()).select_from(base.subquery()))
        # 分页查询
        stmt = base.order_by(AuditLog.id.desc()).limit(limit).offset(offset)
        rows = s.scalars(stmt).all()
        items = [{"id": a.id, "username": a.username, "action": a.action,
                  "kb_id": a.kb_id, "target": a.target, "ip": a.ip,
                  "created_at": a.created_at.isoformat() if a.created_at else None}
                 for a in rows]
        return items, total or 0
