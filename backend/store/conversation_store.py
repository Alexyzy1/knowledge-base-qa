"""对话记录持久化存储：conversation + message 表。
与 mysql_store / auth_store 共享 backend.store.engine，函数式接口。
"""
import json
from datetime import datetime
from sqlalchemy import (String, Text, Integer, BigInteger,
                        DateTime, ForeignKey, func, select, update, delete, or_)
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column)
from loguru import logger
from backend.store.engine import engine, SessionLocal


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversation"
    __table_args__ = {"mysql_charset": "utf8mb4"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    kb_ids: Mapped[str | None] = mapped_column(String(512), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Message(Base):
    __tablename__ = "message"
    __table_args__ = {"mysql_charset": "utf8mb4"}
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sources: Mapped[str | None] = mapped_column(Text, nullable=True)
    thinking: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


def create_tables():
    """初始化 conversation / message 表（幂等）。"""
    Base.metadata.create_all(engine)
    logger.info("conversation / message 表已就绪")


# ── Conversation CRUD ──

def create_conversation(user_id: int, kb_ids: str | None, title: str) -> int:
    with SessionLocal() as s:
        conv = Conversation(user_id=user_id, kb_ids=kb_ids, title=title[:80])
        s.add(conv); s.flush(); conv_id = conv.id; s.commit()
    logger.info("创建 conversation id={} user_id={} title={}", conv_id, user_id, title[:40])
    return conv_id


def get_conversation(conv_id: int) -> dict | None:
    with SessionLocal() as s:
        c = s.get(Conversation, conv_id)
        return None if c is None else _conv_dict(c)


def list_conversations(user_id: int, kb_id: int | None = None,
                       limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    """按 updated_at 倒序。kb_id 可选过滤（匹配 kb_ids 以逗号分隔的列表）。"""
    with SessionLocal() as s:
        base = select(Conversation).where(Conversation.user_id == user_id)
        if kb_id is not None:
            # kb_ids 存 "1,2,3" 格式，精确匹配位置（避免 LIKE '%1%' 误匹配 "11,21"）
            kid = str(kb_id)
            base = base.where(or_(
                Conversation.kb_ids == kid,
                Conversation.kb_ids.like(f"{kid},%"),
                Conversation.kb_ids.like(f"%,{kid},%"),
                Conversation.kb_ids.like(f"%,{kid}"),
            ))
        # 总数
        total = s.scalar(select(func.count()).select_from(base.subquery())) or 0
        stmt = base.order_by(Conversation.updated_at.desc()).limit(limit).offset(offset)
        rows = s.execute(stmt).scalars().all()
        items = [_conv_dict(c) for c in rows]
        return items, total


def update_conversation_title(conv_id: int, title: str) -> bool:
    with SessionLocal() as s:
        c = s.get(Conversation, conv_id)
        if c is None:
            return False
        c.title = title[:80]
        s.commit()
    return True


def delete_conversation(conv_id: int) -> int:
    """删 conversation（级联删 messages，由 FK ondelete CASCADE 保证）。返回删除行数。"""
    with SessionLocal() as s:
        n = s.execute(delete(Conversation).where(Conversation.id == conv_id)).rowcount
        s.commit()
    logger.info("删除 conversation id={} 影响行数={}", conv_id, n)
    return n


def touch_conversation(conv_id: int):
    """刷新 updated_at 到当前时间（有新消息时调用）。"""
    with SessionLocal() as s:
        s.execute(update(Conversation).where(Conversation.id == conv_id)
                  .values(updated_at=datetime.now()))
        s.commit()


# ── Message CRUD ──

def add_message(conv_id: int, role: str, content: str,
                model: str | None = None, sources: str | None = None,
                thinking: str | None = None) -> int:
    with SessionLocal() as s:
        msg = Message(conversation_id=conv_id, role=role, content=content,
                      model=model, sources=sources, thinking=thinking)
        s.add(msg); s.flush(); msg_id = msg.id; s.commit()
    logger.debug("添加 message id={} conv={} role={} len={}", msg_id, conv_id, role, len(content))
    return msg_id


def get_messages(conv_id: int) -> list[dict]:
    with SessionLocal() as s:
        rows = s.execute(
            select(Message).where(Message.conversation_id == conv_id)
            .order_by(Message.id)
        ).scalars().all()
        return [_msg_dict(m) for m in rows]


def get_recent_history(conv_id: int, max_turns: int = 6) -> list[dict]:
    """取最近 N 对对话（user+assistant），用于 LLM history 上下文。
    返回 [{"role": "user", "content": "..."}, ...] 格式。
    """
    with SessionLocal() as s:
        rows = s.execute(
            select(Message).where(Message.conversation_id == conv_id)
            .order_by(Message.id.desc()).limit(max_turns * 2)
        ).scalars().all()
    # 倒序取回，反转成时间正序
    rows = list(reversed(rows))
    return [{"role": m.role, "content": m.content} for m in rows
            if m.role in ("user", "assistant") and m.content.strip()]


def count_messages(conv_id: int) -> int:
    with SessionLocal() as s:
        return s.scalar(
            select(func.count()).select_from(Message)
            .where(Message.conversation_id == conv_id)
        ) or 0


# ── helpers ──

def _conv_dict(c: Conversation) -> dict:
    kb_ids = None
    if c.kb_ids:
        try:
            kb_ids = [int(x) for x in c.kb_ids.split(",") if x.strip().isdigit()]
        except Exception:
            kb_ids = None
    return {
        "id": c.id,
        "user_id": c.user_id,
        "kb_ids": kb_ids,
        "title": c.title,
        "message_count": count_messages(c.id),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _msg_dict(m: Message) -> dict:
    sources = None
    if m.sources:
        try:
            sources = json.loads(m.sources)
        except Exception:
            sources = None
    return {
        "id": m.id,
        "conversation_id": m.conversation_id,
        "role": m.role,
        "content": m.content,
        "model": m.model,
        "sources": sources,
        "thinking": m.thinking,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }
