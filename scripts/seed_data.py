import asyncio
import tempfile
from backend.ingest.ingest_pipeline import ingest_document
from backend.store import milvus_store, mysql_store as db
from pathlib import Path

db.init_tables()
KB_ID = 1  # 测试知识库

# 每条单独成文档，直接写 txt（绕开 PDF，更快），ingest 支持 txt
CHUNKS = [
    # A: 近义不同词 —— dense 该赢
    "训练猫咪使用猫砂盆需要耐心，把猫砂盆放在安静角落，每次进食后抱猫进去熟悉环境。",
    # B: 术语缩写 —— BM25 该赢
    "Milvus 的向量检索默认使用 HNSW 索引，metric 用 COSINE，适合高精度近邻搜索。",
    # C: 关键词重叠组
    "Python 的异步编程基于 asyncio 事件循环，用 async 和 await 关键字定义协程。",
    "FastAPI 原生支持异步接口，路由函数写成 async def 即可获得高并发能力。",
    # 干扰项
    "今天天气晴朗，适合外出散步，气温二十五度，紫外线较强注意防晒。",
    "红烧肉的做法是先焯水再小火慢炖，加冰糖炒糖色，最后大火收汁。",
]

async def main():
    with tempfile.TemporaryDirectory(prefix="seed_") as tmp_dir:
        tmp = Path(tmp_dir)
        for i, content in enumerate(CHUNKS):
            p = tmp / f"seed_{i}.txt"
            p.write_text(content, encoding="utf-8")
            doc_id = db.create_document(KB_ID, f"seed_{i}.txt")
            r = await ingest_document(str(p), kb_id=KB_ID, doc_id=doc_id,
                                      chunk_size=500, overlap=50)
            print(f"doc_id={doc_id} status={r['status']} milvus_ids={r['milvus_ids']} | {content[:20]}...")

asyncio.run(main())
milvus_store.client.flush(milvus_store.COLLECTION)
print("\nseed done. kb_id=1")
