# ask.py —— 从 q.txt 读问题,跟 DeepSeek 对话,历史存 messages.json
import asyncio, json, os
from loguru import logger
from backend.core import llm_client

logger.remove()
HISTORY, QUESTION = "messages.json", "q.txt"


async def main():
    with open(QUESTION, encoding="utf-8") as f:
        question = f.read().strip()
    if not question:
        print("q.txt 是空的,先把问题写进去再跑")
        return

    messages = json.load(open(HISTORY, encoding="utf-8")) if os.path.exists(HISTORY) else []
    messages.append({"role": "user", "content": question})

    print(f"你: {question}\nDeepSeek: ", end="", flush=True)
    reply = ""
    async for delta in llm_client.stream(messages):
        print(delta, end="", flush=True)
        reply += delta
    print("\n")

    messages.append({"role": "assistant", "content": reply})
    json.dump(messages, open(HISTORY, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


asyncio.run(main())
