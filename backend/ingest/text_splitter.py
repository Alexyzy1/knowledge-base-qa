import re
import math
from loguru import logger

# 句子原子切分：按 中文句末标点。！？； 和 换行 切，分隔符保留在句尾。
# 两个备选都至少吃 1 个字符，保证无字符丢失（"".join(atoms) == text）。
_ATOM = re.compile(r'[^。！？；\n]*[。！？；\n]|[^。！？；\n]+')


def _atomize(text: str) -> list[str]:
    """把文本切成句子原子（中文句子/换行为界），不丢字符。"""
    return _ATOM.findall(text)


def _hard_split(s: str, size: int) -> list[str]:
    """超长原子（无标点的长串）按字符硬切。"""
    return [s[i:i + size] for i in range(0, len(s), size)]


def split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    边界感知分段：优先在句末/换行处断开，凑不到目标长度才硬切；相邻 chunk 带 overlap 重叠。
    返回 list[str]；chunk_index / doc_id 等元数据由 pipeline 装配时再加。
    """
    if not text or not text.strip():
        logger.warning("split_text 收到空文本，返回 []")
        return []
    if overlap >= chunk_size:
        raise ValueError(f"overlap({overlap}) 必须小于 chunk_size({chunk_size})")

    units: list[str] = []
    for atom in _atomize(text):
        if len(atom) > chunk_size:
            units.extend(_hard_split(atom, chunk_size))
        else:
            units.append(atom)

    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for u in units:
        if cur and cur_len + len(u) > chunk_size:
            chunks.append("".join(cur).strip())
            while cur and (cur_len > overlap or cur_len + len(u) > chunk_size):
                cur_len -= len(cur[0])
                cur.pop(0)
        cur.append(u)
        cur_len += len(u)
    if cur:
        chunks.append("".join(cur).strip())

    chunks = [c for c in chunks if c]
    logger.info("分段完成(fixed)：{} 字 → {} 块（chunk_size={}, overlap={}）",
                len(text), len(chunks), chunk_size, overlap)
    return chunks


# ── 递归切分（RecursiveCharacterTextSplitter 同款算法）──
# 分隔符优先级：段落 → 换行 → 句末标点 → 逗号 → 空格 → 硬切
_RECURSIVE_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", "  ", " ", ""]


def _split_recursive(text: str, separators: list[str], chunk_size: int) -> list[str]:
    """递归切分：用当前优先级最高分隔符切，子块超长则用下一级分隔符递归。"""
    sep = separators[0] if separators else ""
    if sep == "":
        # 终极兜底：硬切
        return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]

    if sep == " ":
        splits = text.split(sep)
    else:
        splits = text.split(sep)
        # 保留分隔符（"。"、"！"等）
        if sep and sep not in (" ", ""):
            splits = [s + sep for s in splits[:-1]] + [splits[-1]] if splits else []

    result = []
    for part in splits:
        part = part.strip() if sep in ("\n\n", "\n") else part
        if not part:
            continue
        if len(part) <= chunk_size:
            result.append(part)
        else:
            # 这段太长，用下一级分隔符递归
            result.extend(_split_recursive(part, separators[1:], chunk_size))
    return result


def _merge_with_overlap(splits: list[str], chunk_size: int, overlap: int) -> list[str]:
    """把切好的小段合并到 chunk_size，带 overlap 滑动窗口。"""
    if not splits:
        return []
    chunks = []
    cur, cur_len = [], 0
    for s in splits:
        if cur and cur_len + len(s) > chunk_size:
            chunks.append("".join(cur).strip())
            # 滑动窗口：从前面弹出直到剩余 ≤ overlap
            while cur and (cur_len > overlap or cur_len + len(s) > chunk_size):
                cur_len -= len(cur[0])
                cur.pop(0)
        cur.append(s)
        cur_len += len(s)
    if cur:
        chunks.append("".join(cur).strip())
    return [c for c in chunks if c]


def split_text_recursive(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    RecursiveCharacterTextSplitter 同款。
    按 \\n\\n → \\n → 。→ ！→ ？→ ；→ ，→ 空格 → 硬切 的优先级逐级切分，
    切完后再用重叠窗口合并到 target chunk_size。
    """
    if not text or not text.strip():
        logger.warning("split_text_recursive 收到空文本，返回 []")
        return []
    if overlap >= chunk_size:
        raise ValueError(f"overlap({overlap}) 必须小于 chunk_size({chunk_size})")

    separators = list(_RECURSIVE_SEPARATORS)
    atoms = _split_recursive(text.strip(), separators, chunk_size)
    chunks = _merge_with_overlap(atoms, chunk_size, overlap)
    logger.info("分段完成(recursive)：{} 字 → {} 块（chunk_size={}, overlap={}）",
                len(text), len(chunks), chunk_size, overlap)
    return chunks


