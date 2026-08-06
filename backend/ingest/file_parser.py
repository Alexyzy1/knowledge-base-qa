import csv
import io
from pathlib import Path
from loguru import logger
import fitz  # PyMuPDF
from docx import Document
import openpyxl
import xlrd
from pptx import Presentation
from backend.core.ocr_client import parse_via_ocr
from backend import config
from backend.core.asr_client import parse_audio as _parse_audio_legacy, parse_video

# 扫描版判定阈值：平均每页可抽取文本低于此字符数 → 判为扫描版，回退 OCR
OCR_MIN_CHARS_PER_PAGE = 10


def _sanitize_sheet_name(name: str) -> str:
    """清理工作表名：去换行、限制长度。"""
    return name.strip().replace("\n", " ")[:60]


def _rows_to_markdown_table(rows: list[list[str]], max_cols: int | None = None) -> str:
    """将行列数据转为 markdown 表格字符串。

    首行全部非空时视为表头；否则生成 Col1/Col2... 占位表头。
    自动处理管道符转义、换行符替换、尾随空行裁剪、列数补齐。
    """
    if not rows:
        return ""

    # 裁剪尾随全空行
    while rows and all(not str(c).strip() for c in rows[-1]):
        rows.pop()
    if not rows:
        return ""

    # 确定列数
    col_count = max((len(r) for r in rows), default=0)
    if max_cols is not None:
        col_count = max(col_count, max_cols)
    if col_count == 0:
        return ""

    # 补齐各行到相同列数
    padded = []
    for r in rows:
        pr = [str(c) if c is not None else "" for c in r]
        pr += [""] * (col_count - len(pr))
        padded.append(pr)

    # 判断首行是否为表头
    has_header = padded and all(c.strip() for c in padded[0])

    if has_header:
        header = padded[0]
        body = padded[1:]
    else:
        header = [f"Col{i+1}" for i in range(col_count)]
        body = padded

    def _fmt_row(cells):
        return "| " + " | ".join(
            str(c).replace("\n", " ").replace("|", "\\|") for c in cells
        ) + " |"

    lines = [_fmt_row(header)]
    lines.append("| " + " | ".join(["---"] * col_count) + " |")
    for row in body:
        lines.append(_fmt_row(row))

    return "\n".join(lines)


def _read_text(path: Path) -> str:
    """txt/md：utf-8 → gbk 容错读取。"""
    raw = path.read_bytes()
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_pdf(path: Path, ocr_enabled: bool = True,
               table_enable: bool = True, formula_enable: bool = False) -> str:
    """PDF：优先走 OCR 版面解析（含表格、标题、阅读顺序），失败则降级 PyMuPDF。

    ocr_enabled=False 时跳过 OCR 直接走 PyMuPDF；OCR 失败也降级 PyMuPDF，
    双重失败（PyMuPDF 也抽不出文字）则抛异常，由 pipeline 兜底置 failed。
    """
    if ocr_enabled:
        try:
            text = parse_via_ocr(str(path), table_enable=table_enable, formula_enable=formula_enable)
            logger.info("PDF {} OCR 版面解析完成：{} 字符", path.name, len(text))
            return text
        except Exception as e:
            logger.warning("PDF {} OCR 解析失败，降级 PyMuPDF: {}", path.name, e)

    # 降级：PyMuPDF 抽文本（OCR 未开 或 OCR 失败）
    parts = []
    with fitz.open(str(path)) as doc:
        n_pages = doc.page_count
        for page in doc:
            parts.append(page.get_text())
    text = "\n".join(parts)

    if not text.strip():
        raise RuntimeError(f"PDF {path.name} 文字提取和 OCR 均失败")

    logger.info("PDF {} PyMuPDF 降级抽取：{} 字符（{} 页）", path.name, len(text), n_pages)
    return text


def _parse_docx(path: Path) -> str:
    """docx：段落 + 表格单元格。"""
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.extend(c.text for c in row.cells)
    return "\n".join(parts)


def _parse_image(path: Path, ocr_enabled: bool = True,
                 table_enable: bool = True, formula_enable: bool = False) -> str:
    """图片(png/jpg/jpeg)：走 OCR 服务做版面解析 + 表格识别。

    ocr_enabled=False 时返回空字符串（不抛异常，由 pipeline 判空后置 failed）。
    """
    if not ocr_enabled:
        logger.warning("图片 {} OCR 已禁用，返回空", path.name)
        return ""
    logger.info("图片 {} → OCR 解析", path.name)
    return parse_via_ocr(str(path), table_enable=table_enable, formula_enable=formula_enable)


