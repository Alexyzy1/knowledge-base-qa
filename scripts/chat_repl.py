# chat_repl.py —— 跟服务器上的 DeepSeek 多轮对话
import asyncio
from loguru import logger
from backend.core import llm_client

logger.remove()  # 关掉控制台日志,免得 DEBUG/INFO 把对话冲乱;不想关就删这行


async def main():
    messages = []  # 累积整段对话历史
    print("开始对话(输入 exit 或直接回车退出)\n")
    while True:
        user = input("你: ").strip()
        if user in ("exit", "quit", ""):
            break
        messages.append({"role": "user", "content": user})

        print("DeepSeek: ", end="", flush=True)
        reply = ""
        async for delta in llm_client.stream(messages):
            print(delta, end="", flush=True)
            reply += delta
        print("\n")
        messages.append({"role": "assistant", "content": reply})  # 关键:把回答也存回去


asyncio.run(main())
