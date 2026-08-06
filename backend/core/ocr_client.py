"""OCR/文档解析服务客户端：把文件发给版面解析服务，取 md_content 作为纯文本。
服务为 MinerU 类，POST /pdf_parse，返回 {md_content, md_content_detail}。
用途：扫描版 PDF 回退 + 图片(png/jpg)直接解析。失败抛异常，交由上层置 failed。"""
from pathlib import Path
import os
import time
import httpx
from loguru import logger

# 服务地址，通过环境变量配置
OCR_PARSE_URL = os.getenv("OCR_PARSE_URL", "")
OCR_TIMEOUT = 300.0  # 大文件 OCR 慢，给足超时


def parse_via_ocr(path: str, table_enable: bool = True, formula_enable: bool = False) -> str:
    """把文件发给解析服务，返回拼好的 md_content 纯文本。

    任何失败（网络/非 200/服务报错/空内容）都抛异常，
    由上层调用方（file_parser）捕获并做降级处理。

    table_enable: 是否启用表格识别
    formula_enable: 是否启用公式识别
    """
    p = Path(path)
    if not OCR_PARSE_URL:
        logger.warning("OCR 服务未配置（OCR_PARSE_URL 为空），将抛出异常由上层降级处理")
        raise RuntimeError("OCR 服务未配置，请设置 OCR_PARSE_URL 环境变量")
    if not p.is_file():
        raise FileNotFoundError(f"文件不存在: {path}")

    t0 = time.time()
    with open(p, "rb") as f:
        files = {"pdf_file": (p.name, f)}
        data = {
            "table_enable": str(table_enable).lower(),
            "formula_enable": str(formula_enable).lower(),
        }
        try:
            resp = httpx.post(OCR_PARSE_URL, files=files, data=data, timeout=OCR_TIMEOUT)
        except httpx.HTTPError as e:
            logger.error("OCR 请求异常 {}: {}", p.name, e)
            raise
    dt = time.time() - t0

    if resp.status_code != 200:
        logger.error("OCR 返回 HTTP {} {}: {}", resp.status_code, p.name, resp.text[:200])
        raise RuntimeError(f"OCR 服务 HTTP {resp.status_code}")

    body = resp.json()
    if isinstance(body, dict) and body.get("error"):
        logger.error("OCR 服务报错 {}: {}", p.name, body["error"])
        raise RuntimeError(f"OCR 服务错误: {body['error']}")

    md = (body or {}).get("md_content", "") or ""
    if not md.strip():
        logger.error("OCR {} 返回空内容（{:.1f}s）", p.name, dt)
        raise RuntimeError("OCR 返回空内容（可能是空白页或解析失败）")

    logger.info("OCR 解析 {} 完成：{} 字符，耗时 {:.1f}s", p.name, len(md), dt)
    return md
