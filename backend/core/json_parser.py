# backend/core/json_parser.py
from json_repair import repair_json
from loguru import logger


def parse_llm_json(raw: str, default: dict | None = None) -> dict:
    """把 LLM 的文本输出健壮地解析成 dict。

    json_repair 会自动处理 markdown 围栏、prose 前缀、尾逗号、单引号、
    裸 key、未闭合括号等,无需手动剥 ```。它不抛异常,失败时返回空串,
    因此唯一要兜底的是"结果不是 dict"。
    """
    obj = repair_json(raw, return_objects=True)
    if isinstance(obj, dict):
        return obj

    # 修不出 dict(空串 / list / 标量)——记日志并回退
    logger.warning("LLM 输出无法解析为 JSON 对象,原始内容: {}", raw[:200])
    return default if default is not None else {"answer": raw, "confidence": 0.0, "sources": []}