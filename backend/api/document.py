"""文档管理接口：上传（异步入库）/ 列表+状态 / 删除（同步清两库）。
RBAC：上传/删文档需 editor，列表需 reader（super_admin 放行）。
"""
import asyncio
import csv
import html
import io
import os
import tempfile
import threading
import zipfile
from datetime import datetime, date

# 入库并发控制：保护 embedding API 和 Milvus 不被同时大量入库打爆
# 用 threading.BoundedSemaphore 而非 asyncio.Semaphore：
# _run_ingest 内部 asyncio.run() 创建新事件循环时会报
# "Semaphore is bound to a different event loop"，线程信号量跨循环安全。
_INGEST_SEMAPHORE = threading.BoundedSemaphore(3)

from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, Depends, Request
from pydantic import BaseModel, model_validator
from fastapi.responses import FileResponse, StreamingResponse, HTMLResponse
from loguru import logger

from backend.store import mysql_store as db
from backend.store import auth_store as astore
from backend.store import milvus_store
from backend.ingest.ingest_pipeline import ingest_document
from backend.core.response import success, fail
from backend.core.deps import get_current_user, get_current_user_lax, get_client_ip
from backend.core import rbac

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STORAGE_ROOT = _PROJECT_ROOT / "storage"
_MIME = {
    ".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    # 音频
    ".mp3": "audio/mpeg", ".flac": "audio/flac", ".wav": "audio/wav",
    ".aac": "audio/aac", ".m4a": "audio/mp4", ".ogg": "audio/ogg",
    ".opus": "audio/opus", ".wma": "audio/x-ms-wma", ".amr": "audio/amr",
    # 视频
    ".mp4": "video/mp4", ".avi": "video/x-msvideo", ".mov": "video/quicktime",
    ".mkv": "video/x-matroska", ".flv": "video/x-flv", ".wmv": "video/x-ms-wmv",
    ".webm": "video/webm", ".mpeg": "video/mpeg", ".mpg": "video/mpeg",
    ".3gp": "video/3gpp", ".m4v": "video/x-m4v",
}


# ── Pydantic request models ──

class UpdateTagsRequest(BaseModel):
    tags: list[str] = []


class BatchDeleteRequest(BaseModel):
    doc_ids: list[int]

    @model_validator(mode='after')
    def check_not_empty(self):
        if not self.doc_ids:
            raise ValueError('doc_ids 不能为空')
        return self


class BatchTagsRequest(BaseModel):
    doc_ids: list[int]
    action: str = "set"
    tags: list[str] = []

    @model_validator(mode='after')
    def check_valid(self):
        if not self.doc_ids:
            raise ValueError('doc_ids 不能为空')
        if self.action not in ("set", "add", "remove"):
            raise ValueError('action 必须是 set / add / remove 之一')
        return self


class BatchMoveRequest(BaseModel):
    doc_ids: list[int]
    folder_id: int | None = None

    @model_validator(mode='after')
    def check_not_empty(self):
        if not self.doc_ids:
            raise ValueError('doc_ids 不能为空')
        return self


class BatchDownloadRequest(BaseModel):
    doc_ids: list[int]

    @model_validator(mode='after')
    def check_not_empty(self):
        if not self.doc_ids:
            raise ValueError('doc_ids 不能为空')
        return self


class CreateNoteRequest(BaseModel):
    title: str
    content: str = ""
    folder_id: int | None = None


