"""Qwen3-ASR 客户端：OpenAI Chat Completions 兼容协议。
发送 base64 编码的音频到 /v1/chat/completions，返回转写文本。
用途：多种音频格式的内容转写。失败抛异常，由上层兜底置 failed。

长音频处理：
- 超过 QWEN_ASR_SPLIT_THRESHOLD（默认 60s）时，通过 ffmpeg silencedetect 检测静音间隙
- 在静音点切分为多个短段，通过 ThreadPoolExecutor 并发调用 API
- ffmpeg/ffprobe 缺失时自动降级为单次调用
"""
import base64
import os
import re
import shutil
import subprocess
import tempfile
import time
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from loguru import logger

from backend import config

# 文件后缀名到 MIME 类型的映射
_AUDIO_MIME_MAP = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".opus": "audio/ogg",   # 以 OGG MIME 类型发送
    ".wma": "audio/wav",    # 回退为通用 WAV
    ".amr": "audio/wav",    # 回退为通用 WAV
}


# ── 单段 API 调用（核心 HTTP 逻辑，不含切分） ──

def _call_api_single(path: str, prompt: str | None = None,
                     filename: str | None = None, wrap: bool = True) -> str:
    """把单个音频文件发给 Qwen3-ASR，返回转写文本。

    prompt 可选：传入说话人标注等指令。
    filename 可选：用于输出格式包装，默认使用文件名。
    wrap=False 时返回裸文本（用于切分段内部调用）。

    任何失败（网络/非 200/服务报错/空内容）都抛异常，
    由上层调用方捕获并抛出让 pipeline 兜底置 failed。
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"音频文件不存在: {path}")

    suffix = p.suffix.lower()
    mime_type = _AUDIO_MIME_MAP.get(suffix, "audio/wav")

    t0 = time.time()

    # preprocess audio for Qwen compatibility — resample non-standard WAV rates
    from backend.core.audio_utils import preprocess_audio_if_needed

    audio_path_str = path
    _cleanup_path: str | None = None
    try:
        audio_path_str, was_processed = preprocess_audio_if_needed(path)
        if was_processed:
            _cleanup_path = audio_path_str
            p2 = Path(audio_path_str)
        else:
            p2 = p
    except RuntimeError:
        raise
    except Exception as exc:
        logger.error("Qwen ASR 音频预处理异常 {}: {}", p.name, exc)
        raise RuntimeError(f"音频文件预处理失败: {p.name}") from exc

    try:
        with open(audio_path_str, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    finally:
        if _cleanup_path:
            try:
                os.unlink(_cleanup_path)
            except OSError:
                pass

    # log large file warning — base64 adds 33% payload overhead
    file_size = p.stat().st_size
    file_size_mb = file_size / (1024 * 1024)
    if file_size_mb > 8:
        logger.warning(
            "Qwen ASR: 大音频 {} ({:.1f}MB), base64 后约 {:.1f}MB, 预计 ~{} tokens",
            p.name, file_size_mb, file_size_mb * 1.33, int(file_size * 0.35))

    audio_url = f"data:{mime_type};base64,{b64}"

    content_blocks = [
        {"type": "audio_url", "audio_url": {"url": audio_url}}
    ]
    if prompt:
        content_blocks.append({"type": "text", "text": prompt})

    payload = {
        "model": config.QWEN_ASR_MODEL,
        "stream": False,
        "temperature": 0.01,
        "messages": [{
            "role": "user",
            "content": content_blocks
        }]
    }

    headers = {
        "Authorization": f"Bearer {config.QWEN_ASR_API_KEY}",
        "Content-Type": "application/json",
    }

    url = f"{config.QWEN_ASR_BASE_URL.rstrip('/')}/v1/chat/completions"

    logger.debug("Qwen ASR 请求: url={} model={} mime={} size={}",
                 url, config.QWEN_ASR_MODEL, mime_type, p.stat().st_size)

    try:
        resp = httpx.post(url, json=payload, headers=headers,
                          timeout=config.QWEN_ASR_TIMEOUT)
    except httpx.HTTPError as e:
        logger.error("Qwen ASR 请求异常 {}: {}", p.name, e)
        raise

    dt = time.time() - t0

    logger.debug("Qwen ASR 响应: status={} dt={:.1f}s", resp.status_code, dt)

    if resp.status_code != 200:
        logger.error("Qwen ASR 返回 HTTP {} {}: {}", resp.status_code, p.name, resp.text[:200])
        raise RuntimeError(f"Qwen ASR 服务 HTTP {resp.status_code}")

    body = resp.json()
    if isinstance(body, dict) and body.get("error"):
        logger.error("Qwen ASR 服务报错 {}: {}", p.name, body)
        raise RuntimeError(f"Qwen ASR 服务错误: {body}")

    try:
        choices = body.get("choices", [])
        if not choices:
            raise ValueError("响应中无 choices")
        raw_text = choices[0].get("message", {}).get("content", "") or ""
    except (IndexError, KeyError, TypeError, ValueError) as e:
        logger.error("Qwen ASR 响应格式异常 {}: {}", p.name, e)
        raise RuntimeError(f"Qwen ASR 响应格式异常: {e}")

    logger.debug("Qwen ASR 原始响应: {!r}", raw_text[:200])

    # remove "language Chinese<asr_text>" prefix
    text = re.sub(r"^language\s+\w+<asr_text>\s*", "", raw_text).strip()

    if not text:
        logger.error("Qwen ASR 音频 {} 返回空内容（原始: {!r}, {:.1f}s）", p.name, raw_text[:100], dt)
        raise RuntimeError("ASR 音频转写返回空内容")

    # normalize output format to match Legacy ASR structure
    # Note: ingest_pipeline adds its own [filename] prefix per chunk,
    # so we add the audio wrapper format WITHOUT the duplicate [filename] header
    if wrap:
        display_name = filename or p.name
        text = f"音频 {display_name} 的主要内容如下：\n# 音频内容：\n{text}"

    logger.info("Qwen ASR 音频 {} 转写完成：{} 字符，耗时 {:.1f}s", p.name, len(text), dt)
    return text


# ── 二进制工具检测 ──

def _find_binary(path_config: str) -> str | None:
    """查找 ffmpeg/ffprobe 二进制文件。

    先尝试 shutil.which（PATH 搜索），再尝试文件路径检测（支持相对/绝对路径）。
    相对路径会基于项目根目录（backend/../ = yuanzy/）解析。
    找不到返回 None。
    """
    # 1) PATH 搜索
    result = shutil.which(path_config)
    if result is not None:
        return result
    # 2) 绝对路径直接检测
    if os.path.isabs(path_config) and os.path.isfile(path_config):
        return path_config
    # 3) 相对路径：基于项目根目录解析
    # __file__ = backend/core/asr_client_qwen.py
    # dirname x3 → yuanzy/
    _proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidate = os.path.join(_proj_root, path_config)
    if os.path.isfile(candidate):
        return candidate
    logger.debug("未找到二进制文件: {}", path_config)
    return None


# ── ffprobe / ffmpeg 子进程封装 ──

def _ffprobe_duration(path: str) -> float | None:
    """通过 ffprobe 获取音频时长（秒），失败返回 None。"""
    ffprobe = _find_binary(config.QWEN_ASR_FFPROBE_PATH)
    if ffprobe is None:
        logger.warning("ffprobe ({}) 不可用，跳过时长检测",
                       config.QWEN_ASR_FFPROBE_PATH)
        return None

    try:
        result = subprocess.run(
            [ffprobe, "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.warning("ffprobe 返回非零 {}: stderr={!r}",
                           result.returncode, result.stderr[:200])
            return None
        return float(result.stdout.strip())
    except FileNotFoundError:
        logger.warning("ffprobe 命令未找到: {}", ffprobe)
        return None
    except subprocess.TimeoutExpired:
        logger.warning("ffprobe 超时 ({} 秒): {}", 30, Path(path).name)
        return None
    except (ValueError, OSError) as e:
        logger.warning("ffprobe 解析失败 {}: {}", Path(path).name, e)
        return None


def _ffmpeg_silence_points(path: str) -> list[float]:
    """运行 ffmpeg silencedetect，返回"可切分点"列表（秒）。

    对每组 silence_start / silence_end，取中点为切分点。
    """
    ffmpeg = _find_binary(config.QWEN_ASR_FFMPEG_PATH)
    if ffmpeg is None:
        logger.warning("ffmpeg ({}) 不可用，跳过静音检测",
                       config.QWEN_ASR_FFMPEG_PATH)
        return []

    filter_spec = (
        f"silencedetect=n={config.QWEN_ASR_SILENCE_DB}dB:"
        f"d={config.QWEN_ASR_SILENCE_DURATION}"
    )

    try:
        result = subprocess.run(
            [ffmpeg, "-i", path, "-af", filter_spec, "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        logger.warning("ffmpeg 命令未找到: {}", ffmpeg)
        return []
    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg silencedetect 超时: {}", Path(path).name)
        return []
    except OSError as e:
        logger.warning("ffmpeg silencedetect 系统错误 {}: {}", Path(path).name, e)
        return []

    # 解析 stderr 中的 silence_start / silence_end
    # [silencedetect @ 0x...] silence_start: 12.34
    # [silencedetect @ 0x...] silence_end: 13.57 | silence_duration: 1.23
    starts: list[float] = []
    ends: list[float] = []
    for line in result.stderr.splitlines():
        if "silence_start:" in line:
            try:
                starts.append(float(line.split("silence_start:")[1].strip().split()[0]))
            except (ValueError, IndexError):
                pass
        if "silence_end:" in line:
            try:
                ends.append(float(line.split("silence_end:")[1].strip().split()[0]))
            except (ValueError, IndexError):
                pass

    # 每组 (start, end) 取中点作为切分点
    cut_points = []
    for s, e in zip(starts, ends):
        mid = (s + e) / 2.0
        cut_points.append(round(mid, 2))

    if cut_points:
        logger.debug("静音检测到 {} 个切分点: {}", len(cut_points), cut_points[:10])
    else:
        logger.debug("未检测到静音段")
    return cut_points


# ── 切分边界计算 ──

def _compute_split_boundaries(
    duration: float,
    silence_points: list[float],
) -> list[tuple[float, float]]:
    """给定音频时长和静音切分点，返回 [(start, end), ...] 切分列表。

    约束：
    - 每段时长 ≥ QWEN_ASR_MIN_SEGMENT（尾段除外）
    - 每段时长 ≤ QWEN_ASR_MAX_SEGMENT
    - 优先在静音点切分
    - 无静音点或段仍过长时，用 QWEN_ASR_MAX_SEGMENT 均匀切分
    """
    min_seg = config.QWEN_ASR_MIN_SEGMENT
    max_seg = config.QWEN_ASR_MAX_SEGMENT

    # Step 1: 过滤静音点——去掉太靠近首尾或太靠近上一个切分点的
    valid_cuts: list[float] = [0.0]
    for pt in silence_points:
        if pt < min_seg:                      # 太靠近开头
            continue
        if pt > duration - min_seg:           # 太靠近结尾
            continue
        if pt - valid_cuts[-1] < min_seg:     # 离上一个切点太近
            continue
        valid_cuts.append(pt)
    valid_cuts.append(duration)

    # Step 2: 对每段超过 max_seg 的区间做均匀切分
    boundaries: list[tuple[float, float]] = []
    for i in range(len(valid_cuts) - 1):
        seg_start = valid_cuts[i]
        seg_end = valid_cuts[i + 1]
        seg_dur = seg_end - seg_start

        if seg_dur <= max_seg:
            boundaries.append((seg_start, seg_end))
        else:
            # 均匀切分，每段尽可能接近 max_seg
            n_parts = math.ceil(seg_dur / max_seg)
            part_dur = seg_dur / n_parts
            for k in range(n_parts):
                part_start = seg_start + k * part_dur
                part_end = part_start + part_dur if k < n_parts - 1 else seg_end
                boundaries.append((round(part_start, 2), round(part_end, 2)))

    return boundaries


# ── ffmpeg 音频段提取 ──

def _ffmpeg_extract_segment(
    input_path: str,
    start: float,
    duration: float,
    output_path: str,
) -> None:
    """用 ffmpeg -ss/-t 提取音频段（流复制，不重编码）。"""
    ffmpeg = _find_binary(config.QWEN_ASR_FFMPEG_PATH)
    if ffmpeg is None:
        raise RuntimeError(
            f"ffmpeg ({config.QWEN_ASR_FFMPEG_PATH}) 不可用，无法提取音频段"
        )

    # 先用流复制 (-c copy) 快速提取
    cmd_copy = [
        ffmpeg, "-y", "-ss", str(start), "-i", input_path,
        "-t", str(duration), "-c", "copy", output_path,
    ]
    result = subprocess.run(cmd_copy, capture_output=True, text=True, timeout=60)

    if result.returncode != 0:
        # 流复制失败（某些格式不支持 seek），降级为重编码
        logger.debug("ffmpeg -c copy 失败，降级重编码: {}", result.stderr[:200])
        cmd_reencode = [
            ffmpeg, "-y", "-ss", str(start), "-i", input_path,
            "-t", str(duration), output_path,
        ]
        subprocess.run(cmd_reencode, capture_output=True, check=True, timeout=120)


# ── 段并发转写 ──

def _transcribe_segment(args: tuple) -> tuple[int, str]:
    """单个音频段的转写，返回 (index, raw_text)。供 ThreadPoolExecutor 使用。
    不包 wrapper（由外层统一包装）。"""
    index, seg_path, prompt = args
    try:
        text = _call_api_single(seg_path, prompt, wrap=False)
        return (index, text)
    except Exception:
        logger.exception("音频段 {} (index={}) 转写失败", Path(seg_path).name, index)
        raise


# ── 公开入口 ──

def parse_audio(path: str, prompt: str | None = None,
                filename: str | None = None) -> str:
    """把音频文件发给 Qwen3-ASR，返回转写文本。

    prompt 可选：传入说话人标注等指令，模型会尝试在输出中遵循。
    filename 可选：用于输出格式包装，默认使用文件名。

    对超过 QWEN_ASR_SPLIT_THRESHOLD 的长音频自动切分+并发：
    - ffmpeg silencedetect 找静音间隙 → 切分
    - ThreadPoolExecutor 并发调用 API
    - 按序拼接结果

    ffmpeg/ffprobe 缺失时自动降级为单次调用。

    任何失败（网络/非 200/服务报错/空内容）都抛异常，
    由上层调用方（file_parser）捕获并抛出让 pipeline 兜底置 failed。
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"音频文件不存在: {path}")

    # Step 1: 检查时长，判断是否需要切分
    duration = _ffprobe_duration(path)
    if duration is None:
        logger.info("Qwen ASR 无法获取音频时长，走单次调用: {}", p.name)
        return _call_api_single(path, prompt, filename)

    if duration <= config.QWEN_ASR_SPLIT_THRESHOLD:
        logger.debug("Qwen ASR 音频 {} 时长 {:.1f}s ≤ {}s 阈值，单次调用",
                     p.name, duration, config.QWEN_ASR_SPLIT_THRESHOLD)
        return _call_api_single(path, prompt, filename)

    logger.info("Qwen ASR 音频 {} 时长 {:.1f}s > {}s 阈值，启动切分流程",
                p.name, duration, config.QWEN_ASR_SPLIT_THRESHOLD)

    # Step 2: 检测静音点
    silence_points = _ffmpeg_silence_points(path)

    # Step 3: 计算切分边界
    boundaries = _compute_split_boundaries(duration, silence_points)

    if len(boundaries) <= 1:
        logger.info("Qwen ASR 音频 {} 切分边界计算后仅 {} 段，退回单次调用",
                    p.name, len(boundaries))
        return _call_api_single(path, prompt, filename)

    logger.info("Qwen ASR 将 {:.1f}s 音频切分为 {} 段（静音点: {}）",
                duration, len(boundaries), len(silence_points))

    # Step 4: 提取各段到临时文件
    suffix = p.suffix.lower()
    temp_dir = tempfile.mkdtemp(prefix="asr_segments_")
    temp_files: list[str] = []

    t0_total = time.time()

    try:
        for i, (start, end) in enumerate(boundaries):
            seg_path = os.path.join(temp_dir, f"seg_{i:03d}{suffix}")
            _ffmpeg_extract_segment(path, start, end - start, seg_path)
            temp_files.append(seg_path)
            logger.debug("段 {}: {:.1f}s → {:.1f}s → {}", i, start, end, seg_path)

        # Step 5: 并发转写
        max_workers = min(config.QWEN_ASR_MAX_CONCURRENT, len(temp_files))
        seg_args = [(i, seg_path, prompt) for i, seg_path in enumerate(temp_files)]

        results: dict[int, str] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(_transcribe_segment, args): args[0]
                for args in seg_args
            }
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    seg_idx, text = future.result()
                    results[seg_idx] = text
                    logger.info("段 {}/{} 转写完成：{} 字符",
                                seg_idx + 1, len(temp_files), len(text))
                except Exception:
                    # 任一段失败 → 取消其余（尽力）并传播异常
                    logger.error("段 {}/{} 转写失败，取消其余段",
                                 idx + 1, len(temp_files))
                    for f in future_to_idx:
                        f.cancel()
                    raise

        # Step 6: 按序拼接（段内无 wrapper，直接拼）
        ordered = [results[i] for i in range(len(temp_files))]
        # 段间用空格分隔，保证英文可读性（静音段自然断句点，空格连续句）
        full_text = " ".join(ordered).strip()

        # 统一加格式包装
        display_name = filename or p.name
        full_text = (
            f"音频 {display_name} 的主要内容如下：\n"
            f"# 音频内容：\n{full_text}"
        )

        dt_total = time.time() - t0_total
        logger.info(
            "Qwen ASR 切分转写完成：{:.1f}s → {} 段，{} 字符，总耗时 {:.1f}s",
            duration, len(temp_files), len(full_text), dt_total,
        )
        return full_text

    finally:
        # Step 7: 清理临时文件
        for seg_path in temp_files:
            try:
                os.remove(seg_path)
            except OSError:
                pass
        try:
            os.rmdir(temp_dir)
        except OSError:
            pass