# ── Markdown 标题感知切分 ──
_MD_HEADER = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)


def split_text_markdown(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    按 Markdown 标题（# ~ ######）切分。每个 section 的 chunk 会带上标题路径前缀：
    「## 概述 > ### 详细说明」帮助检索时匹配结构上下文。

    实现：找到所有标题位置 → 按标题分段 → 每段内部递归切分 → 标题前缀追加到每个 chunk。
    """
    if not text or not text.strip():
        logger.warning("split_text_markdown 收到空文本，返回 []")
        return []
    if overlap >= chunk_size:
        raise ValueError(f"overlap({overlap}) 必须小于 chunk_size({chunk_size})")

    # 找所有标题位置
    headers: list[tuple[int, int, str]] = []  # (start, end, header_text)
    for m in _MD_HEADER.finditer(text):
        headers.append((m.start(), m.end(), m.group(0).strip()))

    if not headers:
        # 没标题 → 退回递归切分
        logger.info("文本无 Markdown 标题，退回 recursive")
        return split_text_recursive(text, chunk_size, overlap)

    # 构建标题层级栈
    all_chunks: list[str] = []
    for i, (h_start, h_end, header_line) in enumerate(headers):
        # 当前 section 的正文：从标题行尾到下一个标题行首（或文本末尾）
        body_start = h_end + 1 if h_end < len(text) and text[h_end] == '\n' else h_end
        body_end = headers[i + 1][0] if i + 1 < len(headers) else len(text)
        body = text[body_start:body_end].strip()
        if not body:
            continue

        # 确定标题级别和前缀
        level = len(header_line) - len(header_line.lstrip('#'))
        prefix = header_line + "\n"

        # 对 body 递归切分（当 body 很短时直接保留）
        if len(body) <= chunk_size:
            all_chunks.append(prefix + body)
        else:
            atoms = _split_recursive(body, list(_RECURSIVE_SEPARATORS), chunk_size)
            merged = _merge_with_overlap(atoms, chunk_size, overlap)
            for c in merged:
                all_chunks.append(prefix + c)

    logger.info("分段完成(markdown)：{} 字, {} headers → {} 块",
                len(text), len(headers), len(all_chunks))
    return all_chunks


# ── 语义切分 ──
# 默认相似度阈值：相邻句余弦相似度低于此值即切开
_DEFAULT_SEMANTIC_THRESHOLD = 0.6
# 最小 chunk 大小（字符数），低于此下限的短块向前合并
_DEFAULT_MIN_CHUNK_SIZE = 100
_SENTENCE = re.compile(r'[^。！？；\n]*[。！？；\n]|[^。！？；\n]+')


async def split_text_semantic(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
    threshold: float = _DEFAULT_SEMANTIC_THRESHOLD,
    min_chunk_size: int = _DEFAULT_MIN_CHUNK_SIZE,
) -> list[str]:
    """
    语义感知分段：先切成句子 → embed 每句 → 相邻句余弦相似度 < threshold 处切开 →
    合并到 chunk_size。最终短块向前合并（保证每块 ≥ min_chunk_size）。

    需要 embedding_client，本函数是 async。
    """
    if not text or not text.strip():
        logger.warning("split_text_semantic 收到空文本，返回 []")
        return []
    if min_chunk_size > chunk_size:
        min_chunk_size = chunk_size // 2  # 下限不应超过上限，兜底取一半

    from backend.core import embedding_client

    # 1. 切句子
    sentences = [s.strip() for s in _SENTENCE.findall(text) if s.strip()]
    if not sentences:
        return []
    if len(sentences) == 1:
        return [sentences[0]]

    # 2. 批量 embedding
    vectors = await embedding_client.embed(sentences)

    # 3. 计算相邻句子余弦相似度，标记断点
    breakpoints: list[int] = [0]  # 每个 breakpoint 是一个 chunk 的起始句索引
    for i in range(1, len(sentences)):
        sim = _cosine_similarity(vectors[i - 1], vectors[i])
        if sim < threshold:
            breakpoints.append(i)

    # 4. 按断点合并句子到 chunk_size
    chunks: list[str] = []
    bp_idx = 0
    while bp_idx < len(breakpoints):
        start = breakpoints[bp_idx]
        end = breakpoints[bp_idx + 1] if bp_idx + 1 < len(breakpoints) else len(sentences)
        # 合并 start..end 的句子
        cur, cur_len = [], 0
        for j in range(start, end):
            s = sentences[j]
            if cur and cur_len + len(s) > chunk_size:
                chunks.append("".join(cur))
                # overlap 窗口
                while cur and cur_len > overlap:
                    cur_len -= len(cur[0])
                    cur.pop(0)
            cur.append(s)
            cur_len += len(s)
        if cur:
            chunks.append("".join(cur))
        bp_idx += 1

    # 5. 后处理：短块向前合并（保证每块 ≥ min_chunk_size）
    chunks = _merge_short_chunks(chunks, min_chunk_size)
    chunks = [c.strip() for c in chunks if c.strip()]
    logger.info("分段完成(semantic)：{} 句, {} 断点 → {} 块（min={}, max={}）",
                len(sentences), len(breakpoints), len(chunks), chunk_size, overlap)
    return chunks


def _merge_short_chunks(chunks: list[str], min_size: int) -> list[str]:
    """把过短的 chunk 向前合并到上一个 chunk。

    只做一轮扫描，不连锁：一个 chunk 被合并后，合并的目标块不再参与后续判断。
    首块过短则向后合并（合并到下一块）。
    """
    if not chunks or min_size <= 0 or len(chunks) == 1:
        return chunks
    n = len(chunks)

    # 标记哪些 chunk 被合并掉了（用于跳过）
    merged_away: set[int] = set()

    # 首块过短 → 向后合并
    if len(chunks[0].strip()) < min_size and n >= 2:
        chunks[1] = chunks[0] + chunks[1]
        merged_away.add(0)

    for i in range(1, n):
        if i in merged_away:
            continue
        c = chunks[i].strip()
        if not c:
            merged_away.add(i)
            continue
        if len(c) < min_size:
            # 找前一个未被合并的块
            prev = i - 1
            while prev >= 0 and prev in merged_away:
                prev -= 1
            if prev >= 0:
                chunks[prev] = chunks[prev] + c
                merged_away.add(i)

    return [chunks[i].strip() for i in range(n)
            if i not in merged_away and chunks[i].strip()]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """两个向量的余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── 句子窗口切分 ──
def split_text_sentence_window(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
    window_size: int = 1,
) -> list[str]:
    """
    句子窗口：每条句子独立成块，但内容带上前后各 window_size 句的上下文。

    检索时用原句匹配 → 给 LLM 的上下文本身就是带窗口的完整片段。
    chunk_size 在这里控制窗口+原句的总长上限。
    """
    if not text or not text.strip():
        logger.warning("split_text_sentence_window 收到空文本，返回 []")
        return []

    sentences = [s.strip() for s in _SENTENCE.findall(text) if s.strip()]
    if not sentences:
        return []

    chunks = []
    for i, sent in enumerate(sentences):
        # 前后取各 window_size 句
        ctx_start = max(0, i - window_size)
        ctx_end = min(len(sentences), i + window_size + 1)
        context_sentences = sentences[ctx_start:ctx_end]
        chunk = "".join(context_sentences)
        # 截断到 chunk_size
        if len(chunk) > chunk_size:
            chunk = chunk[:chunk_size]
        if chunk.strip():
            chunks.append(chunk.strip())

    logger.info("分段完成(sentence_window)：{} 句 → {} 块 (window={})",
                len(sentences), len(chunks), window_size)
    return chunks


# ── 说话人切分 ──
_SPEAKER_MARKER = re.compile(r'\[(?:Speaker|说话人)\s*(\d+)\][：:]?\s*')


def _split_by_speaker(text: str) -> list[tuple[int, str]]:
    """按说话人标记切分文本。

    返回 [(speaker_id, segment_text), ...]，同一说话人的连续段落会合并。
    如果文本中没有说话人标记，返回 [(0, text)] 表示整段未标注。
    """
    # 找所有说话人标记位置
    positions: list[tuple[int, int, int]] = []  # (start, marker_end, speaker_id)
    for m in _SPEAKER_MARKER.finditer(text):
        positions.append((m.start(), m.end(), int(m.group(1))))

    if not positions:
        return [(0, text)]

    # 按标记切分
    segments: list[tuple[int, str]] = []
    for i, (start, marker_end, speaker_id) in enumerate(positions):
        # 当前段内容：从当前标记后到下一个标记前（或文本末尾）
        seg_end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        content = text[marker_end:seg_end].strip()
        if content:
            # 合并同一说话人的连续段
            if segments and segments[-1][0] == speaker_id:
                prev_id, prev_text = segments.pop()
                segments.append((speaker_id, prev_text + "\n" + content))
            else:
                segments.append((speaker_id, content))

    return segments


def split_text_speaker(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    说话人感知切分：按 [说话人N] 或 [SpeakerN] 标记分段，
    每个 chunk 内的内容来自同一说话人（或连续未标注段），
    长段在句末标点处带 overlap 断开。

    如果文本中没有说话人标记，退回 split_text（固定大小切分）。
    """
    if not text or not text.strip():
        logger.warning("split_text_speaker 收到空文本，返回 []")
        return []
    if overlap >= chunk_size:
        raise ValueError(f"overlap({overlap}) 必须小于 chunk_size({chunk_size})")

    segments = _split_by_speaker(text)
    if len(segments) == 1 and segments[0][0] == 0:
        logger.info("文本无说话人标记，退回 fixed 切分")
        return split_text(text, chunk_size, overlap)

    # 判断标记语言
    chinese_marker = bool(re.search(r'说话人', text))
    english_marker = bool(re.search(r'Speaker', text))

    chunks: list[str] = []
    for speaker_id, seg_text in segments:
        if len(seg_text) <= chunk_size:
            if chinese_marker:
                chunks.append(f"[说话人{speaker_id}]: {seg_text}")
            elif english_marker:
                chunks.append(f"[Speaker{speaker_id}]: {seg_text}")
            else:
                chunks.append(seg_text)
        else:
            # 长段原子化后合并
            units: list[str] = []
            for atom in _atomize(seg_text):
                if len(atom) > chunk_size:
                    units.extend(_hard_split(atom, chunk_size))
                else:
                    units.append(atom)

            if chinese_marker:
                prefix = f"[说话人{speaker_id}]: "
            elif english_marker:
                prefix = f"[Speaker{speaker_id}]: "
            else:
                prefix = ""

            cur, cur_len = [], len(prefix)
            for u in units:
                if cur and cur_len + len(u) > chunk_size:
                    chunks.append(prefix + "".join(cur).strip())
                    while cur and (cur_len - len(prefix) > overlap or cur_len + len(u) > chunk_size):
                        cur_len -= len(cur[0])
                        cur.pop(0)
                cur.append(u)
                cur_len += len(u)
            if cur:
                chunks.append(prefix + "".join(cur).strip())

    chunks = [c.strip() for c in chunks if c.strip()]
    logger.info("分段完成(speaker)：{} 个说话人段 → {} 块（chunk_size={}）",
                len(segments), len(chunks), chunk_size)
    return chunks


# ── 表格切分 ──

def split_table_rows(
    rows: list[list[str]],
    sheet_name: str = "Sheet1",
    chunk_size: int = 500,
) -> list[str]:
    """
    表格感知分段：每个 chunk = 表头行 + 若干数据行，凑到 chunk_size。

    表头 = 首行（全部非空时）或 Col1/Col2... 占位符。
    每个 chunk 都重复表头，保证独立可读。

    校验：
    - 行数不足（<2：仅表头无数据）→ 返回空列表
    - 列宽差异过大（max/min > 5）→ 返回空列表（非标准表格）
    """
    if not rows:
        return []

    # 裁剪尾随全空行
    while rows and all(not str(c).strip() for c in rows[-1]):
        rows.pop()
    if not rows:
        return []

    # 确定列数
    col_counts = [len(r) for r in rows]
    col_count = max(col_counts, default=0)
    if col_count == 0:
        return []

    # ── 校验：非标准表格拒绝 ──
    # 1. 仅表头无数据（< 2 行）
    if len(rows) < 2:
        logger.warning("split_table_rows: 表格仅 {} 行（无数据），拒绝分段", len(rows))
        return []

    # 2. 列宽差异过大——多数行列数一致，个别行偏宽/偏窄可能是合并单元格或解析异常
    #    统计列数分布，如果众数占比 < 70%，拒绝
    from collections import Counter
    col_dist = Counter(col_counts)
    top_count = col_dist.most_common(1)[0][1] if col_dist else 0
    if top_count < len(rows) * 0.7:
        logger.warning(
            "split_table_rows: 列数不一致（分布={}），疑似非标准表格，拒绝分段",
            dict(col_dist),
        )
        return []

    # 3. 宽幅差异：max_col / min_col > 5 → 可能是 OCR 碎片拼接，拒绝
    min_col = min(col_counts)
    max_col = max(col_counts)
    if min_col > 0 and max_col / min_col > 5:
        logger.warning(
            "split_table_rows: 列宽差异过大（{}~{}），疑似非标准表格，拒绝分段",
            min_col, max_col,
        )
        return []

    has_header = all(c.strip() for c in rows[0]) if rows[0] else False
    if has_header:
        header_row = rows[0]
        data_rows = rows[1:]
    else:
        header_row = [f"Col{i+1}" for i in range(col_count)]
        data_rows = rows[:]

    header_md = _row_to_md(header_row) + "\n" + _md_separator(len(header_row))
    header_len = len(header_md)

    sheet_prefix = f"## Sheet: {sheet_name}\n\n"
    min_chunk_size = max(chunk_size, header_len + len(sheet_prefix) + 80)
    min_chunk_size = min(min_chunk_size, chunk_size * 2)  # 不过度膨胀

    chunks: list[str] = []
    cur_rows: list[str] = []
    cur_len = len(sheet_prefix) + header_len

    for row in data_rows:
        row_str = _row_to_md(row)
        row_len = len(row_str) + 1  # +1 for \n
        if cur_rows and cur_len + row_len > min_chunk_size:
            chunks.append(sheet_prefix + header_md + "\n" + "".join(cur_rows))
            # 新块：重置，重复表头
            cur_rows = [row_str + "\n"]
            cur_len = len(sheet_prefix) + header_len + row_len
        else:
            cur_rows.append(row_str + "\n")
            cur_len += row_len

    if cur_rows:
        chunks.append(sheet_prefix + header_md + "\n" + "".join(cur_rows))

    logger.info("分段完成(table)：{} 行 → {} 块（chunk_size={}）",
                len(data_rows), len(chunks), chunk_size)
    return chunks


def _row_to_md(cells: list[str]) -> str:
    """一行转为 markdown 表格行。"""
    return "| " + " | ".join(
        str(c).replace("\n", " ").replace("|", "\\|") for c in cells
    ) + " |"


def _md_separator(ncols: int) -> str:
    """markdown 表格分隔行。"""
    return "| " + " | ".join(["---"] * ncols) + " |"