def _safe_ext(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    return ext if (ext and ext[1:].isalnum()) else ""


def _store_original_bytes(data: bytes, kb_id: int, doc_id: int, filename: str) -> dict:
    """把上传的原文件 bytes 落盘到 storage/{kb_id}/{doc_id}{ext}，返回回填信息（路径相对项目根）。"""
    ext = _safe_ext(filename)
    kb_dir = _STORAGE_ROOT / str(int(kb_id))
    kb_dir.mkdir(parents=True, exist_ok=True)
    dest = kb_dir / f"{int(doc_id)}{ext}"
    dest.write_bytes(data)
    rel = str(dest.relative_to(_PROJECT_ROOT))
    return {"storage_path": rel, "size": len(data),
            "mime": _MIME.get(ext, "application/octet-stream")}


router = APIRouter(prefix="/api", tags=["document"])
# 二进制端点专用：浏览器直发(iframe/img/window.open)带不上 header，
# 故走 lax 认证(?token=)。必须独立 router，否则会被 main.py 的组级严格依赖覆盖。
raw_router = APIRouter(prefix="/api", tags=["document-raw"])


def _run_ingest(path: str, kb_id: int, doc_id: int,
                task_id: int | None = None, delete_after: bool = True,
                filename: str = ""):
    """BackgroundTasks 的同步包装：在新事件循环里跑异步入库管线。

    ingest_document 内部已自管状态(processing→done/failed)且自回滚 Milvus，
    这里再套一层兜底：万一 asyncio.run 或管线漏网异常，强制置 failed，
    避免文档状态永久卡在 processing。
    delete_after=False 时不删源文件（retry 复用已落盘的原文件时使用）。
    """

    async def _guarded():
        _INGEST_SEMAPHORE.acquire()
        try:
            return await ingest_document(path, kb_id, doc_id, task_id=task_id, filename=filename)
        finally:
            _INGEST_SEMAPHORE.release()

    try:
        result = asyncio.run(_guarded())
        logger.info("后台入库结束 doc_id={} status={}", doc_id, result.get("status"))
    except Exception as e:
        logger.exception("后台入库包装层异常 doc_id={} task_id={}: {}", doc_id, task_id, e)
        try:
            db.update_document_status(doc_id, "failed")
            db.update_task_status(task_id, "failed", 0, str(e))
        except Exception as se:
            logger.error("兜底置 failed 也失败 doc_id={}: {}", doc_id, se)
    finally:
        if delete_after:
            try:
                os.remove(path)
            except OSError:
                pass


_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


@router.post("/kb/{kb_id}/upload")
async def upload(kb_id: int, request: Request, background_tasks: BackgroundTasks,
                 file: UploadFile = File(...), folder_id: int | None = Form(None),
                 user: dict = Depends(get_current_user)):
    rbac.require_kb_role(user, kb_id, "editor")
    suffix = os.path.splitext(file.filename)[1]
    raw = await file.read()
    if len(raw) > _MAX_UPLOAD_BYTES:
        return fail(code=413, msg="文件超过 50MB 限制")
    fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="upload_")
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
    now = datetime.now()
    doc_id = db.create_document(kb_id, file.filename, "pending",
                                uploaded_by=user["username"], uploaded_at=now)
    if folder_id is not None:
        db.set_document_folder(doc_id, folder_id)
    # 原文件持久化（独立于解析入库；入库成败不影响原文件留存）
    try:
        info = _store_original_bytes(raw, kb_id, doc_id, file.filename)
        db.update_document_storage(doc_id, info["storage_path"], info["size"], info["mime"])
        logger.info("原文件已落盘 doc_id={} → {} ({} bytes)", doc_id, info["storage_path"], info["size"])
    except Exception as e:
        logger.error("原文件落盘失败 doc_id={}: {}（不阻断入库）", doc_id, e)
    task_id = db.create_task(user["id"], kb_id, doc_id, file.filename)
    astore.write_audit(action="upload_doc", user_id=user["id"], username=user["username"],
                       kb_id=kb_id, target=file.filename, ip=get_client_ip(request))
    logger.info("收到上传 kb_id={} filename={} → doc_id={} task_id={} (by {})",
                kb_id, file.filename, doc_id, task_id, user["username"])
    background_tasks.add_task(_run_ingest, tmp_path, kb_id, doc_id, task_id=task_id, filename=file.filename)
    return success({"doc_id": doc_id, "filename": file.filename,
                    "status": "pending", "task_id": task_id})


@router.get("/kb/{kb_id}/docs")
def list_docs(kb_id: int, tag: str | None = None, folder_id: int | None = None,
              user: dict = Depends(get_current_user)):
    rbac.require_kb_role(user, kb_id, "reader")
    return success(db.list_documents(kb_id, tag=tag, folder_id=folder_id))


@router.delete("/docs/{doc_id}")
def delete_doc(doc_id: int, request: Request, user: dict = Depends(get_current_user)):
    doc = db.get_document(doc_id)
    if doc is None:
        return fail(code=404, msg="文档不存在")
    rbac.require_kb_role(user, doc["kb_id"], "editor")
    milvus_ids = db.get_chunk_milvus_ids(doc_id)
    if milvus_ids:
        milvus_store.delete(ids=milvus_ids)
    n = db.delete_document(doc_id)
    astore.write_audit(action="delete_doc", user_id=user["id"], username=user["username"],
                       kb_id=doc["kb_id"], target=doc.get("filename",""), ip=get_client_ip(request))
    logger.info("用户 {} 删除文档 doc_id={}，清 Milvus {} 条，删 MySQL {} 条 chunk",
                user["username"], doc_id, len(milvus_ids), n)
    return success({"doc_id": doc_id, "deleted_milvus": len(milvus_ids), "deleted_chunks": n})


