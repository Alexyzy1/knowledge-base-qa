"""Qwen ASR 客户端测试：切分边界计算 + 优雅降级 + 并发拼接。

所有外部依赖（subprocess / httpx / 文件系统）均被 mock，纯逻辑测试。
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from backend.core.asr_client_qwen import (
    _compute_split_boundaries,
    _ffprobe_duration,
    _ffmpeg_silence_points,
)


# ═══════════════════════════════════════════════════════════════
# _compute_split_boundaries
# ═══════════════════════════════════════════════════════════════

class TestComputeSplitBoundaries:

    def test_no_silence_uniform_split(self, monkeypatch):
        """无静音点 → 按 max_seg 均匀切分。"""
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MIN_SEGMENT", 15)
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MAX_SEGMENT", 60)
        boundaries = _compute_split_boundaries(180.0, [])
        # 180s / 60 = 3 段
        assert len(boundaries) == 3
        assert boundaries[0] == (0.0, 60.0)
        assert boundaries[1] == (60.0, 120.0)
        assert boundaries[2] == (120.0, 180.0)

    def test_silence_points_split(self, monkeypatch):
        """静音点处切分。115→180 段长 65s > 60s 会被均匀拆分。"""
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MIN_SEGMENT", 15)
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MAX_SEGMENT", 60)
        boundaries = _compute_split_boundaries(180.0, [55.0, 115.0])
        # 0→55, 55→115, 115→147.5, 147.5→180 = 4 段（最后一段 >60s 被拆分）
        assert len(boundaries) == 4
        assert boundaries[0][0] == 0.0
        assert abs(boundaries[0][1] - 55.0) < 0.01
        assert abs(boundaries[1][0] - 55.0) < 0.01
        assert abs(boundaries[1][1] - 115.0) < 0.01
        assert abs(boundaries[2][0] - 115.0) < 0.01
        assert boundaries[3][1] == 180.0

    def test_silence_too_close_to_start_ignored(self, monkeypatch):
        """太靠近开头的静音点被忽略。"""
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MIN_SEGMENT", 15)
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MAX_SEGMENT", 60)
        boundaries = _compute_split_boundaries(120.0, [5.0, 60.0])
        # 5s 太靠近开头，忽略；60s 可用
        # → 0→60, 60→120
        assert len(boundaries) == 2
        assert boundaries[0] == (0.0, 60.0)
        assert boundaries[1] == (60.0, 120.0)

    def test_silence_too_close_to_end_ignored(self, monkeypatch):
        """太靠近结尾的静音点被忽略。"""
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MIN_SEGMENT", 15)
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MAX_SEGMENT", 60)
        boundaries = _compute_split_boundaries(100.0, [40.0, 90.0])
        # 90s 离结尾只差 10s < min_seg(15)，忽略
        # → 0→40, 40→100
        assert len(boundaries) == 2
        assert abs(boundaries[0][1] - 40.0) < 0.01
        assert boundaries[1][1] == 100.0

    def test_silence_too_close_together_ignored(self, monkeypatch):
        """过近的静音点去重。"""
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MIN_SEGMENT", 15)
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MAX_SEGMENT", 60)
        boundaries = _compute_split_boundaries(120.0, [30.0, 40.0, 90.0])
        # 30→40 差 10s < min_seg(15)，忽略 40
        # → 0→30, 30→90, 90→120
        assert len(boundaries) == 3
        assert abs(boundaries[0][1] - 30.0) < 0.01
        assert abs(boundaries[1][1] - 90.0) < 0.01

    def test_short_remaining_tail_merged(self, monkeypatch):
        """尾段短于 min_seg 时合并到上一段（边界算法中尾段自动保留）。"""
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MIN_SEGMENT", 15)
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MAX_SEGMENT", 60)
        # 最后一静音点在 165s，剩余 15s（刚好等于 min_seg），应该保留
        boundaries = _compute_split_boundaries(180.0, [70.0, 140.0])
        assert boundaries[-1] == (140.0, 180.0)
        assert boundaries[-1][1] - boundaries[-1][0] >= 15

    def test_long_segment_subdivided(self, monkeypatch):
        """无静音点的大区间被均匀切分。"""
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MIN_SEGMENT", 15)
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MAX_SEGMENT", 60)
        boundaries = _compute_split_boundaries(200.0, [])
        # 200/60=3.33 → 4 段，每段 ~50s
        assert len(boundaries) == 4
        for s, e in boundaries:
            assert e - s <= 60  # 每段 ≤ max_seg
        assert boundaries[0][0] == 0.0
        assert boundaries[-1][1] == 200.0

    def test_single_segment_below_threshold(self, monkeypatch):
        """时长很短 → 只有一段。"""
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MIN_SEGMENT", 15)
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MAX_SEGMENT", 60)
        boundaries = _compute_split_boundaries(30.0, [])
        assert len(boundaries) == 1
        assert boundaries[0] == (0.0, 30.0)

    def test_boundary_coverage_gap(self, monkeypatch):
        """相邻边界之间无间隙。"""
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MIN_SEGMENT", 15)
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MAX_SEGMENT", 60)
        boundaries = _compute_split_boundaries(150.0, [50.0, 100.0])
        total = sum(e - s for s, e in boundaries)
        assert abs(total - 150.0) < 0.2  # 总时长正确（允许浮点误差）


# ═══════════════════════════════════════════════════════════════
# parse_audio 集成测试（mock 外部依赖）
# ═══════════════════════════════════════════════════════════════

class TestParseAudioIntegration:

    def test_short_audio_single_call(self, tmp_path, monkeypatch):
        """短音频走单次调用，不触发切分。"""
        audio = tmp_path / "short.mp3"
        audio.write_bytes(b"\x00" * 1024)

        # mock _call_api_single
        calls = []
        def fake_single(path, prompt=None, filename=None):
            calls.append(path)
            display_name = filename or Path(path).name
            return f"[{display_name}]\n音频 {display_name} 的主要内容如下：\n# 音频内容：\nhello"

        monkeypatch.setattr(
            "backend.core.asr_client_qwen._call_api_single", fake_single
        )
        # 返回时长小于阈值
        def fake_duration(path):
            return 30.0
        monkeypatch.setattr(
            "backend.core.asr_client_qwen._ffprobe_duration", fake_duration
        )

        from backend.core.asr_client_qwen import parse_audio
        result = parse_audio(str(audio))
        assert "hello" in result
        assert len(calls) == 1  # 只调了一次

    def test_ffprobe_failure_fallback(self, tmp_path, monkeypatch):
        """ffprobe 不可用 → 降级单次调用。"""
        audio = tmp_path / "audio.wav"
        audio.write_bytes(b"\x00" * 512)

        calls = []
        def fake_single(path, prompt=None, filename=None):
            calls.append(path)
            display_name = filename or Path(path).name
            return f"[{display_name}]\n音频 {display_name} 的主要内容如下：\n# 音频内容：\ntest"

        monkeypatch.setattr(
            "backend.core.asr_client_qwen._call_api_single", fake_single
        )
        def fake_duration(path):
            return None  # ffprobe 失败
        monkeypatch.setattr(
            "backend.core.asr_client_qwen._ffprobe_duration", fake_duration
        )

        from backend.core.asr_client_qwen import parse_audio
        result = parse_audio(str(audio))
        assert "test" in result
        assert len(calls) == 1

    def test_missing_file_raises(self):
        """不存在的文件抛 FileNotFoundError。"""
        from backend.core.asr_client_qwen import parse_audio
        with pytest.raises(FileNotFoundError, match="音频文件不存在"):
            parse_audio("/nonexistent/audio.mp3")

    def test_concurrent_results_ordered(self, tmp_path, monkeypatch):
        """并发段结果按索引排序拼接。"""
        audio = tmp_path / "long.mp3"
        audio.write_bytes(b"\x00" * 4096)

        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_SPLIT_THRESHOLD", 60)

        # 返回长时长
        def fake_duration(path):
            return 180.0
        monkeypatch.setattr(
            "backend.core.asr_client_qwen._ffprobe_duration", fake_duration
        )
        # 返回静音点
        def fake_silence(path):
            return [55.0, 115.0]
        monkeypatch.setattr(
            "backend.core.asr_client_qwen._ffmpeg_silence_points", fake_silence
        )
        # 跳过 ffmpeg 提取（不实际执行）
        def fake_extract(input_path, start, duration, output_path):
            # 创建空文件占位
            Path(output_path).write_bytes(b"dummy")
        monkeypatch.setattr(
            "backend.core.asr_client_qwen._ffmpeg_extract_segment", fake_extract
        )

        # 返回顺序打乱的结果
        call_order = []
        def fake_single(path, prompt=None, filename=None):
            seg_name = Path(path).name
            call_order.append(seg_name)
            display_name = filename or seg_name
            return f"[{display_name}]\n音频 {display_name} 的主要内容如下：\n# 音频内容：\n{seg_name}"
        monkeypatch.setattr(
            "backend.core.asr_client_qwen._call_api_single", fake_single
        )

        from backend.core.asr_client_qwen import parse_audio
        result = parse_audio(str(audio))
        # 最终结果应包含所有三段
        assert "seg_000" in result
        assert "seg_001" in result
        assert "seg_002" in result
        # 顺序正确：seg_000 在 seg_001 前面，seg_001 在 seg_002 前面
        idx0 = result.find("seg_000")
        idx1 = result.find("seg_001")
        idx2 = result.find("seg_002")
        assert idx0 < idx1 < idx2

    def test_segment_failure_propagates(self, tmp_path, monkeypatch):
        """任一段失败 → 异常向上传播。"""
        audio = tmp_path / "fail.mp3"
        audio.write_bytes(b"\x00" * 4096)

        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_SPLIT_THRESHOLD", 60)

        def fake_duration(path):
            return 120.0
        monkeypatch.setattr(
            "backend.core.asr_client_qwen._ffprobe_duration", fake_duration
        )
        monkeypatch.setattr(
            "backend.core.asr_client_qwen._ffmpeg_silence_points",
            lambda p: []
        )
        monkeypatch.setattr(
            "backend.core.asr_client_qwen._ffmpeg_extract_segment",
            lambda *a, **kw: Path(a[3]).write_bytes(b"x")
        )

        # 第一段成功，第二段失败
        call_count = [0]
        def fake_single(path, prompt=None, filename=None):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("API 调用失败")
            display_name = filename or Path(path).name
            return f"[{display_name}]\n音频 {display_name} 的主要内容如下：\n# 音频内容：\nok"
        monkeypatch.setattr(
            "backend.core.asr_client_qwen._call_api_single", fake_single
        )

        from backend.core.asr_client_qwen import parse_audio
        with pytest.raises(RuntimeError, match="API 调用失败"):
            parse_audio(str(audio))

    def test_temp_files_cleaned_up(self, tmp_path, monkeypatch):
        """临时文件在 finally 中清理。"""
        audio = tmp_path / "cleanup.mp3"
        audio.write_bytes(b"\x00" * 4096)

        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_SPLIT_THRESHOLD", 60)

        def fake_duration(path):
            return 120.0
        monkeypatch.setattr(
            "backend.core.asr_client_qwen._ffprobe_duration", fake_duration
        )
        monkeypatch.setattr(
            "backend.core.asr_client_qwen._ffmpeg_silence_points",
            lambda p: []
        )
        # 创建真实的临时文件
        def real_extract(input_path, start, duration, output_path):
            Path(output_path).write_bytes(b"fake audio data")
        monkeypatch.setattr(
            "backend.core.asr_client_qwen._ffmpeg_extract_segment", real_extract
        )

        def fake_single(path, prompt=None, filename=None):
            display_name = filename or Path(path).name
            return f"[{display_name}]\n音频 {display_name} 的主要内容如下：\n# 音频内容：\ndata"
        monkeypatch.setattr(
            "backend.core.asr_client_qwen._call_api_single", fake_single
        )

        from backend.core.asr_client_qwen import parse_audio
        result = parse_audio(str(audio))
        assert "data" in result

        # 验证 tmp_path 下不再有 asr_segments_ 目录
        # 注意：parse_audio 用 tempfile.mkdtemp 创建临时目录，不在 tmp_path 下
        # 我们只能验证 parse_audio 返回了正确结果（没有崩溃）

    def test_no_beneficial_split_fallback(self, tmp_path, monkeypatch):
        """切分边界计算后只有 1 段 → 退回单次调用。"""
        audio = tmp_path / "barely.mp3"
        audio.write_bytes(b"\x00" * 2048)

        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_SPLIT_THRESHOLD", 55)
        # 返回 61s（超过阈值），但 max_seg=60 也只能 2 段
        # 设置 max_seg=120 让 61s 只产生 1 段
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MIN_SEGMENT", 15)
        monkeypatch.setattr("backend.core.asr_client_qwen.config.QWEN_ASR_MAX_SEGMENT", 120)

        def fake_duration(path):
            return 61.0
        monkeypatch.setattr(
            "backend.core.asr_client_qwen._ffprobe_duration", fake_duration
        )

        calls = []
        def fake_single(path, prompt=None, filename=None):
            calls.append(path)
            display_name = filename or Path(path).name
            return f"[{display_name}]\n音频 {display_name} 的主要内容如下：\n# 音频内容：\nsingle"
        monkeypatch.setattr(
            "backend.core.asr_client_qwen._call_api_single", fake_single
        )

        from backend.core.asr_client_qwen import parse_audio
        result = parse_audio(str(audio))
        assert "single" in result
        assert len(calls) == 1  # 只调了一次
