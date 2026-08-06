"""对话记录管理接口：列表、详情、删除、改标题。"""
from fastapi import APIRouter, Depends, Query
from loguru import logger
from backend.store import conversation_store as store
from backend.core.response import success, fail
from backend.core.deps import get_current_user

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(
    kb_id: int | None = Query(None, description="按知识库过滤"),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
):
    items, total = store.list_conversations(user["id"], kb_id=kb_id,
                                            limit=limit, offset=offset)
    return success({"items": items, "total": total})


@router.get("/{conv_id}")
async def get_conversation(conv_id: int, user: dict = Depends(get_current_user)):
    conv = store.get_conversation(conv_id)
    if conv is None:
        return fail(404, "对话不存在")
    if conv["user_id"] != user["id"]:
        return fail(403, "无权访问此对话")
    messages = store.get_messages(conv_id)
    conv["messages"] = messages
    return success(conv)


@router.delete("/{conv_id}")
async def delete_conversation(conv_id: int, user: dict = Depends(get_current_user)):
    conv = store.get_conversation(conv_id)
    if conv is None:
        return fail(404, "对话不存在")
    if conv["user_id"] != user["id"]:
        return fail(403, "无权删除此对话")
    store.delete_conversation(conv_id)
    logger.info("用户 {} 删除 conversation id={}", user["username"], conv_id)
    return success(None)


@router.patch("/{conv_id}")
async def update_conversation_title(conv_id: int, body: dict, user: dict = Depends(get_current_user)):
    conv = store.get_conversation(conv_id)
    if conv is None:
        return fail(404, "对话不存在")
    if conv["user_id"] != user["id"]:
        return fail(403, "无权修改此对话")
    title = (body.get("title") or "").strip()
    if not title:
        return fail(400, "标题不能为空")
    store.update_conversation_title(conv_id, title)
    return success(None)