def _do_retry_doc(doc_id: int, user_id: int, username: str, kb_id: int,
                  ip: str, background_tasks: BackgroundTasks) -> dict:
    """内部：对单个文档执行重试（清理旧 chunk → 重置状态 → 重新入库）。
    返回 {"ok": True, "doc_id": ..., "task_id": ...} 或 {"ok": False, "doc_id": ..., "reason": ...}。
    """
    doc = db.get_document(doc_id)
    if doc is None:
        return {"ok": False, "doc_id": doc_id, "reason": "文档不存在"}
    if doc["kb_id"] != kb_id:
        return {"ok": False, "doc_id": doc_id, "reason": "文档不属于该知识库"}

    storage = db.get_document_storage(doc_id)
    if not storage or not storage.get("storage_path"):
        return {"ok": False, "doc_id": doc_id, "reason": "原文件不存在（持久化功能之前上传）"}

    abs_path = os.path.realpath(os.path.join(_PROJECT_ROOT, storage["storage_path"]))
    root = os.path.realpath(str(_STORAGE_ROOT))
    if not (abs_path == root or abs_path.startswith(root + os.sep)):
        return {"ok": False, "doc_id": doc_id, "reason": "原文件路径异常"}
    if not os.path.isfile(abs_path):
        return {"ok": False, "doc_id": doc_id, "reason": "原文件已丢失"}

    latest_task = db.get_latest_task_by_doc_id(doc_id)

    # 清理残余 chunk
    milvus_ids = db.get_chunk_milvus_ids(doc_id)
    if milvus_ids:
        try:
            milvus_store.delete(ids=milvus_ids)
        except Exception as e:
            logger.warning("doc retry: Milvus 清理失败 doc_id={}: {}", doc_id, e)
    db.delete_chunks_by_doc_id(doc_id)

    # 任务：复用失败任务或新建
    if latest_task and latest_task["status"] == "failed":
        task_id = latest_task["id"]
        db.update_task_status(task_id, "queued", 0, None)
    else:
        task_id = db.create_task(user_id, kb_id, doc_id,
                                 storage.get("filename", doc["filename"]))

    db.update_document_status(doc_id, "pending")

    from backend.store import auth_store as astore
    astore.write_audit(action="retry_doc", user_id=user_id, username=username,
                       kb_id=kb_id, target=doc.get("filename",""), ip=ip)
    logger.info("用户 {} 重试文档 doc_id={} task_id={}", username, doc_id, task_id)

    background_tasks.add_task(_run_ingest, abs_path, kb_id, doc_id,
                              task_id=task_id, delete_after=False,
                              filename=storage.get("filename", doc["filename"]))
    return {"ok": True, "doc_id": doc_id, "task_id": task_id}


@router.post("/docs/{doc_id}/retry")
def retry_doc(doc_id: int, request: Request, background_tasks: BackgroundTasks,
              user: dict = Depends(get_current_user)):
    """对解析失败的文档重新入库。需 editor。"""
    doc = db.get_document(doc_id)
    if doc is None:
        return fail(code=404, msg="文档不存在")
    rbac.require_kb_role(user, doc["kb_id"], "editor")

    result = _do_retry_doc(doc_id, user["id"], user["username"], doc["kb_id"],
                           get_client_ip(request), background_tasks)
    if not result["ok"]:
        return fail(code=400, msg=result["reason"])
    return success({"doc_id": result["doc_id"], "task_id": result["task_id"], "status": "queued"})


@router.post("/kb/{kb_id}/docs/batch-delete")
def batch_delete(kb_id: int, req: BatchDeleteRequest, request: Request,
                 user: dict = Depends(get_current_user)):
    """批量删除文档：逐个执行（尽力型），返回成功/失败汇总。需 editor。"""
    rbac.require_kb_role(user, kb_id, "editor")

    succeeded, failed = [], []
    for doc_id in req.doc_ids:
        try:
            doc = db.get_document(doc_id)
            if doc is None:
                failed.append({"doc_id": doc_id, "reason": "文档不存在"})
                continue
            if doc["kb_id"] != kb_id:
                failed.append({"doc_id": doc_id, "reason": "文档不属于该知识库"})
                continue

            milvus_ids = db.get_chunk_milvus_ids(doc_id)
            if milvus_ids:
                milvus_store.delete(ids=milvus_ids)
            n = db.delete_document(doc_id)

            # 清理原文件
            rec = db.get_document_storage(doc_id)
            if rec and rec.get("storage_path"):
                abspath = os.path.realpath(os.path.join(_PROJECT_ROOT, rec["storage_path"]))
                if os.path.isfile(abspath):
                    os.remove(abspath)

            astore.write_audit(action="batch_delete_doc", user_id=user["id"],
                               username=user["username"], kb_id=kb_id,
                               target=doc.get("filename",""), ip=get_client_ip(request))
            succeeded.append({"doc_id": doc_id, "deleted_chunks": n})
            logger.info("批量删除 doc_id={} kb_id={} chunks={}", doc_id, kb_id, n)
        except Exception as e:
            logger.exception("批量删除 doc_id={} 失败: {}", doc_id, e)
            failed.append({"doc_id": doc_id, "reason": str(e)[:200]})

    return success({"total": len(req.doc_ids), "succeeded": succeeded, "failed": failed})