def _parse_csv(path: Path) -> tuple[list[list[str]], str]:
    """CSV → (行数据列表, 格式提示)。"""
    raw = Path(str(path)).read_bytes()
    for enc in ("utf-8", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    try:
        dialect = csv.Sniffer().sniff(text[:8192])
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    return (list(csv.reader(io.StringIO(text), delimiter=delimiter)), "csv")


def _parse_xlsx(path: Path) -> tuple[list[list[str]], str]:
    """XLSX → (行数据列表, sheet_name)。"""
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    rows_all: list[list[str]] = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        for row in ws.iter_rows():
            rows_all.append([cell.value for cell in row])
    wb.close()
    logger.info("XLSX {} 解析：{} 个工作表 → {} 行", path.name, len(wb.sheetnames), len(rows_all))
    return (rows_all, _sanitize_sheet_name(wb.sheetnames[0]) if wb.sheetnames else "Sheet1")


def _parse_xls(path: Path) -> tuple[list[list[str]], str]:
    """XLS → (行数据列表, sheet_name)。"""
    wb = xlrd.open_workbook(str(path))
    rows_all: list[list[str]] = []
    for sheet in wb.sheets():
        for row_idx in range(sheet.nrows):
            rows_all.append([sheet.cell_value(row_idx, col_idx) for col_idx in range(sheet.ncols)])
    logger.info("XLS {} 解析：{} 个工作表 → {} 行", path.name, len(wb.sheets()), len(rows_all))
    return (rows_all, _sanitize_sheet_name(wb.sheets()[0].name) if wb.sheets() else "Sheet1")


def _parse_pptx(path: Path) -> str:
    """PPTX：逐页提取文本，以 ## Slide N 分节；支持文本框、表格、组合形状。"""
    prs = Presentation(str(path))
    parts = []

    def _extract_shape_text(shape) -> list[str]:
        """递归提取形状中的文本行。"""
        texts = []
        if shape.has_text_frame:
            for para in shape.text_frame.paragraphs:
                line = para.text
                if line.strip():
                    texts.append(line.strip())
        if shape.has_table:
            table = shape.table
            rows = []
            for row in table.rows:
                rows.append([cell.text for cell in row.cells])
            if rows:
                texts.append(_rows_to_markdown_table(rows))
        if shape.shape_type == 6:  # MSO_SHAPE_TYPE.GROUP
            for child in shape.shapes:
                texts.extend(_extract_shape_text(child))
        return texts

    for slide_num, slide in enumerate(prs.slides, start=1):
        slide_texts = []
        for shape in slide.shapes:
            slide_texts.extend(_extract_shape_text(shape))
        if slide_texts:
            parts.append(f"## Slide {slide_num}\n\n" + "\n\n".join(slide_texts))

    result = "\n\n".join(parts)
    logger.info("PPTX {} 解析：{} 张有内容幻灯片 → {} 字符",
                path.name, len(parts), len(result))
    return result


# 音视频格式：通过 ASR 服务转写为文字
_AUDIO_SUFFIXES = {".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".amr"}
_VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".mpeg", ".mpg", ".3gp", ".m4v"}


def _get_qwen_parse_audio():
    """惰性导入 Qwen ASR 客户端，模块缺失时返回 None。"""
    try:
        from backend.core.asr_client_qwen import parse_audio
        return parse_audio
    except ImportError:
        return None


def _parse_audio_video(path: Path) -> str:
    """音频/视频文件：调用 ASR 服务将语音转写为文字。
    音频根据 ASR_ENGINE 选择引擎，视频始终走旧服务 /video_chat。
    """
    suffix = path.suffix.lower()
    if suffix in _VIDEO_SUFFIXES:
        return parse_video(str(path), only_extract_audio=True)
    else:
        if config.ASR_ENGINE == "qwen":
            qwen_parse = _get_qwen_parse_audio()
            if qwen_parse is None:
                raise RuntimeError(
                    "ASR_ENGINE 设为 'qwen'，但 asr_client_qwen 模块未找到或导入失败"
                )
            return qwen_parse(str(path), filename=path.name)
        return _parse_audio_legacy(str(path))


_PARSERS = {
    ".txt": _read_text,
    ".md": _read_text,
    ".docx": _parse_docx,
    ".csv": _parse_csv,
    ".xlsx": _parse_xlsx,
    ".xls": _parse_xls,
    ".pptx": _parse_pptx,
    # 音视频格式 → ASR 转写
    ".mp3": _parse_audio_video, ".flac": _parse_audio_video, ".wav": _parse_audio_video,
    ".aac": _parse_audio_video, ".m4a": _parse_audio_video, ".ogg": _parse_audio_video,
    ".opus": _parse_audio_video, ".wma": _parse_audio_video, ".amr": _parse_audio_video,
    ".mp4": _parse_audio_video, ".avi": _parse_audio_video, ".mov": _parse_audio_video,
    ".mkv": _parse_audio_video, ".flv": _parse_audio_video, ".wmv": _parse_audio_video,
    ".webm": _parse_audio_video, ".mpeg": _parse_audio_video, ".mpg": _parse_audio_video,
    ".3gp": _parse_audio_video, ".m4v": _parse_audio_video,
}

# 表格格式：解析器返回 (rows, sheet_name) 而非纯文本
_TABLE_SUFFIXES = {".csv", ".xlsx", ".xls"}

# OCR 能力覆盖的格式（pdf 优先 OCR、图片强制 OCR）
_OCR_FORMATS = {".pdf", ".png", ".jpg", ".jpeg"}


def parse_file(path: str, ocr_enabled: bool = True,
               table_enable: bool = True, formula_enable: bool = False):
    """统一出口：按扩展名解析。

    返回:
      - 普通格式 → str（纯文本）
      - 表格格式 (.csv/.xlsx/.xls) → (rows: list[list[str]], sheet_name: str)

    ocr_enabled:   是否启用 OCR 版面解析（对 PDF/图片有效）。关闭后 PDF 走 PyMuPDF，图片返回空。
    table_enable:  OCR 时是否提取表格（Markdown 格式）。
    formula_enable: OCR 时是否提取公式（LaTeX 格式）。
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"文件不存在: {path}")
    suffix = p.suffix.lower()

    # OCR-capable formats: route with OCR config
    if suffix in _OCR_FORMATS:
        if suffix == ".pdf":
            text = _parse_pdf(p, ocr_enabled=ocr_enabled,
                              table_enable=table_enable, formula_enable=formula_enable)
        else:
            text = _parse_image(p, ocr_enabled=ocr_enabled,
                                table_enable=table_enable, formula_enable=formula_enable)
    else:
        parser = _PARSERS.get(suffix)
        if parser is None:
            raise ValueError(f"不支持的文件类型: {suffix}（支持 {list(_PARSERS)} + {list(_OCR_FORMATS)}）")
        text = parser(p)

    logger.info("解析 {} 完成：{} 字符", p.name, len(text))
    return text
