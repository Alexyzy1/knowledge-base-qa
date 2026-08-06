import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from backend.core.logger import setup_logger
from backend.core.response import success, fail
from backend.api import kb as kb_api
from backend.api import document as doc_api
from backend.api import chat as chat_api
from backend.api import auth as auth_api
from backend.api import account as account_api
from backend.api import share as share_api
from backend.api import audit as audit_api
from backend.api import member as member_api
from backend.api import models as models_api
from backend.api import folder as folder_api
from backend.api import task as task_api
from backend.api import conversation as conv_api
from backend.api import stats as stats_api
from backend.api import kb_export as kb_export_api
from backend.api import kb_import as kb_import_api
from backend.core.deps import get_current_user
from backend.core.rbac import ForbiddenError
from backend.core.rate_limit import ip_rate_limit_middleware, user_chat_rate_limit, get_debug_stats as rate_limit_stats
logger = setup_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI 启动中…")
    # ── Schema 迁移：确保新增字段存在（幂等，跳过已存在的列）──
    try:
        from backend.store.engine import engine as _eng
        from sqlalchemy import text as _text, inspect as _inspect
        import asyncio as _asyncio
        def _migrate():
            inspector = _inspect(_eng)
            cols = {c["name"] for c in inspector.get_columns("user")}
            if "token_version" not in cols:
                with _eng.begin() as _conn:
                    _conn.execute(_text(
                        "ALTER TABLE `user` ADD COLUMN `token_version` INT NOT NULL DEFAULT 0"))
                logger.info("Schema 迁移：user 表已添加 token_version 列")
            else:
                logger.debug("Schema 迁移：token_version 列已存在，跳过")
        await _asyncio.to_thread(_migrate)
    except Exception as e:
        logger.error("Schema 迁移异常（不阻塞启动）: {}", e)
    # ── 启动恢复：扫描卡在 "processing" 的文档（服务器重启/崩溃导致 BackgroundTasks 丢失），
    # 重置为 "failed" 以便用户通过任务中心重试。
    try:
        from backend.store import mysql_store as _db
        stuck = _db.reset_stuck_documents()
        if stuck:
            logger.warning("启动恢复：将 {} 个卡在 processing 的文档重置为 failed: {}",
                           len(stuck), stuck)
        else:
            logger.info("启动恢复：无卡住的 processing 文档")
    except Exception as e:
        logger.error("启动恢复异常（不阻塞启动）: {}", e)
    yield
    logger.info("FastAPI 关闭。")


app = FastAPI(title="知识库问答系统", version="0.1.0", lifespan=lifespan)

# IP 级限流中间件（注册在最外层，所有请求都经过）
app.middleware("http")(ip_rate_limit_middleware)

app.include_router(kb_api.router, dependencies=[Depends(get_current_user)])
app.include_router(doc_api.router, dependencies=[Depends(get_current_user)])
app.include_router(doc_api.raw_router)  # 二进制端点：lax 认证，不挂组级严格依赖
# chat 路由：先做用户级限流（内嵌 get_current_user），再进入端点
app.include_router(chat_api.router, dependencies=[Depends(user_chat_rate_limit)])
app.include_router(auth_api.router)
app.include_router(account_api.router)  # 端点级登录校验，不挂组级
app.include_router(account_api.keys_router)  # API Key 管理，端点级登录校验
app.include_router(share_api.router, dependencies=[Depends(get_current_user)])  # 分享管理：需登录
app.include_router(share_api.public_router)  # 公开只读：免登录，不挂组级依赖
app.include_router(share_api.auth_router, dependencies=[Depends(get_current_user)])  # 分享导入：需登录
app.include_router(audit_api.router, dependencies=[Depends(get_current_user)])  # 审计查询：需登录，端点内再校验 owner/super_admin
app.include_router(member_api.router, dependencies=[Depends(get_current_user)])
app.include_router(models_api.router, dependencies=[Depends(get_current_user)])
app.include_router(folder_api.router, dependencies=[Depends(get_current_user)])
app.include_router(task_api.router, dependencies=[Depends(get_current_user)])
app.include_router(conv_api.router, dependencies=[Depends(get_current_user)])
app.include_router(stats_api.router, dependencies=[Depends(get_current_user)])
app.include_router(kb_export_api.router, dependencies=[Depends(get_current_user)])
app.include_router(kb_import_api.router, dependencies=[Depends(get_current_user)])
FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "index.html"