@router.get("/docs/{doc_id}/preview")
def preview_doc(doc_id: int, user: dict = Depends(get_current_user)):
    """解析结果预览（阶段八方案 a：从 chunk 按 chunk_index 拼回 markdown）。
    入库未保存整篇 md_content，此处由 chunk 重组；忠实版面属阶段九。
    """
    doc = db.get_document(doc_id)
    if doc is None:
        return fail(code=404, msg="文档不存在")
    rbac.require_kb_role(user, doc["kb_id"], "reader")     # 看预览需 reader
    chunks = db.get_chunks(doc_id)                         # 已按 chunk_index 排序
    ordered = sorted(chunks, key=lambda c: c["chunk_index"])
    markdown = "\n\n".join(c["content"] for c in ordered)
    out_chunks = [{"id": c["id"], "chunk_index": c["chunk_index"],
                   "content": c["content"]} for c in ordered]
    return success({"markdown": markdown, "chunks": out_chunks})



def _content_disposition(filename: str, ext: str) -> str:
    """ASCII 回退名 + RFC 5987 filename*（中文/特殊字符 UTF-8 编码，浏览器优先用后者）。"""
    from urllib.parse import quote
    ascii_fb = filename.encode("ascii", "ignore").decode("ascii")
    ascii_fb = ascii_fb.replace(chr(34), "").replace(chr(13), "").replace(chr(10), "")
    if not ascii_fb.strip() or ascii_fb.strip() == ext:
        ascii_fb = "download" + (ext or "")
    return "attachment; filename=\"" + ascii_fb + "\"; filename*=UTF-8\'\'" + quote(filename, safe="")


@raw_router.get("/docs/{doc_id}/download")
def download_doc(doc_id: int, user: dict = Depends(get_current_user_lax)):
    """流式下载原文件。文件名用 DB 原始 filename（B 方案），类型用 DB mime。
    老文档（加列前上传，无 storage_path）或文件缺失 → 404。
    """
    doc = db.get_document(doc_id)
    if doc is None:
        return fail(code=404, msg="文档不存在")
    rbac.require_kb_role(user, doc["kb_id"], "reader")     # 下载属读操作，reader 即可

    rec = db.get_document_storage(doc_id)
    if not rec or not rec.get("storage_path"):
        return fail(code=404, msg="原文件不存在（该文档上传于持久化功能之前）")

    abspath = os.path.realpath(os.path.join(_PROJECT_ROOT, rec["storage_path"]))
    root = os.path.realpath(str(_STORAGE_ROOT))
    if not (abspath == root or abspath.startswith(root + os.sep)):
        logger.error("下载路径逃逸 doc_id={} path={}", doc_id, rec["storage_path"])
        return fail(code=404, msg="原文件不存在")
    if not os.path.isfile(abspath):
        return fail(code=404, msg="原文件不存在")

    filename = doc["filename"] or "download"
    ext = _safe_ext(filename)
    headers = {"Content-Disposition": _content_disposition(filename, ext)}
    logger.info("下载原文件 doc_id={} → {} (by {})", doc_id, rec["storage_path"], user["username"])
    return FileResponse(abspath, media_type=rec.get("mime") or "application/octet-stream",
                        headers=headers)



@raw_router.get("/docs/{doc_id}/preview/raw")
def preview_raw(doc_id: int, user: dict = Depends(get_current_user_lax)):
    """原文件内联预览（inline）。供前端"原文件" tab 的 iframe/img 直接加载。
    认证走 lax（iframe/img 带不上 header，用 ?token=）。逻辑同 download，仅 disposition=inline。
    """
    doc = db.get_document(doc_id)
    if doc is None:
        return fail(code=404, msg="文档不存在")
    rbac.require_kb_role(user, doc["kb_id"], "reader")

    rec = db.get_document_storage(doc_id)
    if not rec or not rec.get("storage_path"):
        return fail(code=404, msg="原文件不存在（该文档上传于持久化功能之前）")

    abspath = os.path.realpath(os.path.join(_PROJECT_ROOT, rec["storage_path"]))
    root = os.path.realpath(str(_STORAGE_ROOT))
    if not (abspath == root or abspath.startswith(root + os.sep)):
        logger.error("预览路径逃逸 doc_id={} path={}", doc_id, rec["storage_path"])
        return fail(code=404, msg="原文件不存在")
    if not os.path.isfile(abspath):
        return fail(code=404, msg="原文件不存在")

    headers = {"Content-Disposition": "inline"}
    return FileResponse(abspath, media_type=rec.get("mime") or "application/octet-stream",
                        headers=headers)


