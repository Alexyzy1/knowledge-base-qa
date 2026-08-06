"""Audio utility functions for ASR preprocessing — pure stdlib, no dependencies.

Provides WAV header inspection, non-standard sample rate detection,
and linear-interpolation resampling.  Only wave/struct/tempfile/os are used,
so it works in environments without ffmpeg/pydub/librosa.
"""

import os
import struct
import tempfile
import wave
from loguru import logger

# WAV sample rates that Qwen3-ASR is known to handle.
# 8kHz excluded — tested and returns "language None" (empty).
_QWEN_SUPPORTED_RATES = {16000, 24000, 44100, 48000}

# Target rate for resampling (16kHz mono is well-supported by ASR models).
_DEFAULT_TARGET_RATE = 16000


def get_wav_info(path: str) -> dict | None:
    """Read WAV header and return (nchannels, sampwidth, framerate, nframes, duration).
    Returns None if the file is not a valid WAV or cannot be read.
    """
    try:
        with wave.open(path, 'rb') as wf:
            params = wf.getparams()
            nchannels, sampwidth, framerate, nframes = (
                params.nchannels, params.sampwidth, params.framerate, params.nframes)
            duration = nframes / framerate if framerate > 0 else 0.0
            return {
                "nchannels": nchannels,
                "sampwidth": sampwidth,
                "framerate": framerate,
                "nframes": nframes,
                "duration": duration,
            }
    except Exception:
        return None


def needs_resampling(path: str) -> bool:
    """Return True if this is a WAV with a sample rate Qwen3-ASR won't handle."""
    info = get_wav_info(path)
    if info is None:
        return False  # not a WAV, or unreadable — let ASR deal with it
    return info["framerate"] not in _QWEN_SUPPORTED_RATES


def resample_wav_linear(src_path: str, dst_path: str, target_rate: int = _DEFAULT_TARGET_RATE) -> bool:
    """Resample a WAV file to target_rate using linear interpolation.

    Reads 16-bit PCM frames, linearly interpolates to the new rate,
    and writes the result.  Only 16-bit mono/stereo is supported.

    Returns True on success, False if the file cannot be processed.
    """
    try:
        with wave.open(src_path, 'rb') as wf_src:
            params = wf_src.getparams()
            src_rate = params.framerate
            nchannels = params.nchannels
            sampwidth = params.sampwidth
            src_frames = wf_src.readframes(params.nframes)

        if src_rate == target_rate:
            # no resampling needed — just copy
            with wave.open(dst_path, 'wb') as wf_dst:
                wf_dst.setparams(params)
                wf_dst.writeframes(src_frames)
            return True

        if sampwidth not in (1, 2):
            logger.warning("WAV 重采样不支持 {} 字节采样位深: {}", sampwidth, os.path.basename(src_path))
            return False

        # decode samples
        total_samples = len(src_frames) // sampwidth
        if sampwidth == 2:
            fmt = f"<{total_samples}h"
            samples = list(struct.unpack(fmt, src_frames))
        else:
            # 8-bit unsigned PCM — convert to signed for interpolation
            samples = [b - 128 for b in src_frames]

        # resample per channel
        ratio = src_rate / target_rate
        out_len = int(total_samples / ratio)
        out_samples = [0] * out_len
        for i in range(out_len):
            src_pos = i * ratio
            idx = int(src_pos)
            frac = src_pos - idx
            left = samples[min(idx, total_samples - 1)]
            right = samples[min(idx + 1, total_samples - 1)]
            out_samples[i] = int(left + (right - left) * frac)

        # re-pack
        if sampwidth == 2:
            # clamp to 16-bit signed range
            out_samples = [max(-32768, min(32767, s)) for s in out_samples]
            out_frames = struct.pack(f"<{out_len}h", *out_samples)
        else:
            # back to unsigned 8-bit
            out_bytes = bytes(max(0, min(255, s + 128)) for s in out_samples)
            out_frames = out_bytes

        with wave.open(dst_path, 'wb') as wf_dst:
            wf_dst.setnchannels(nchannels)
            wf_dst.setsampwidth(sampwidth)
            wf_dst.setframerate(target_rate)
            wf_dst.writeframes(out_frames)

        logger.info("WAV 重采样完成: {} {}Hz→{}Hz → {}",
                    os.path.basename(src_path), src_rate, target_rate, os.path.basename(dst_path))
        return True

    except Exception as exc:
        logger.warning("WAV 重采样异常 {}: {}", os.path.basename(src_path), exc)
        return False


def preprocess_audio_if_needed(path: str) -> tuple[str, bool]:
    """Check if audio needs preprocessing for Qwen ASR compatibility.

    Returns (audio_path, was_processed).
    - If no processing needed: returns (path, False).
    - If resampled: returns (tmp_path, True); caller MUST delete tmp_path after use.

    For non-WAV files, always returns (path, False) — the ASR service
    decides whether the format is supported.
    """
    if not path.lower().endswith('.wav'):
        return path, False

    info = get_wav_info(path)
    if info is None:
        # not a valid WAV — let ASR deal with it
        return path, False

    if info["framerate"] in _QWEN_SUPPORTED_RATES:
        return path, False

    # non-standard rate — resample
    logger.info("WAV 采样率 {}Hz 不在 Qwen 支持列表中，将重采样到 {}Hz: {}",
               info["framerate"], _DEFAULT_TARGET_RATE, os.path.basename(path))

    fd, tmp_path = tempfile.mkstemp(suffix='.wav')
    os.close(fd)

    ok = resample_wav_linear(path, tmp_path, _DEFAULT_TARGET_RATE)
    if not ok:
        os.unlink(tmp_path)
        raise RuntimeError(
            f"WAV 重采样失败: {os.path.basename(path)} "
            f"({info['framerate']}Hz, {info['sampwidth']*8}bit)")

    return tmp_path, True
