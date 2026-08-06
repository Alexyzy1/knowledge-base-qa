"""ASR/音视频转写服务客户端：把音频/视频文件发给多模态处理服务，取转写文本。
服务提供 /audio_chat 和 /video_chat 两个端点。
用途：音频(mp3/flac/wav/...)和视频(mp4/avi/mov/...)的内容转写。失败抛异常，由上层兜底置 failed。
"""
from pathlib import Path
import os
import time
import httpx
from loguru import logger

ASR_BASE_URL = os.getenv("ASR_BASE_URL", "")
AUDIO_CHAT_URL = f"{ASR_BASE_URL}/audio_chat" if ASR_BASE_URL else ""
VIDEO_CHAT_URL = f"{ASR_BASE_URL}/video_chat" if ASR_BASE_URL else ""
ASR_TIMEOUT = 600.0  # 大文件转写可能较慢


def parse_audio(path: str) -> str:
    """把音频文件发给 /audio_chat，返回转写文本。

    任何失败（网络/非 200/服务报错/空内容）都抛异常，
    由上层调用方（file_parser）捕获并抛出让 pipeline 兜底置 failed。
    """
    p = Path(path)
    if not AUDIO_CHAT_URL:
        raise RuntimeError("ASR 服务未配置，请设置 ASR_BASE_URL 环境变量")
    if not p.is_file():
        raise FileNotFoundError(f"音频文件不存在: {path}")

    t0 = time.time()
    with open(p, "rb") as f:
        files = {"audio_file": (p.name, f)}
        data = {"audio_name": p.name}
        try:
            resp = httpx.post(AUDIO_CHAT_URL, files=files, data=data, timeout=ASR_TIMEOUT)
        except httpx.HTTPError as e:
            logger.error("ASR 音频请求异常 {}: {}", p.name, e)
            raise

    dt = time.time() - t0

    if resp.status_code != 200:
        logger.error("ASR 音频返回 HTTP {} {}: {}", resp.status_code, p.name, resp.text[:200])
        raise RuntimeError(f"ASR 音频服务 HTTP {resp.status_code}")

    body = resp.json()
    if isinstance(body, dict) and body.get("error"):
        logger.error("ASR 音频服务报错 {}: {}", p.name, body)
        raise RuntimeError(f"ASR 音频服务错误: {body}")

    text = (body or {}).get("audio_text", "") or ""
    if not text.strip():
        logger.error("ASR 音频 {} 返回空内容（{:.1f}s）", p.name, dt)
        raise RuntimeError("ASR 音频转写返回空内容")

    logger.info("ASR 音频 {} 转写完成：{} 字符，耗时 {:.1f}s", p.name, len(text), dt)
    return text


def parse_video(path: str, only_extract_audio: bool = True) -> str:
    """把视频文件发给 /video_chat，返回转写文本。

    only_extract_audio=True 时仅提取音频转文字（跳过视频图像识别，更快速）。
    """
    p = Path(path)
    if not VIDEO_CHAT_URL:
        raise RuntimeError("ASR 服务未配置，请设置 ASR_BASE_URL 环境变量")
    if not p.is_file():
        raise FileNotFoundError(f"视频文件不存在: {path}")

    t0 = time.time()
    with open(p, "rb") as f:
        files = {"video_file": (p.name, f)}
        data = {
            "video_name": p.name,
            "only_extract_audio": str(only_extract_audio).lower(),
        }
        try:
            resp = httpx.post(VIDEO_CHAT_URL, files=files, data=data, timeout=ASR_TIMEOUT)
        except httpx.HTTPError as e:
            logger.error("ASR 视频请求异常 {}: {}", p.name, e)
            raise

    dt = time.time() - t0

    if resp.status_code != 200:
        logger.error("ASR 视频返回 HTTP {} {}: {}", resp.status_code, p.name, resp.text[:200])
        raise RuntimeError(f"ASR 视频服务 HTTP {resp.status_code}")

    body = resp.json()
    if isinstance(body, dict) and body.get("error"):
        logger.error("ASR 视频服务报错 {}: {}", p.name, body)
        raise RuntimeError(f"ASR 视频服务错误: {body}")

    text = (body or {}).get("video_text", "") or ""
    if not text.strip():
        logger.error("ASR 视频 {} 返回空内容（{:.1f}s）", p.name, dt)
        raise RuntimeError("ASR 视频转写返回空内容")

    logger.info("ASR 视频 {} 转写完成：{} 字符，耗时 {:.1f}s", p.name, len(text), dt)
    return text