# ── Office/CSV → HTML 实时预览 ────────────────────────────────────
_STYLE = ('<meta charset="utf-8"><style>'
          '*{margin:0;padding:0;box-sizing:border-box}'
          'body{font:14px/1.6 -apple-system,Segoe UI,sans-serif;color:#333;padding:16px 20px}'
          'h2{font-size:1.2em;margin:8px 0 4px}'
          'h3{font-size:1em;margin:6px 0 2px;color:#555}'
          'table{border-collapse:collapse;width:100%;margin:6px 0 14px;font-size:13px}'
          'th{background:#4472C4;color:#fff;font-weight:600;text-align:left;padding:6px 8px;'
          'border:1px solid #4472C4;position:sticky;top:0;z-index:1}'
          'td{padding:5px 8px;border:1px solid #ddd}'
          'tr:nth-child(even) td{background:#f8f9fa}'
          'p{margin:4px 0}'
          '.slide{margin:6px 0 12px;padding:4px 0;border-top:1px solid #eee}'
          '.slide h3{color:#2F5496}'
          '.info{font-size:12px;color:#888;margin-bottom:12px}'
          '</style>')


def _rows_to_html(rows: list[list], has_header: bool = True, start: int = 1) -> str:
    """把行列数据渲染为 HTML <table>。start 控制表头行号（0=首行是表头/数据从1开始）。"""
    if not rows:
        return "<p>(空表格)</p>"
    h = ['<table>']
    for i, row in enumerate(rows):
        tag = 'th' if (i == 0 and has_header) else 'td'
        cells = ''.join(f'<{tag}>{html.escape(str(c) if c is not None else "")}</{tag}>' for c in row)
        h.append(f'<tr>{cells}</tr>')
    h.append('</table>')
    return '\n'.join(h)


def _file_to_html(abspath: str, ext: str) -> str:
    """把原文件实时转为 HTML 字符串。"""
    parts = [_STYLE]

    # ── CSV ──
    if ext == '.csv':
        raw = Path(abspath).read_bytes()
        text = None
        for enc in ('utf-8', 'utf-8-sig', 'gbk'):
            try: text = raw.decode(enc); break
            except UnicodeDecodeError: continue
        if text is None: text = raw.decode('utf-8', errors='replace')
        try:
            dialect = csv.Sniffer().sniff(text[:8192])
            delimiter = dialect.delimiter
        except Exception:
            delimiter = ','
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = list(reader)
        parts.append(f'<h2>CSV 预览</h2><div class="info">共 {len(rows)} 行 · {Path(abspath).name}</div>')
        parts.append(_rows_to_html(rows, has_header=True))
        return '\n'.join(parts)

    # ── XLSX ──
    if ext == '.xlsx':
        from openpyxl import load_workbook
        wb = load_workbook(abspath, read_only=True, data_only=True)
        parts.append(f'<h2>Excel 预览</h2><div class="info">共 {len(wb.sheetnames)} 个工作表 · {Path(abspath).name}</div>')
        for sn in wb.sheetnames:
            ws = wb[sn]
            rows = [[cell.value for cell in row] for row in ws.iter_rows()]
            if not rows:
                parts.append(f'<h3>{html.escape(sn)}</h3><p>(空工作表)</p>')
                continue
            # 裁剪尾随全空行
            while rows and all(not str(c).strip() for c in rows[-1] if c is not None):
                rows.pop()
            parts.append(f'<h3>{html.escape(sn)}</h3>')
            parts.append(_rows_to_html(rows, has_header=True))
        wb.close()
        return '\n'.join(parts)

    # ── XLS ──
    if ext == '.xls':
        from xlrd import open_workbook
        wb = open_workbook(abspath)
        sheets = [wb.sheet_by_index(i) for i in range(wb.nsheets)]
        parts.append(f'<h2>Excel 预览</h2><div class="info">共 {len(sheets)} 个工作表 · {Path(abspath).name}</div>')
        for sheet in sheets:
            rows = [[sheet.cell_value(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)]
            parts.append(f'<h3>{html.escape(sheet.name)}</h3>')
            parts.append(_rows_to_html(rows, has_header=True))
        return '\n'.join(parts)

    # ── DOCX ──
    if ext == '.docx':
        from docx import Document
        doc = Document(abspath)
        parts.append(f'<h2>Word 预览</h2><div class="info">{Path(abspath).name}</div>')
        for elem in doc.element.body:
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag == 'p':
                text = ''.join(node.text or '' for node in elem.iter() if node.text).strip()
                if not text:
                    # 可能是内嵌图片或空行
                    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
                          'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'}
                    drawings = elem.findall('.//wp:inline', ns) + elem.findall('.//wp:anchor', ns)
                    if drawings:
                        for d in drawings:
                            desc = d.find('.//wp:docPr', ns)
                            dname = desc.get('descr', '') or desc.get('name', '') if desc is not None else ''
                            parts.append(f'<p style="color:#888">[图片: {html.escape(dname or "(无描述)")}]</p>')
                    else:
                        parts.append('<br>')
                elif text.startswith('Heading'):
                    # 标题样式
                    level = text.replace('Heading', '').strip()
                    parts.append(f'<h2>{html.escape(text)}</h2>')
                else:
                    parts.append(f'<p>{html.escape(text)}</p>')
            elif tag == 'tbl':
                tbl = elem
                ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                rows_xml = tbl.findall('.//w:tr', ns)
                tbl_rows = []
                for tr in rows_xml:
                    cells = tr.findall('.//w:tc', ns)
                    row = []
                    for tc in cells:
                        paras = tc.findall('.//w:p', ns)
                        cell_text = '\n'.join(p.text or '' for p in paras for t in p.findall('.//w:t', ns) if t.text)
                        row.append(cell_text)
                    if row:
                        tbl_rows.append(row)
                if tbl_rows:
                    parts.append(_rows_to_html(tbl_rows, has_header=True))
        return '\n'.join(parts)

    # ── PPTX ──
    if ext == '.pptx':
        from pptx import Presentation
        prs = Presentation(abspath)
        parts.append(f'<h2>PPTX 预览</h2><div class="info">共 {len(prs.slides)} 张幻灯片 · {Path(abspath).name}</div>')
        for idx, slide in enumerate(prs.slides, 1):
            parts.append(f'<div class="slide"><h3>Slide {idx}</h3>')
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        t = para.text.strip()
                        if t:
                            parts.append(f'<p>{html.escape(t)}</p>')
                if shape.has_table:
                    tbl = shape.table
                    rows = [[cell.text for cell in row.cells] for row in tbl.rows]
                    if rows:
                        parts.append(_rows_to_html(rows, has_header=True))
            parts.append('</div>')
        return '\n'.join(parts)

    return f"<p>不支持预览此文件类型（{ext}）</p>"


