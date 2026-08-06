from loguru import logger
from backend.ingest.file_parser import parse_file, _TABLE_SUFFIXES
from backend.ingest.text_splitter import (
    split_text, split_text_recursive,
    split_text_markdown, split_text_semantic,
    split_text_sentence_window, split_table_rows,
    split_text_speaker,
)
from backend.core import embedding_client
from backend.store import milvus_store
from backend.store import mysql_store as db


# ── Contextual Retrieval (Anthropic 2024) ──
# 每个 chunk 在 embed 前拼接一个上下文前缀：文档名 + 所在位置信息。
# 前缀不存入 MySQL/Milvus 的 text 字段（text 仍是原始 chunk），只用于 embedding 向量。
# 这样 dense retrieval 自然携带"这个 chunk 来自哪个文档、在文档中的大致位置"的信息，
# 解决文件名查询（如 "lec8"）时内容不含文件名的 chunk 被其他文件挤掉的问题。

def _add_context_prefixes(chunks: list[str], filename: str) -> list[str]:
    """给 chunk 列表添加上下文前缀（仅用于 embedding，不写入存储）。

    策略（纯规则，不调用 LLM）：
    - 每个 chunk 用 "[文档: {filename}, 第 {i}/{n} 段]" 做前缀
    - 这样即使 chunk 文本不含文件名，embedding 向量也携带文档来源信号
    - 对于 markdown 文档，尝试从 chunk 开头提取 # heading 作为补充
    """
    n = len(chunks)
    result: list[str] = []
    for i, chunk in enumerate(chunks):
        # 提取可能的 heading（markdown 文档）
        heading = ""
        stripped = chunk.lstrip()
        if stripped.startswith("#"):
            # 取第一行 heading
            line_end = stripped.find("\n")
            heading = stripped[:line_end].rstrip() if line_end > 0 else stripped.rstrip()

        if heading and len(heading) > 3:
            prefix = f"[文档: {filename}, 第 {i+1}/{n} 段, {heading}]\n"
        else:
            prefix = f"[文档: {filename}, 第 {i+1}/{n} 段]\n"

        result.append(prefix + chunk)

    logger.info("Contextual Retrieval: 为 {} 个 chunk 添加了文档来源前缀", n)
    return result


def _tick(task_id: int | None, status: str, progress: int):
    if task_id is not None:
        db.update_task_status(task_id, status, progress)


async def _embed_in_batches(texts: list[str], batch_size: int) -> list[list[float]]:
    """分批调用 embedding，避免单次请求 token 过多；按 index 拼回完整顺序。"""
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        vectors.extend(await embedding_client.embed(batch))
        logger.info("embedding 批次 {}~{}/{} 完成", i, i + len(batch), len(texts))
    return vectors


