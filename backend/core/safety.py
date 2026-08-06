"""安全过滤：AC 自动机快筛 + LLM 兜底（任务 7）。

策略（用户选定「词库+LLM 兜底」）：
  1) 先用 AC 自动机（Aho-Corasick）对敏感词表做一次扫描匹配，O(n+m) 复杂度；
     对纯英文/数字词汇使用 \\b 词边界正则，避免短词误伤（如 "AV" 命中 "JAVASCRIPT"）；
  2) 词库未命中但 config.SAFETY_LLM_CHECK 打开时，再过一遍轻量 LLM 审查，
     兜住谐音/变体/语义层面的不当内容。

命中后由调用方（chat 接口）统一处理：返回固定安全话术，且该轮不进入后续上下文。
"""
from __future__ import annotations
from pathlib import Path

from loguru import logger

from backend import config
from backend.core import llm_client
from backend.core.json_parser import parse_llm_json
from backend.core.ac_automaton import AhoCorasick

_WORDS_FILE = Path(__file__).resolve().parent / "sensitive_words.txt"


def _load_words() -> list[str]:
    if not _WORDS_FILE.exists():
        return []
    words = []
    for line in _WORDS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.append(line.lower())
    return words


_WORDS = _load_words()
_MIN_WORD_COUNT = 20  # 低于此值视为安全防线薄弱
if len(_WORDS) < _MIN_WORD_COUNT:
    logger.warning(
        "安全词库仅 {} 条（建议 ≥ {}），请补充 backend/core/sensitive_words.txt —— "
        "词库是内容安全的第一道防线，过少则形同虚设",
        len(_WORDS), _MIN_WORD_COUNT,
    )
else:
    logger.info("安全词库加载 {} 条", len(_WORDS))

# AC 自动机：一次扫描匹配所有模式，O(文本长 + 命中数)
_ac = AhoCorasick(_WORDS)
logger.info("安全词库 AC 自动机就绪: {} 个模式串, {} 个状态节点",
            len(_WORDS), len(_ac._trie))


def quick_check(text: str) -> str | None:
    """词库快筛：AC 自动机一次扫描，命中返回命中的词，否则 None。

    纯 ASCII 词启用 \\b 词边界（防止 "AV" 误伤 "HAVE" 等），
    中文/混合词走子串匹配。O(文本长 + 命中数)，与词库大小无关。
    """
    hits = _ac.search(text, word_boundary_ascii=True)
    if hits:
        # 去重，返回所有命中词（逗号分隔，日志可追溯）
        seen: set[str] = set()
        unique = []
        for h in hits:
            if h not in seen:
                seen.add(h)
                unique.append(h)
        return ",".join(unique)
    return None


_LLM_SYSTEM = (
    "你是内容安全审查器。判断【用户文本】是否包含色情、暴力、违法犯罪、仇恨等不当内容。"
    "只输出 JSON，不要解释：\n"
    '{"unsafe": true 或 false, "category": "色情|暴力|违法|仇恨|其他|none"}'
)


async def llm_check(text: str) -> bool:
    """LLM 兜底审查：判定不当返回 True。异常时放行（False），不阻断正常问答。"""
    try:
        messages = [
            {"role": "system", "content": _LLM_SYSTEM},
            {"role": "user", "content": f"用户文本：{text}"},
        ]
        raw, _ = await llm_client.chat(messages, temperature=0, max_tokens=64)
        parsed = parse_llm_json(raw, default={"unsafe": False})
        return bool(parsed.get("unsafe"))
    except Exception as e:
        logger.warning("安全 LLM 审查异常,放行: {}", e)
        return False


async def is_blocked(text: str, word_check: bool = True,
                    use_llm: bool | None = None) -> tuple[bool, str]:
    """综合判定。返回 (是否拦截, 原因)。
    word_check=False 时跳过词库快筛；use_llm=None 走全局 config.SAFETY_LLM_CHECK。"""
    if not text or not text.strip():
        return False, ""
    if word_check:
        hit = quick_check(text)
        if hit is not None:
            logger.info("安全拦截(词库): 命中 {!r}", hit)
            return True, f"keyword:{hit}"
    do_llm = use_llm if use_llm is not None else config.SAFETY_LLM_CHECK
    if do_llm and await llm_check(text):
        logger.info("安全拦截(LLM)")
        return True, "llm"
    return False, ""