@raw_router.get("/docs/{doc_id}/preview/html")
def preview_html(doc_id: int, user: dict = Depends(get_current_user_lax)):
    """原文件 → HTML 实时预览。CSV/XLSX/XLS/DOCX/PPTX 渲染为 HTML 表格/文档。"""
    doc = db.get_document(doc_id)
    if doc is None:
        return fail(code=404, msg="文档不存在")
    rbac.require_kb_role(user, doc["kb_id"], "reader")

    rec = db.get_document_storage(doc_id)
    if not rec or not rec.get("storage_path"):
        return fail(code=404, msg="原文件不存在（该文档上传于持久化功能之前）")

    abspath = os.path.realpath(os.path.join(_PROJECT_ROOT, rec["storage_path"]))
    root = os.path.realpath(str(_STORAGE_ROOT))
    if not (abspath == root or abspath.startswith(root + os.sep)):
        return fail(code=404, msg="原文件不存在")
    if not os.path.isfile(abspath):
        return fail(code=404, msg="原文件不存在")

    ext = _safe_ext(doc["filename"] or "")
    if ext not in ('.csv', '.xlsx', '.xls', '.docx', '.pptx'):
        return fail(code=400, msg=f"不支持实时预览此文件类型: {ext}")

    try:
        html_content = _file_to_html(abspath, ext)
    except Exception as e:
        logger.opt(exception=e).error("HTML 预览生成失败 doc_id={}", doc_id)
        return fail(code=500, msg=f"预览生成失败: {e}")

    return HTMLResponse(content=html_content, status_code=200)


@router.put("/kb/{kb_id}/docs/{doc_id}/tags")
def update_tags(kb_id: int, doc_id: int, req: UpdateTagsRequest, request: Request,
                user: dict = Depends(get_current_user)):
    """编辑文档标签，需 editor。"""
    rbac.require_kb_role(user, kb_id, "editor")
    doc = db.get_document(doc_id)
    if doc is None or doc["kb_id"] != kb_id:
        return fail(code=404, msg="文档不存在")
    tags = db.update_document_tags(doc_id, req.tags)
    astore.write_audit(action="update_tags", user_id=user["id"], username=user["username"],
                       kb_id=kb_id, target=doc.get("filename",""), ip=get_client_ip(request))
    return success({"doc_id": doc_id, "tags": tags})