async def ingest_document(path: str, kb_id: int, doc_id: int,
                          chunk_size: int = 500, overlap: int = 50,
                          batch_size: int = 64,
                          task_id: int | None = None,
                          filename: str = "") -> dict:
    """
    入库主链（flow A）：parse → split → embed(分批) → MySQL 插 chunk(拿自增主键当 chunk_id)
                       → Milvus 插(拿雪花 id) → 回写 milvus_id。
    doc_id 由调用方预先 create_document 建好；本函数负责 processing→done/failed 状态流转。
    失败时置 failed 并回滚已插入的 Milvus 行，避免脏向量残留。
    task_id 可选，有则同步更新 task 进度。
    filename 可选，有则给每个 chunk 加 [文件名] 前缀，使检索可命中文件名关键词。
    """
    logger.info("开始入库: path={} kb_id={} doc_id={} filename={!r}", path, kb_id, doc_id, filename)
    db.update_document_status(doc_id, "processing")
    _tick(task_id, "processing", 5)
    milvus_ids: list[int] = []
    try:
        # 1) 解析（按 KB 配置传递 OCR 参数）
        kcfg = db.get_kb_config(kb_id) or {}
        ocr_enabled = kcfg.get("ocr_enabled", True)
        table_enable = kcfg.get("table_parse_enabled", True)
        formula_enable = kcfg.get("formula_parse_enabled", False)
        parsed = parse_file(path, ocr_enabled=ocr_enabled,
                          table_enable=table_enable, formula_enable=formula_enable)

        # 表格格式：parse_file 返回 (rows, sheet_name)，绕过通用 splitter
        table_rows = None
        sheet_name = "Sheet1"
        if isinstance(parsed, tuple):
            table_rows, sheet_name = parsed
            text = ""  # 不走 _rows_to_markdown_table，直接用 row 数据
        else:
            text = parsed

        if not text.strip() and table_rows is None:
            logger.warning("解析结果为空，标记 failed: {}", path)
            db.update_document_status(doc_id, "failed")
            _tick(task_id, "failed", 0)
            return {"doc_id": doc_id, "kb_id": kb_id, "status": "failed",
                    "chunk_count": 0, "reason": "empty_text"}
        _tick(task_id, "processing", 20)

        # 2) 分段（按 KB 配置选择方法；kcfg 已在步骤 1 获取）
        path_lower = path.lower()
        is_table_file = any(path_lower.endswith(s) for s in _TABLE_SUFFIXES)

        if is_table_file and table_rows is not None:
            chunks = split_table_rows(table_rows, sheet_name=sheet_name, chunk_size=chunk_size)
        elif kcfg.get("chunk_method", "fixed") == "markdown":
            chunks = split_text_markdown(text, chunk_size=chunk_size, overlap=overlap)
        elif kcfg.get("chunk_method", "fixed") == "semantic":
            chunks = await split_text_semantic(text, chunk_size=chunk_size, overlap=overlap)
        elif kcfg.get("chunk_method", "fixed") == "sentence_window":
            chunks = split_text_sentence_window(text, chunk_size=chunk_size, overlap=overlap)
        elif kcfg.get("chunk_method", "fixed") == "recursive":
            chunks = split_text_recursive(text, chunk_size=chunk_size, overlap=overlap)
        elif kcfg.get("chunk_method", "fixed") == "speaker":
            chunks = split_text_speaker(text, chunk_size=chunk_size, overlap=overlap)
        else:
            chunks = split_text(text, chunk_size=chunk_size, overlap=overlap)
        if not chunks:
            logger.warning("分段结果为空，标记 failed: {}", path)
            db.update_document_status(doc_id, "failed")
            _tick(task_id, "failed", 0)
            return {"doc_id": doc_id, "kb_id": kb_id, "status": "failed",
                    "chunk_count": 0, "reason": "empty_chunks"}
        _tick(task_id, "processing", 35)

        # 2.5) 给每个 chunk 加文件名前缀 + 上下文前缀（Contextual Retrieval）
        # dense/BM25 均可命中文件名关键词；context 前缀让 chunk embedding 自然携带文档定位信息
        if filename and filename.strip():
            fname = filename.strip()
            prefix = f"[{fname}]\n"
            if len(chunks) > 1:
                # 为每个 chunk 生成包含文档名和前后文关联的上下文前缀
                chunks = _add_context_prefixes(chunks, fname)
            else:
                chunks = [prefix + c for c in chunks]

        # 3) 向量化（分批）
        vectors = await _embed_in_batches(chunks, batch_size)
        assert len(vectors) == len(chunks), f"向量数 {len(vectors)} != chunk 数 {len(chunks)}"
        _tick(task_id, "processing", 70)

        # 4) MySQL 插 chunk（milvus_id 暂空），拿自增主键 = 正式 chunk_id
        items = [{"chunk_index": i, "content": c} for i, c in enumerate(chunks)]
        chunk_ids = db.insert_chunks(doc_id, kb_id, items)
        _tick(task_id, "processing", 80)

        # 5) 用真实 chunk_id 插 Milvus，拿雪花 id
        rows = [{"kb_id": kb_id, "doc_id": doc_id, "chunk_id": cid,
                 "text": c, "dense_vector": v}
                for cid, c, v in zip(chunk_ids, chunks, vectors)]
        milvus_ids = milvus_store.insert(rows)
        _tick(task_id, "processing", 90)

        # 6) 回写 milvus_id 到 MySQL chunk 行
        db.update_chunk_milvus_ids(dict(zip(chunk_ids, milvus_ids)))

        # 7) 完成
        db.update_document_status(doc_id, "done")
        _tick(task_id, "done", 100)
        logger.info("入库完成: doc_id={} chunk_count={}", doc_id, len(chunks))
        return {"doc_id": doc_id, "kb_id": kb_id, "status": "done",
                "chunk_count": len(chunks),
                "chunk_ids": chunk_ids, "milvus_ids": milvus_ids}

    except Exception as e:
        logger.exception("入库失败 doc_id={}: {}", doc_id, e)
        # 回滚：先清 Milvus 向量，再删 MySQL chunk 行（防止幽灵 chunk）
        if milvus_ids:
            try:
                milvus_store.delete(ids=milvus_ids)
                logger.info("已回滚 Milvus {} 条", len(milvus_ids))
            except Exception as re:
                logger.error("Milvus 回滚失败 doc_id={}: {}", doc_id, re)
        try:
            db.delete_chunks_by_doc_id(doc_id)
            logger.info("已回滚 MySQL chunk doc_id={}", doc_id)
        except Exception as re:
            logger.error("MySQL chunk 回滚失败 doc_id={}: {}", doc_id, re)
        db.update_document_status(doc_id, "failed")
        _tick(task_id, "failed", 0)
        return {"doc_id": doc_id, "kb_id": kb_id, "status": "failed",
                "chunk_count": 0, "reason": str(e)}
