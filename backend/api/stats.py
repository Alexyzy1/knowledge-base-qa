"""仪表盘统计 API。
GET /api/stats/dashboard?days=30
- super_admin：全量统计
- admin/user：只看自己有权限的知识库（通过 kb_member）
- guest：返回空数据
"""
from datetime import datetime, timedelta, date
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from loguru import logger
from backend.core.response import success
from backend.core.deps import get_current_user
from backend.store.engine import SessionLocal
from backend.store import auth_store

router = APIRouter(prefix="/api", tags=["stats"])


def _visible_kb_ids(user: dict) -> list[int] | None:
    """非 super_admin 用户返回可访问的 kb_id 列表；super_admin 返回 None 表示全量。"""
    if user["role"] == "super_admin":
        return None
    return auth_store.list_visible_kb_ids(user["id"])


def _kb_filter_sql(kb_ids: list[int] | None, column: str = "kb_id") -> tuple[str, dict]:
    """生成参数化 SQL 过滤条件片段。返回 (sql_fragment, params_dict)。
    kb_ids 为 None 表示全量（1=1），空列表表示无权限（1=0）。
    column 参数硬编码，不接受用户输入。
    """
    if kb_ids is None:
        return "1=1", {}
    if not kb_ids:
        return "1=0", {}
    placeholders = ", ".join(f":kb_id_{i}" for i in range(len(kb_ids)))
    params = {f"kb_id_{i}": kid for i, kid in enumerate(kb_ids)}
    return f"{column} IN ({placeholders})", params


def _conv_kb_filter_sql(kb_ids: list[int] | None) -> tuple[str, dict]:
    """对 conversation.kb_ids（逗号分隔字符串）生成参数化过滤片段。
    精确匹配位置：避免 LIKE '%1%' 误匹配 "11,21" 等。
    返回 (sql_fragment, params_dict)。
    """
    if kb_ids is None:
        return "1=1", {}
    if not kb_ids:
        return "1=0", {}
    parts = []
    params = {}
    for i, kid in enumerate(kb_ids):
        pk = f"kb_{i}"
        params[pk] = str(kid)
        pk_like = f"kb_like_{i}"
        params[pk_like] = f"{kid},%"
        pk_like_mid = f"kb_like_mid_{i}"
        params[pk_like_mid] = f"%,{kid},%"
        pk_like_end = f"kb_like_end_{i}"
        params[pk_like_end] = f"%,{kid}"
        parts.append(
            f"(c.kb_ids = :{pk} OR "
            f"c.kb_ids LIKE :{pk_like} OR "
            f"c.kb_ids LIKE :{pk_like_mid} OR "
            f"c.kb_ids LIKE :{pk_like_end})"
        )
    return "(" + " OR ".join(parts) + ")", params


def _merge_params(*dicts: dict) -> dict:
    """合并多个参数字典。"""
    result = {}
    for d in dicts:
        result.update(d)
    return result


