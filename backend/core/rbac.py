"""RBAC 两轴判定：全局角色层级 × 每库资源角色。
失败抛 ForbiddenError，由 main.py 的处理器转成统一 {code:403}（HTTP 200，与其他业务错误一致）。
"""
from backend.store.auth_models import ROLE_LEVEL
from backend.store import auth_store

KB_ROLE_LEVEL = {"reader": 0, "editor": 1, "owner": 2}


class ForbiddenError(Exception):
    def __init__(self, msg: str = "权限不足"):
        self.msg = msg
        super().__init__(msg)


def require_global(user: dict, min_role: str) -> None:
    """全局层级判定（系统级操作用）。"""
    if ROLE_LEVEL.get(user["role"], -1) < ROLE_LEVEL[min_role]:
        raise ForbiddenError(f"需要 {min_role} 及以上权限")


def require_kb_role(user: dict, kb_id: int, need: str) -> None:
    """资源角色判定：super_admin 万能钥匙旁路，否则看 kb_member。"""
    if user["role"] == "super_admin":
        return
    role = auth_store.get_kb_role(kb_id, user["id"])
    if role is None or KB_ROLE_LEVEL[role] < KB_ROLE_LEVEL[need]:
        raise ForbiddenError(f"对该知识库需要 {need} 及以上权限")


def require_kb_roles(user: dict, kb_ids: list[int], need: str) -> None:
    """多库资源角色判定：对列表中的每个库校验权限。
    super_admin 直接放行；否则逐库查 kb_member，首个没权限的抛 ForbiddenError。"""
    if user["role"] == "super_admin":
        return
    for kid in kb_ids:
        require_kb_role(user, kid, need)
