"""审计查询接口。
- GET /api/kb/{id}/audit  库级，仅该库 owner（super_admin 旁路）。
- GET /api/audit          全局，仅 super_admin。
权限墙在后端硬校验：前端的 isOwner/super_admin 判断只是 UI，绕过前端也拦得住。
返回 {items:[...]}，每条含 created_at/username/action/target(+全局含 kb_name)。
"""
import re
from fastapi import APIRouter, Depends
from backend.store import auth_store as astore
from backend.store import mysql_store as db
from backend.core.response import success
from backend.core.deps import get_current_user
from backend.core import rbac

router = APIRouter(prefix="/api", tags=["audit"])

# kb_name 缓存（查询时给每条记录补知识库名，前端全局审计要显示）
def _enrich_kb_name(items: list[dict]) -> list[dict]:
    cache: dict[int, str] = {}
    for it in items:
        kid = it.get("kb_id")
        if kid is None:
            it["kb_name"] = None
            continue
        if kid not in cache:
            basic = db.get_kb_basic(kid)
            cache[kid] = basic["name"] if basic else None
        it["kb_name"] = cache[kid]
    return items

# target 格式化缓存：把旧数据 "doc:42" 还原为实际文件名
_doc_name_cache: dict[int, str] = {}

def _resolve_target(items: list[dict]) -> list[dict]:
    for it in items:
        t = it.get("target", "") or ""
        m = re.match(r"^doc:(\d+)$", t)
        if m:
            doc_id = int(m.group(1))
            if doc_id not in _doc_name_cache:
                doc = db.get_document(doc_id)
                _doc_name_cache[doc_id] = doc["filename"] if doc else ("文档 #" + str(doc_id))
            it["target"] = _doc_name_cache[doc_id]
    return items


@router.get("/kb/{kb_id}/audit")
def kb_audit(kb_id: int, action: str | None = None, user: str | None = None,
             limit: int = 50, offset: int = 0,
             date_from: str | None = None, date_to: str | None = None,
             current: dict = Depends(get_current_user)):
    rbac.require_kb_role(current, kb_id, "owner")      # 仅该库 owner 可看
    items, total = astore.query_audit(kb_id=kb_id, action=action, user=user,
                                      limit=limit, offset=offset,
                                      date_from=date_from, date_to=date_to)
    return success({"items": _resolve_target(_enrich_kb_name(items)), "total": total})


@router.get("/audit")
def global_audit(action: str | None = None, user: str | None = None,
                 kb_id: int | None = None, limit: int = 50, offset: int = 0,
                 date_from: str | None = None, date_to: str | None = None,
                 current: dict = Depends(get_current_user)):
    rbac.require_global(current, "super_admin")        # 仅超管可看全局
    items, total = astore.query_audit(kb_id=kb_id, action=action, user=user,
                                      limit=limit, offset=offset,
                                      date_from=date_from, date_to=date_to)
    return success({"items": _resolve_target(_enrich_kb_name(items)), "total": total})
