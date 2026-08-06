import asyncio, json
from backend.retrieval.retriever import retrieve

async def main():
    for mode in ("dense", "sparse", "hybrid"):
        hits = await retrieve("温室夜间温度", kb_id=2, mode=mode, top_k=3)
        print(f"\n===== mode={mode} | 返回 {len(hits)} 条 =====")
        if hits:
            print("首条 keys:", list(hits[0].keys()))
            print("首条内容:", json.dumps(hits[0], ensure_ascii=False, default=str)[:300])

asyncio.run(main())
