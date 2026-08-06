# backend/core/llm_client.py
import httpx
from openai import AsyncOpenAI, APIError, APIConnectionError, APITimeoutError
from loguru import logger

from backend import config

_client = AsyncOpenAI(
    api_key=config.MODEL_API_KEY,
    base_url=config.MODEL_API_BASE,
    timeout=httpx.Timeout(120.0, connect=10.0),
    max_retries=1,
)


async def chat(messages: list[dict], temperature: float = 0.7,
               model: str | None = None, max_tokens: int | None = None,
               thinking: bool = False, **kwargs) -> tuple[str, str]:
    """普通(非流式)对话。返回 (answer, reasoning) — reasoning 可能为空字符串。"""
    logger.debug("LLM chat 请求,messages 条数={}", len(messages))
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if thinking:
        effective_model = (model or config.LLM_MODEL).lower()
        if "qwen" in effective_model or "deepseek" in effective_model:
            pass  # Qwen/DeepSeek 默认产出 reasoning，不设 enable_thinking=True
        elif "minimax" in effective_model or "m2.7" in effective_model:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
        else:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
    resp = await _client.chat.completions.create(
        model=model or config.LLM_MODEL,
        messages=messages,
        temperature=temperature,
        **kwargs,
    )
    msg = resp.choices[0].message
    content = msg.content or ""
    # 提取思考/推理内容（尝试所有可能的字段位置）
    reasoning = getattr(msg, "reasoning_content", None) or ""
    if not reasoning:
        extra = getattr(msg, "model_extra", None) or {}
        reasoning = extra.get("reasoning_content") or extra.get("reasoning") or extra.get("thinking") or ""
    # 如果 content 为空但 reasoning 有内容，用 reasoning 作为回答
    if not content:
        content = reasoning
        reasoning = ""
    logger.info("LLM chat 完成,返回 {} 字, reasoning {} 字", len(content), len(reasoning))
    return content, reasoning


async def stream(messages: list[dict], temperature: float = 0.7,
                 model: str | None = None, max_tokens: int | None = None,
                 thinking: bool = False, **kwargs):
    """流式对话,逐段 yield 文本增量。max_tokens=None 时不限。"""
    logger.debug("LLM stream 请求,messages 条数={}", len(messages))
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if thinking:
        effective_model = (model or config.LLM_MODEL).lower()
        if "qwen" in effective_model or "deepseek" in effective_model:
            pass  # Qwen/DeepSeek 默认产出 reasoning/prompt标签分离，不设 enable_thinking
        else:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
    # thinking=False 时：Qwen/DeepSeek 同样不设 extra_body；其余模型不设即关闭。
    resp = await _client.chat.completions.create(
        model=model or config.LLM_MODEL,
        messages=messages,
        temperature=temperature,
        stream=True,
        **kwargs,
    )
    chunk_count = 0
    async for chunk in resp:
        if not chunk.choices or chunk.choices[0].delta is None:
            continue
        delta = chunk.choices[0].delta
        # 尝试多种字段：content、reasoning_content、model_extra
        text = delta.content or ""
        if not text:
            text = getattr(delta, "reasoning_content", None) or ""
        if not text:
            extra = getattr(delta, "model_extra", None) or {}
            text = extra.get("reasoning_content", "") or extra.get("thinking", "") or extra.get("reasoning", "") or ""
        # 调试：前 3 个 chunk 打印可用字段，定位 Qwen 输出在哪里
        chunk_count += 1
        if chunk_count <= 3:
            fields = [f for f in dir(delta) if not f.startswith("_")]
            model_extra = getattr(delta, "model_extra", None)
            logger.debug("stream chunk #{} fields={} model_extra={} content={!r} reasoning={!r}",
                         chunk_count, fields, model_extra,
                         getattr(delta, "content", None),
                         getattr(delta, "reasoning_content", None))
        if text:
            yield text
    logger.info("LLM stream 完成,共 {} 个 chunk", chunk_count)


async def stream_with_thinking(messages: list[dict], temperature: float = 0.7,
                               model: str | None = None, max_tokens: int | None = None,
                               thinking: bool = False, **kwargs):
    """流式对话,返回 ('think', text) 或 ('content', text) 元组。
    思维模型的推理过程走 think，最终答案走 content；调用方据此区分展示。"""
    logger.debug("LLM stream+think 请求,messages 条数={}", len(messages))
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    effective_model = (model or config.LLM_MODEL).lower()
    if thinking:
        if "qwen" in effective_model or "deepseek" in effective_model:
            # Qwen/DeepSeek 默认就产出 reasoning（在 model_extra.reasoning 中），
            # 设任何 extra_body 都会破坏 content 输出。不设即可。
            pass
        else:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
    # thinking=False 时：Qwen/DeepSeek 同样不设 extra_body，由上层 chat.py 根据
    # req.thinking 决定是否丢弃 think 内容；其余模型不设 extra_body 即关闭。
    resp = await _client.chat.completions.create(
        model=model or config.LLM_MODEL,
        messages=messages,
        temperature=temperature,
        stream=True,
        **kwargs,
    )
    chunk_count = 0
    think_count = 0
    content_count = 0
    async for chunk in resp:
        if not chunk.choices or chunk.choices[0].delta is None:
            continue
        delta = chunk.choices[0].delta
        chunk_count += 1

        # ── 提取推理内容（尝试所有可能的字段位置）──
        extra = getattr(delta, "model_extra", None) or {}
        # 1) delta 直接属性 reasoning_content（新版 openai SDK）
        reasoning = getattr(delta, "reasoning_content", None)
        # 2) model_extra 中的各种键名
        if not reasoning:
            reasoning = extra.get("reasoning_content") or extra.get("reasoning") or extra.get("thinking") or ""
        if not reasoning:
            reasoning = ""

        # ── 提取回答内容 ──
        content = delta.content or ""

        # ── 调试：前 5 个 chunk 打印可用字段，定位不同模型的输出通道 ──
        if chunk_count <= 5:
            fields = sorted([f for f in dir(delta) if not f.startswith("_")])
            logger.debug(
                "stream+think chunk #{} model={} fields={} "
                "model_extra_keys={} content={!r} reasoning_attr={!r} reasoning_extra={!r}",
                chunk_count, effective_model, fields,
                sorted(extra.keys()) if extra else [],
                content[:80] if content else None,
                getattr(delta, "reasoning_content", None),
                {k: extra.get(k) for k in extra if "reason" in k.lower() or "think" in k.lower()},
            )

        if reasoning:
            think_count += 1
            yield ("think", reasoning)
        if content:
            content_count += 1
            yield ("content", content)
    logger.info("LLM stream+think 完成,共 {} chunk, think={} content={}",
                chunk_count, think_count, content_count)