def _norm_tags_local(tags) -> list[str]:
    """去空、去重、保序（与 mysql_store._norm_tags 同逻辑，本地副本避免跨模块引用私有函数）。"""
    seen, out = set(), []
    for t in (tags or []):
        t = str(t).strip()
        if t and t not in seen:
            seen.add(t); out.append(t)
    return out


def _compute_tags(existing: list[str], action: str, incoming: list[str]) -> list[str]:
    """根据 action 计算最终标签列表。incoming 已通过 _norm_tags_local 标准化。"""
    if action == "set":
        return incoming
    if action == "add":
        seen = set(existing)
        for t in incoming:
            if t not in seen:
                existing.append(t)
                seen.add(t)
        return existing
    if action == "remove":
        rm = set(incoming)
        return [t for t in existing if t not in rm]
    return existing


@router.post("/kb/{kb_id}/docs/batch-tags")
def batch_tags(kb_id: int, req: BatchTagsRequest, request: Request,
               user: dict = Depends(get_current_user)):
    """批量修改文档标签（set/add/remove）。需 editor。"""
    rbac.require_kb_role(user, kb_id, "editor")

    clean_tags = _norm_tags_local(req.tags)
    if req.action in ("set", "add") and not clean_tags:
        return fail(code=400, msg="set/add 操作时 tags 不能为空")
    if req.action == "remove" and not clean_tags:
        return fail(code=400, msg="remove 操作时 tags 不能为空")

    succeeded, failed = [], []
    for doc_id in req.doc_ids:
        try:
            doc = db.get_document(doc_id)
            if doc is None:
                failed.append({"doc_id": doc_id, "reason": "文档不存在"})
                continue
            if doc["kb_id"] != kb_id:
                failed.append({"doc_id": doc_id, "reason": "文档不属于该知识库"})
                continue

            existing = doc.get("tags") or []
            new_tags = _compute_tags(list(existing), req.action, clean_tags)
            db.update_document_tags(doc_id, new_tags)
            astore.write_audit(action="batch_update_tags", user_id=user["id"],
                               username=user["username"], kb_id=kb_id,
                               target=doc.get("filename",""), ip=get_client_ip(request))
            succeeded.append({"doc_id": doc_id, "tags": new_tags})
        except Exception as e:
            logger.exception("批量标签 doc_id={} 失败: {}", doc_id, e)
            failed.append({"doc_id": doc_id, "reason": str(e)[:200]})

    return success({"total": len(req.doc_ids), "succeeded": succeeded, "failed": failed})


@router.post("/kb/{kb_id}/docs/batch-move")
def batch_move(kb_id: int, req: BatchMoveRequest, request: Request,
               user: dict = Depends(get_current_user)):
    """批量移动文档到文件夹。folder_id 为 null 时移到根目录。需 editor。"""
    rbac.require_kb_role(user, kb_id, "editor")

    # 验证目标文件夹存在且属于该知识库
    if req.folder_id is not None:
        fo = db.get_folder(req.folder_id)
        if fo is None:
            return fail(code=400, msg="目标文件夹不存在")
        if fo["kb_id"] != kb_id:
            return fail(code=400, msg="目标文件夹不属于该知识库")

    succeeded, failed = [], []
    for doc_id in req.doc_ids:
        try:
            doc = db.get_document(doc_id)
            if doc is None:
                failed.append({"doc_id": doc_id, "reason": "文档不存在"})
                continue
            if doc["kb_id"] != kb_id:
                failed.append({"doc_id": doc_id, "reason": "文档不属于该知识库"})
                continue

            db.set_document_folder(doc_id, req.folder_id)
            astore.write_audit(action="batch_move_doc", user_id=user["id"],
                               username=user["username"], kb_id=kb_id,
                               target=doc.get("filename",""), ip=get_client_ip(request))
            succeeded.append({"doc_id": doc_id, "folder_id": req.folder_id})
        except Exception as e:
            logger.exception("批量移动 doc_id={} 失败: {}", doc_id, e)
            failed.append({"doc_id": doc_id, "reason": str(e)[:200]})

    return success({"total": len(req.doc_ids), "succeeded": succeeded, "failed": failed})