@app.get("/")
async def index():
    return FileResponse(FRONTEND)


# 静态文件：前端 CSS/JS 等资源
_frontend_dir = FRONTEND.parent
_css_dir = _frontend_dir / "css"
if _css_dir.is_dir():
    app.mount("/css", StaticFiles(directory=str(_css_dir)), name="css")
_js_dir = _frontend_dir / "js"
if _js_dir.is_dir():
    app.mount("/js", StaticFiles(directory=str(_js_dir)), name="js")


# ── SPA fallback: serve index.html for unmatched routes ──
# Must be registered AFTER all app routes, API routers, and StaticFiles mounts
# so they take priority.  Only falls through if nothing above matched.
@app.get("/{path:path}")
async def spa_fallback(path: str):
    return FileResponse(FRONTEND)


@app.exception_handler(ForbiddenError)
async def forbidden_handler(request: Request, exc: ForbiddenError):
    logger.warning("权限拒绝 {} {} query={}: {}",
                   request.method, request.url.path,
                   str(request.query_params), exc.msg)
    return fail(code=403, msg=exc.msg)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """把 FastAPI 内置异常（如 429 限流、401 认证）转成项目统一 JSON 格式。"""
    if exc.status_code == 429:
        logger.warning("限流返回 429 {} {} detail={}",
                       request.method, request.url.path, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "msg": str(exc.detail), "data": None},
        headers=dict(exc.headers) if exc.headers else {},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # 生成短 request_id，方便用户截屏后运维在日志中定位
    req_id = str(uuid.uuid4())[:8]
    # 尽量记录完整上下文
    try:
        body = await request.body()
        body_str = body.decode("utf-8", errors="replace")[:500] if body else ""
    except Exception:
        body_str = "(无法读取请求体)"
    logger.opt(exception=exc).error(
        "未处理异常 [{}] {} {} query={} body={}",
        req_id, request.method, request.url.path,
        str(request.query_params), body_str,
    )
    return JSONResponse(
        status_code=200,
        content={"code": 500, "msg": f"服务器内部错误 (Ref: {req_id})", "data": None},
    )


@app.get("/api/health")
async def health():
    """深度健康检查：MySQL / Milvus / LLM API 逐一探测。
    全部 ok → healthy，任一失败 → degraded + 详情。"""
    import asyncio
    from sqlalchemy import text
    from backend.store.engine import engine as _db_engine
    from backend.store.milvus_store import client as _milvus_client
    from backend.core.llm_client import _client as _llm_client

    checks: dict[str, str] = {}

    # 1) MySQL（同步操作 → to_thread）
    try:
        def _check_mysql():
            with _db_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        await asyncio.to_thread(_check_mysql)
        checks["mysql"] = "ok"
    except Exception as e:
        checks["mysql"] = f"error: {e}"

    # 2) Milvus（同步操作 → to_thread）
    try:
        await asyncio.to_thread(_milvus_client.list_collections)
        checks["milvus"] = "ok"
    except Exception as e:
        checks["milvus"] = f"error: {e}"

    # 3) LLM API（异步，快速列出模型即证明连通）
    try:
        await _llm_client.models.list()
        checks["llm"] = "ok"
    except Exception as e:
        checks["llm"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    return success({"status": "healthy" if all_ok else "degraded", "checks": checks})


@app.get("/api/debug/rate-limits")
def debug_rate_limits(user: dict = Depends(get_current_user)):
    """限流状态调试端点（仅 super_admin）。"""
    if user.get("role") != "super_admin":
        return fail(code=403, msg="仅 super_admin 可查看")
    return success(rate_limit_stats())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)