@router.get("/stats/dashboard")
def dashboard(
    days: int = Query(30, ge=1, le=365, description="统计时间范围（天）"),
    current: dict = Depends(get_current_user),
):
    """返回仪表盘核心统计数据。"""
    if current["role"] == "guest":
        return success({
            "overview": {"total_users": 0, "total_kbs": 0, "total_documents": 0,
                         "total_qa_messages": 0, "total_conversations": 0},
            "qa_trend": [],
            "top_active_users": [],
            "kb_usage": [],
            "doc_status_distribution": {},
            "daily_active_users": 0,
        })

    kb_ids = _visible_kb_ids(current)
    kb_filter_sql, kb_params = _kb_filter_sql(kb_ids)
    conv_filter_sql, conv_params = _conv_kb_filter_sql(kb_ids)
    cutoff = datetime.now() - timedelta(days=days)
    today_start = datetime.combine(date.today(), datetime.min.time())

    with SessionLocal() as s:
        # ── 概览卡片 ──
        # 总用户（始终全量，不按知识库范围限制）
        total_users = s.execute(text("SELECT COUNT(*) FROM user")).scalar() or 0

        # 总知识库
        if kb_ids is None:
            total_kbs = s.execute(text("SELECT COUNT(*) FROM knowledge_base")).scalar() or 0
        else:
            total_kbs = len(kb_ids)

        # 总文档（参数化）
        total_docs = s.execute(text(
            f"SELECT COUNT(*) FROM document WHERE {kb_filter_sql}"
        ), kb_params).scalar() or 0

        # 总问答消息数（限定时间范围和 KB 范围）
        msg_params = _merge_params({"cutoff": cutoff}, conv_params)
        total_qa = s.execute(text(f"""
            SELECT COUNT(*) FROM message m
            JOIN conversation c ON m.conversation_id = c.id
            WHERE m.role = 'user' AND m.created_at >= :cutoff AND {conv_filter_sql}
        """), msg_params).scalar() or 0

        # 总对话数
        total_convs = s.execute(text(f"""
            SELECT COUNT(*) FROM conversation c
            WHERE c.created_at >= :cutoff AND {conv_filter_sql}
        """), msg_params).scalar() or 0

        # ── 问答趋势（按天统计用户消息数）──
        qa_rows = s.execute(text(f"""
            SELECT DATE(m.created_at) AS dt, COUNT(*) AS cnt
            FROM message m
            JOIN conversation c ON m.conversation_id = c.id
            WHERE m.role = 'user' AND m.created_at >= :cutoff AND {conv_filter_sql}
            GROUP BY dt ORDER BY dt
        """), msg_params).all()
        qa_trend = [{"date": str(r.dt), "count": r.cnt} for r in qa_rows]

        # ── 活跃用户 Top 10 ──
        user_rows = s.execute(text(f"""
            SELECT u.id AS user_id, u.username, COUNT(*) AS message_count
            FROM message m
            JOIN conversation c ON m.conversation_id = c.id
            JOIN user u ON c.user_id = u.id
            WHERE m.role = 'user' AND m.created_at >= :cutoff AND {conv_filter_sql}
            GROUP BY u.id, u.username
            ORDER BY message_count DESC LIMIT 10
        """), msg_params).all()
        top_users = [{"user_id": r.user_id, "username": r.username,
                       "message_count": r.message_count} for r in user_rows]

        # ── 知识库使用详情 ──
        # 文档数：直接按 kb_id 统计（参数化）
        doc_rows = s.execute(text(f"""
            SELECT kb_id, COUNT(*) AS doc_count
            FROM document WHERE {kb_filter_sql}
            GROUP BY kb_id
        """), kb_params).all()
        doc_map = {r.kb_id: r.doc_count for r in doc_rows}

        # 问答数：通过 conversation 关联（参数化）
        qa_by_kb_rows = s.execute(text(f"""
            SELECT c.kb_ids, COUNT(*) AS msg_count
            FROM message m
            JOIN conversation c ON m.conversation_id = c.id
            WHERE m.role = 'user' AND m.created_at >= :cutoff AND {conv_filter_sql}
            GROUP BY c.kb_ids
        """), msg_params).all()

        # 合并 kb_usage：汇总每个 kb_id 的文档数和问答数
        kb_usage_map: dict[int, dict] = {}
        # 先填入文档数
        for kb_id_str, doc_cnt in doc_map.items():
            kb_usage_map[int(kb_id_str)] = {"kb_id": int(kb_id_str), "doc_count": doc_cnt, "message_count": 0}

        # 再累加问答数（kb_ids 可能包含多个，如 "1,2,3"）
        for kb_ids_str, msg_cnt in qa_by_kb_rows:
            if kb_ids_str:
                for part in kb_ids_str.split(","):
                    part = part.strip()
                    if part.isdigit():
                        kid = int(part)
                        if kid not in kb_usage_map:
                            kb_usage_map[kid] = {"kb_id": kid, "doc_count": 0, "message_count": 0}
                        kb_usage_map[kid]["message_count"] += msg_cnt

        # 批量取 KB 名称（参数化）
        all_kb_ids = list(kb_usage_map.keys())
        kb_names = {}
        if all_kb_ids:
            name_placeholders = ", ".join(f":nid_{i}" for i in range(len(all_kb_ids)))
            name_params = {f"nid_{i}": kid for i, kid in enumerate(all_kb_ids)}
            name_rows = s.execute(text(
                f"SELECT id, name FROM knowledge_base WHERE id IN ({name_placeholders})"
            ), name_params).all()
            kb_names = {r.id: r.name for r in name_rows}

        kb_usage = []
        for kid, info in kb_usage_map.items():
            info["kb_name"] = kb_names.get(kid, f"KB#{kid}")
            kb_usage.append(info)
        kb_usage.sort(key=lambda x: x["message_count"] + x["doc_count"], reverse=True)

        # ── 文档状态分布（参数化）──
        status_rows = s.execute(text(f"""
            SELECT status, COUNT(*) AS cnt
            FROM document WHERE {kb_filter_sql}
            GROUP BY status
        """), kb_params).all()
        doc_status = {r.status: r.cnt for r in status_rows}

        # ── 今日活跃用户数（参数化）──
        dau_params = _merge_params({"today": today_start}, conv_params)
        dau = s.execute(text(f"""
            SELECT COUNT(DISTINCT c.user_id)
            FROM message m
            JOIN conversation c ON m.conversation_id = c.id
            WHERE m.role = 'user' AND m.created_at >= :today AND {conv_filter_sql}
        """), dau_params).scalar() or 0

    return success({
        "overview": {
            "total_users": total_users,
            "total_kbs": total_kbs,
            "total_documents": total_docs,
            "total_qa_messages": total_qa,
            "total_conversations": total_convs,
        },
        "qa_trend": qa_trend,
        "top_active_users": top_users,
        "kb_usage": kb_usage,
        "doc_status_distribution": doc_status,
        "daily_active_users": dau,
    })