@router.post("/kb/{kb_id}/docs/batch-retry")
def batch_retry(kb_id: int, req: BatchDeleteRequest, request: Request,
                background_tasks: BackgroundTasks,
                user: dict = Depends(get_current_user)):
    """批量重新解析失败的文档（尽力型）。需 editor。"""
    rbac.require_kb_role(user, kb_id, "editor")
    user_id = user["id"]
    username = user["username"]
    ip = get_client_ip(request)

    succeeded, failed = [], []
    for doc_id in req.doc_ids:
        try:
            result = _do_retry_doc(doc_id, user_id, username, kb_id,
                                   ip, background_tasks)
            if result["ok"]:
                succeeded.append({"doc_id": doc_id, "task_id": result["task_id"]})
            else:
                failed.append({"doc_id": doc_id, "reason": result["reason"]})
        except Exception as e:
            logger.exception("批量重试 doc_id={} 异常: {}", doc_id, e)
            failed.append({"doc_id": doc_id, "reason": str(e)[:200]})

    return success({"total": len(req.doc_ids), "succeeded": succeeded, "failed": failed})


@router.post("/kb/{kb_id}/notes")
def create_note(kb_id: int, req: CreateNoteRequest, request: Request,
                background_tasks: BackgroundTasks,
                user: dict = Depends(get_current_user)):
    """新建笔记：作为一篇 .md 文档入库（复用上传管线，分段+向量化+可检索）。需 editor。"""
    rbac.require_kb_role(user, kb_id, "editor")
    title = (req.title or "").strip()
    if not title:
        return fail(code=400, msg="笔记标题不能为空")
    filename = title if title.lower().endswith(".md") else title + ".md"

    doc_id = db.create_document(kb_id, filename, "pending",
                                 uploaded_by=user["username"],
                                 uploaded_at=datetime.utcnow(),
                                 folder_id=req.folder_id)

    # 笔记内容写临时 .md，喂给与 upload 相同的后台入库
    fd, tmp_path = tempfile.mkstemp(suffix=".md", prefix="note_")
    with os.fdopen(fd, "w", encoding="utf-8") as fobj:
        fobj.write(req.content or "")

    # 原文件持久化：把笔记 .md 也存进 storage（与上传一致，可下载/预览原文）
    try:
        info = _store_original_bytes((req.content or "").encode("utf-8"), kb_id, doc_id, filename)
        db.update_document_storage(doc_id, info["storage_path"], info["size"], info["mime"])
    except Exception as e:
        logger.error("笔记原文件落盘失败 doc_id={}: {}（不阻断入库）", doc_id, e)

    astore.write_audit(action="create_note", user_id=user["id"], username=user["username"],
                       kb_id=kb_id, target=title, ip=get_client_ip(request))
    logger.info("新建笔记 kb_id={} title={} → doc_id={} (by {})",
                kb_id, title, doc_id, user["username"])
    background_tasks.add_task(_run_ingest, tmp_path, kb_id, doc_id, filename=filename)
    return success({"id": doc_id, "filename": filename, "status": "pending"})


def _zip_generator(doc_files: list[tuple[str, str]]):
    """流式生成 ZIP：doc_files 为 [(filename, abspath), ...] 列表。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for filename, abspath in doc_files:
            if os.path.isfile(abspath):
                zf.write(abspath, filename)
    buf.seek(0)
    yield buf.read()


@router.post("/kb/{kb_id}/docs/batch-download")
def batch_download(kb_id: int, req: BatchDownloadRequest,
                   user: dict = Depends(get_current_user)):
    """批量下载 ZIP：将所选文档的原文件打包返回。需 reader。"""
    rbac.require_kb_role(user, kb_id, "reader")

    doc_files = []
    skipped = 0
    for doc_id in req.doc_ids:
        doc = db.get_document(doc_id)
        if doc is None or doc["kb_id"] != kb_id:
            skipped += 1
            continue
        rec = db.get_document_storage(doc_id)
        if not rec or not rec.get("storage_path"):
            skipped += 1
            continue
        abspath = os.path.realpath(os.path.join(_PROJECT_ROOT, rec["storage_path"]))
        root = os.path.realpath(str(_STORAGE_ROOT))
        if not (abspath == root or abspath.startswith(root + os.sep)):
            skipped += 1
            continue
        if not os.path.isfile(abspath):
            skipped += 1
            continue
        doc_files.append((doc["filename"] or f"doc_{doc_id}", abspath))

    if not doc_files:
        return fail(code=404, msg="没有可下载的文件")

    zip_name = f"kb_{kb_id}_docs_{date.today().strftime('%Y%m%d')}.zip"
    headers = {"Content-Disposition": _content_disposition(zip_name, ".zip"),
               "X-Download-Skipped": str(skipped)}
    logger.info("批量下载 kb_id={} 打包 {} 文件，跳过 {} 个 (by {})",
                kb_id, len(doc_files), skipped, user["username"])
    return StreamingResponse(_zip_generator(doc_files),
                             media_type="application/zip", headers=headers)
