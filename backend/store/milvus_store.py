from pymilvus import MilvusClient, DataType, Function, FunctionType
from loguru import logger
from backend import config
COLLECTION = "knowledge_chunks"
client = MilvusClient(uri=config.MILVUS_URI)


def _build_kb_filter(kb_id: int | None = None, kb_ids: list[int] | None = None,
                     doc_ids: list[int] | None = None) -> str:
    """构造 Milvus 过滤表达式。kb_ids 优先于 kb_id；doc_ids 限定文档；None=不限。"""
    parts: list[str] = []
    if doc_ids is not None and len(doc_ids) > 0:
        parts.append("doc_id in [" + ", ".join(str(i) for i in doc_ids) + "]")
    if kb_ids is not None:
        if len(kb_ids) == 0:
            return ""  # 调用方应在检索前判空
        parts.append("kb_id in [" + ", ".join(str(i) for i in kb_ids) + "]")
    elif kb_id is not None:
        parts.append(f"kb_id == {kb_id}")
    return " and ".join(parts)


def create_collection():
    if client.has_collection(COLLECTION):
        logger.info("collection {} 已存在，跳过", COLLECTION)
        return
    schema = client.create_schema(auto_id=True)
    schema.add_field("id",        DataType.INT64, is_primary=True)
    schema.add_field("kb_id",     DataType.INT64)
    schema.add_field("doc_id",    DataType.INT64)
    schema.add_field("chunk_id",  DataType.INT64)
    schema.add_field("text",      DataType.VARCHAR, max_length=8192, enable_analyzer=True, analyzer_params={"type": "chinese"})
    schema.add_field("dense_vector",  DataType.FLOAT_VECTOR, dim=config.EMBEDDING_DIM)
    schema.add_field("sparse_vector", DataType.SPARSE_FLOAT_VECTOR)
    schema.add_function(Function(
        name="text_bm25", function_type=FunctionType.BM25,
        input_field_names=["text"], output_field_names=["sparse_vector"],
    ))
    idx = client.prepare_index_params()
    idx.add_index("dense_vector",  index_type="HNSW", metric_type="COSINE",
                  params={"M": 16, "efConstruction": 200})
    idx.add_index("sparse_vector", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
    client.create_collection(COLLECTION, schema=schema, index_params=idx)
    logger.info("collection {} 已建（dense {} 维 + sparse BM25）", COLLECTION, config.EMBEDDING_DIM)
def insert(rows: list[dict]) -> list[int]:
    res = client.insert(COLLECTION, data=rows)
    ids = res["ids"]
    logger.info("插入 {} 条，返回 ids[:3]={}", len(ids), ids[:3])
    return ids
def search(query_vector: list[float], kb_id: int | None = None,
           kb_ids: list[int] | None = None, top_k: int = 3,
           doc_ids: list[int] | None = None) -> list[dict]:
    expr = _build_kb_filter(kb_id=kb_id, kb_ids=kb_ids, doc_ids=doc_ids)
    res = client.search(
        COLLECTION,
        data=[query_vector],
        anns_field="dense_vector",
        limit=top_k,
        search_params={"metric_type": "COSINE"},
        output_fields=["kb_id", "doc_id", "chunk_id", "text"],
        filter=expr,
    )
    hits = [
        {"kb_id": h["entity"]["kb_id"], "doc_id": h["entity"]["doc_id"],
         "chunk_id": h["entity"]["chunk_id"], "text": h["entity"]["text"],
         "score": h["distance"]}
        for h in res[0]
    ]
    logger.info("检索完成，kb_ids={} kb_id={}，命中 {} 条", kb_ids, kb_id, len(hits))
    return hits
def delete(ids: list[int] | None = None, filter_expr: str = "") -> dict:
    res = client.delete(COLLECTION, ids=ids) if ids else client.delete(COLLECTION, filter=filter_expr)
    logger.info("删除完成: {}", res)
    return res


def search_sparse(query_text: str, kb_id: int | None = None,
                  kb_ids: list[int] | None = None, top_k: int = 3,
                  doc_ids: list[int] | None = None) -> list[dict]:
    """BM25 稀疏检索：传 query 原文，Milvus 内部用 analyzer 分词 + BM25 打分。
    返回结构与 search()（dense）一致，便于上层统一处理；score 为 BM25 分（越大越相关）。"""
    expr = _build_kb_filter(kb_id=kb_id, kb_ids=kb_ids, doc_ids=doc_ids)
    res = client.search(
        COLLECTION,
        data=[query_text],                       # 传文本，不是向量
        anns_field="sparse_vector",
        limit=top_k,
        search_params={"metric_type": "BM25"},
        output_fields=["kb_id", "doc_id", "chunk_id", "text"],
        filter=expr,
    )
    hits = [
        {"kb_id": h["entity"]["kb_id"], "doc_id": h["entity"]["doc_id"],
         "chunk_id": h["entity"]["chunk_id"], "text": h["entity"]["text"],
         "score": h["distance"]}
        for h in res[0]
    ]
    logger.info("BM25 检索完成，kb_ids={} kb_id={}，命中 {} 条", kb_ids, kb_id, len(hits))
    return hits


def search_similar(query_vector: list[float], kb_ids: list[int] | None = None,
                   exclude_doc_id: int | None = None, top_k: int = 30) -> list[dict]:
    """找相似：dense 近邻，可跨多库（kb_id in kb_ids），可排除源文档。
    输出比 search() 多带 kb_id（前端要按库分组显示 kb_name）。
    kb_ids=None 表示不限库（super_admin）；空列表表示无可见库 → 直接返回空。"""
    if kb_ids is not None and len(kb_ids) == 0:
        return []
    conds = []
    if kb_ids is not None:
        conds.append("kb_id in [" + ", ".join(str(i) for i in kb_ids) + "]")
    if exclude_doc_id is not None:
        conds.append(f"doc_id != {exclude_doc_id}")
    expr = " and ".join(conds)
    res = client.search(
        COLLECTION,
        data=[query_vector],
        anns_field="dense_vector",
        limit=top_k,
        search_params={"metric_type": "COSINE"},
        output_fields=["kb_id", "doc_id", "chunk_id", "text"],
        filter=expr,
    )
    hits = [
        {"kb_id": h["entity"]["kb_id"], "doc_id": h["entity"]["doc_id"],
         "chunk_id": h["entity"]["chunk_id"], "text": h["entity"]["text"],
         "score": h["distance"]}
        for h in res[0]
    ]
    logger.info("相似检索完成，kb_ids={}，命中 {} 条", kb_ids, len(hits))
    return hits
