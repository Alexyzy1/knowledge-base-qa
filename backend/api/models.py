"""模型注册表接口：DB 版(model 表)。
- GET  /api/models            管理页全量(含停用)，登录即可看
- GET  /api/models?type=llm   下拉数据源，只返 enabled
- POST /api/models            新增(admin)
- PUT  /api/models/{id}       部分更新/启停(admin)
前端契约：{id, name, type, endpoint, enabled}。无 DELETE(前端只有启停)。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from loguru import logger
from backend.store import mysql_store as db
from backend.core.response import success, fail
from backend.core.deps import get_current_user
from backend.core import rbac

router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("")
def list_models(type: str | None = None, user: dict = Depends(get_current_user)):
    # 带 type=下拉场景，只给启用的；不带 type=管理页，给全量(含停用)
    only_enabled = type is not None
    return success(db.list_models(type=type, only_enabled=only_enabled))


class CreateModelRequest(BaseModel):
    name: str
    type: str = "llm"
    endpoint: str | None = None
    enabled: bool = True


@router.post("")
def create_model(req: CreateModelRequest, user: dict = Depends(get_current_user)):
    rbac.require_global(user, "admin")               # 模型注册表由 admin 维护
    mid = db.create_model(req.name, req.type, req.endpoint, req.enabled)
    logger.info("用户 {} 新增模型 id={} name={} type={}", user["username"], mid, req.name, req.type)
    return success(db.get_model(mid))


class UpdateModelRequest(BaseModel):
    name: str | None = None
    type: str | None = None
    endpoint: str | None = None
    enabled: bool | None = None


@router.put("/{model_id}")
def update_model(model_id: int, req: UpdateModelRequest,
                 user: dict = Depends(get_current_user)):
    rbac.require_global(user, "admin")
    body = req.model_dump(exclude_unset=True)        # 只改前端真正传的字段(启停只送 enabled)
    ok = db.update_model(model_id, body)
    if not ok:
        return fail(code=404, msg="模型不存在")
    logger.info("用户 {} 更新模型 id={}: {}", user["username"], model_id, list(body))
    return success(db.get_model(model_id))
