"""
文本切分方法对比脚本

对比项目现有的 5 种分段策略在相同输入上的表现差异。
运行方式: python scripts/compare_splitters.py

输出维度:
  - 块数、块大小分布（均值/中位数/最小/最大/标准差）
  - 边界质量（是否在自然断句处切开）
  - 重叠分析（相邻 chunk 公共子串长度）
  - 耗时
  - 语义一致性（semantic 方法独有：断点处的相似度分布）
"""

import sys
import os
import time
import math
import textwrap
from typing import Callable, Any
from dataclasses import dataclass, field

# Windows GBK 环境下强制 UTF-8 输出，避免 emoji 等字符报错
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 确保 backend 在 path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.ingest.text_splitter import (
    split_text,
    split_text_recursive,
    split_text_markdown,
    split_text_sentence_window,
    _SENTENCE,
    _cosine_similarity,
)


# ═══════════════════════════════════════════════════════════════
# 测试文本
# ═══════════════════════════════════════════════════════════════

SAMPLE_PROSE = (
    "深度学习是机器学习的一个分支，它使用多层神经网络来学习数据的层次化表示。"
    "近年来，随着计算能力的提升和大规模数据集的出现，深度学习取得了突破性进展。"
    "卷积神经网络（CNN）在图像识别任务中表现优异，而循环神经网络（RNN）则擅长处理序列数据。"
    "Transformer 架构的出现彻底改变了自然语言处理领域。它基于自注意力机制，能够并行处理输入序列，"
    "大大提高了训练效率。BERT、GPT 等预训练模型在各种 NLP 任务上刷新了记录。"
    "大语言模型（LLM）通过在海量文本上预训练，展现出了强大的语言理解和生成能力。"
    "然而，LLM 也面临着幻觉、偏见、推理能力不足等挑战。研究者们正在探索各种方法来改善这些问题，"
    "包括检索增强生成（RAG）、思维链推理（Chain-of-Thought）以及人类反馈强化学习（RLHF）等。"
    "RAG 技术通过将外部知识库与 LLM 结合，有效减少了幻觉问题。它首先检索相关文档，"
    "然后将检索结果作为上下文输入给 LLM，使模型能够基于可靠的信息源生成回答。"
    "这种方法的优势在于知识可以动态更新，无需重新训练模型。在实际应用中，"
    "RAG 系统通常包含文档解析、文本分段、向量化、检索和生成等模块。"
    "其中文本分段策略对最终检索效果有重要影响——太粗的粒度会降低检索精度，太细则可能丢失上下文。"
)

SAMPLE_MARKDOWN = """# 知识库问答系统技术文档

## 系统架构

本系统采用 RAG（检索增强生成）架构，核心组件包括：

- **后端服务**：基于 FastAPI 构建，提供 RESTful API
- **向量数据库**：Milvus 存储文档嵌入向量
- **关系数据库**：MySQL 存储文档元信息和用户数据
- **大语言模型**：DeepSeek-V3 提供问答能力

### 数据流

1. 用户上传文档到系统
2. 文档解析器提取纯文本内容
3. 文本分段器将内容切分为适当大小的块
4. 嵌入模型将每个块转换为向量
5. 向量存入 Milvus，元信息存入 MySQL

## API 设计

### 知识库管理

提供知识库的创建、查询、更新和删除功能。每个知识库可以包含多个文档。

### 文档上传

支持 TXT、MD、PDF、DOCX 等格式。上传后自动进入处理流水线。

#### 处理状态

- `pending`：等待处理
- `processing`：正在处理中
- `done`：处理完成
- `failed`：处理失败

## 部署说明

系统使用 Docker Compose 进行容器化部署。主要容器包括：

- `kb-dev`：FastAPI 应用
- `milvus`：向量数据库
- `mysql`：关系数据库

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `DB_HOST` | MySQL 主机 | `localhost` |
| `MILVUS_HOST` | Milvus 主机 | `localhost` |
| `LLM_API_URL` | LLM API 地址 | - |

## 性能优化

### 检索优化

使用混合检索策略，结合稠密向量检索和 BM25 稀疏检索，通过 RRF 算法融合结果。

### 缓存策略

对高频查询结果进行缓存，减少重复的 LLM 调用和向量检索。使用 LRU 淘汰策略。
"""

SAMPLE_CODE_LIKE = """\
import torch
import torch.nn as nn

class TransformerBlock(nn.Module):
    def __init__(self, d_model, n_heads, d_ff, dropout=0.1):
        super().__init__()
        self.attention = nn.MultiheadAttention(d_model, n_heads, dropout=dropout)
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.ff = nn.Sequential(
            nn.Linear(d_model, d_ff),
            nn.ReLU(),
            nn.Linear(d_ff, d_model),
        )
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        attn_out, _ = self.attention(x, x, x)
        x = self.norm1(x + self.dropout(attn_out))
        ff_out = self.ff(x)
        x = self.norm2(x + self.dropout(ff_out))
        return x

class GPT(nn.Module):
    def __init__(self, vocab_size, d_model, n_heads, n_layers, block_size, d_ff):
        super().__init__()
        self.token_embedding = nn.Embedding(vocab_size, d_model)
        self.position_embedding = nn.Embedding(block_size, d_model)
        self.blocks = nn.ModuleList([
            TransformerBlock(d_model, n_heads, d_ff) for _ in range(n_layers)
        ])
        self.ln_final = nn.LayerNorm(d_model)
        self.lm_head = nn.Linear(d_model, vocab_size)

    def forward(self, idx):
        B, T = idx.shape
        tok_emb = self.token_embedding(idx)
        pos_emb = self.position_embedding(torch.arange(T, device=idx.device))
        x = tok_emb + pos_emb
        for block in self.blocks:
            x = block(x)
        x = self.ln_final(x)
        logits = self.lm_head(x)
        return logits
"""

SAMPLE_MIXED = (
    "# 大语言模型的演进与 RAG 实践\n\n"
    "## 1. 从 Transformer 到 GPT\n\n"
    "2017 年，Google 提出了 Transformer 架构，用自注意力机制取代了传统的 RNN 和 CNN。"
    "这一创新使得模型能够并行处理序列数据，大幅提升了训练效率。"
    "随后，OpenAI 基于 Transformer 的 Decoder 部分开发了 GPT 系列模型。\n\n"
    "```python\n"
    "def scaled_dot_product_attention(Q, K, V, mask=None):\n"
    "    d_k = Q.shape[-1]\n"
    "    scores = torch.matmul(Q, K.transpose(-2, -1)) / math.sqrt(d_k)\n"
    "    if mask is not None:\n"
    "        scores = scores.masked_fill(mask == 0, -1e9)\n"
    "    attn = F.softmax(scores, dim=-1)\n"
    "    return torch.matmul(attn, V)\n"
    "```\n\n"
    "## 2. RAG 的技术细节\n\n"
    "检索增强生成（RAG）将信息检索与文本生成相结合。"
    "在回答用户问题时，系统先检索相关知识，再让 LLM 基于检索结果生成回答。"
    "这种方法有效缓解了 LLM 的知识截止和幻觉问题。\n\n"
    "### 2.1 文本分段策略\n\n"
    "文本分段是 RAG 系统的关键环节。常见的分段策略包括固定大小切分、递归切分、"
    "语义切分和句子窗口切分。不同的策略各有优劣，需要根据文档类型和业务场景选择。\n\n"
    "### 2.2 检索优化\n\n"
    "混合检索结合了稠密检索和稀疏检索的优势。RRF 算法能够有效地融合两种检索结果，"
    "提升最终排序的质量。此外，重排序模型可以进一步优化检索结果的相关性。"
)


# ═══════════════════════════════════════════════════════════════
# 分析工具
# ═══════════════════════════════════════════════════════════════

@dataclass
class ChunkStats:
    method: str
    sample: str
    count: int
    total_chars: int
    mean: float
    median: float
    min: int
    max: int
    std: float
    elapsed_ms: float
    boundary_score: float          # 0-100，越高越好
    avg_overlap_chars: float       # 相邻 chunk 平均重叠字符数
    chunks: list = field(repr=False)


def compute_stats(method: str, sample_name: str, chunks: list[str], elapsed_ms: float) -> ChunkStats:
    """计算单个方法 × 单个样本的统计指标。"""
    lengths = [len(c) for c in chunks]
    n = len(lengths)
    if n == 0:
        return ChunkStats(
            method=method, sample=sample_name,
            count=0, total_chars=0, mean=0, median=0, min=0, max=0, std=0,
            elapsed_ms=elapsed_ms, boundary_score=0, avg_overlap_chars=0,
        )

    mean = sum(lengths) / n
    sorted_lens = sorted(lengths)
    median = sorted_lens[n // 2] if n % 2 else (sorted_lens[n // 2 - 1] + sorted_lens[n // 2]) / 2
    variance = sum((l - mean) ** 2 for l in lengths) / n
    std = math.sqrt(variance)

    # 边界质量分：chunk 结尾是自然断句标点的比例
    natural_ends = sum(1 for c in chunks if c.rstrip() and c.rstrip()[-1] in "。！？；\n")
    boundary_score = (natural_ends / n) * 100 if n else 0

    # 相邻 chunk 重叠分析
    overlaps = []
    for i in range(n - 1):
        a, b = chunks[i], chunks[i + 1]
        # 找 b 的前缀在 a 中出现的最长后缀
        max_ov = 0
        for k in range(1, min(len(a), len(b), 200) + 1):
            if a[-k:] == b[:k]:
                max_ov = k
        overlaps.append(max_ov)
    avg_overlap = sum(overlaps) / len(overlaps) if overlaps else 0

    return ChunkStats(
        method=method, sample=sample_name,
        count=n, total_chars=sum(lengths),
        mean=mean, median=median,
        min=min(lengths), max=max(lengths),
        std=std, elapsed_ms=elapsed_ms,
        boundary_score=boundary_score,
        avg_overlap_chars=avg_overlap,
        chunks=chunks,
    )


def longest_common_substring(a: str, b: str) -> str:
    """两个字符串的最长公共子串（简单 DP，仅用于展示）。"""
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return ""
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    max_len, end_pos = 0, 0
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
                if dp[i][j] > max_len:
                    max_len = dp[i][j]
                    end_pos = i
    return a[end_pos - max_len:end_pos]


# ═══════════════════════════════════════════════════════════════
# 对比主逻辑
# ═══════════════════════════════════════════════════════════════

# 方法注册表
METHODS: dict[str, tuple[str, Callable[..., list[str]], dict]] = {
    "fixed":          ("固定大小",   split_text,                {}),
    "recursive":      ("递归切分",   split_text_recursive,      {}),
    "markdown":       ("Markdown",   split_text_markdown,       {}),
    "sentence_window":("句子窗口",   split_text_sentence_window, {"window_size": 1}),
    # semantic 需 embedding，单独处理
}

SAMPLES: dict[str, str] = {
    "中文散文":     SAMPLE_PROSE,
    "Markdown文档": SAMPLE_MARKDOWN,
    "代码文本":     SAMPLE_CODE_LIKE,
    "混合内容":     SAMPLE_MIXED,
}

CHUNK_SIZE = 300
OVERLAP = 50


def run_all() -> list[ChunkStats]:
    """对所有方法 × 所有样本跑一遍，返回统计列表。"""
    results: list[ChunkStats] = []

    for sample_name, text in SAMPLES.items():
        print(f"\n{'='*60}")
        print(f"  测试样本: {sample_name}  ({len(text)} 字符)")
        print(f"  chunk_size={CHUNK_SIZE}, overlap={OVERLAP}")
        print(f"{'='*60}")

        for method_key, (method_label, func, extra_kwargs) in METHODS.items():
            try:
                t0 = time.perf_counter()
                chunks = func(text, chunk_size=CHUNK_SIZE, overlap=OVERLAP, **extra_kwargs)
                elapsed = (time.perf_counter() - t0) * 1000

                stats = compute_stats(method_label, sample_name, chunks, elapsed)
                results.append(stats)

                print(f"  {method_label:12s} → {stats.count:3d} 块, "
                      f"平均 {stats.mean:6.1f} 字, "
                      f"边界分 {stats.boundary_score:5.1f}%, "
                      f"{stats.elapsed_ms:7.2f} ms")
            except Exception as e:
                print(f"  {method_label:12s} → ERROR: {e}")

    return results


def print_summary_table(results: list[ChunkStats]):
    """打印汇总对比表。"""
    print("\n\n")
    print("╔" + "═" * 118 + "╗")
    print("║" + "文本切分方法对比汇总".center(110) + "║")
    print("╠" + "═" * 118 + "╣")
    header = (
        f"║ {'方法':12s} │ {'样本':12s} │ "
        f"{'块数':>5s} │ {'均值':>6s} │ {'中位':>6s} │ {'最小':>5s} │ {'最大':>5s} │ "
        f"{'标准差':>6s} │ {'边界%':>5s} │ {'重叠':>5s} │ {'耗时ms':>7s} ║"
    )
    print(header)
    print("╠" + "═" * 118 + "╣")

    # 按方法分组
    method_order = ["固定大小", "递归切分", "Markdown", "句子窗口"]
    for method in method_order:
        group = [r for r in results if r.method == method]
        for i, s in enumerate(group):
            if i == 0:
                print(
                    f"║ {method:12s} │ {s.sample:12s} │ "
                    f"{s.count:5d} │ {s.mean:6.1f} │ {s.median:6.1f} │ {s.min:5d} │ {s.max:5d} │ "
                    f"{s.std:6.1f} │ {s.boundary_score:5.1f} │ {s.avg_overlap_chars:5.0f} │ {s.elapsed_ms:7.2f} ║"
                )
            else:
                print(
                    f"║ {'':12s} │ {s.sample:12s} │ "
                    f"{s.count:5d} │ {s.mean:6.1f} │ {s.median:6.1f} │ {s.min:5d} │ {s.max:5d} │ "
                    f"{s.std:6.1f} │ {s.boundary_score:5.1f} │ {s.avg_overlap_chars:5.0f} │ {s.elapsed_ms:7.2f} ║"
                )
        if method != method_order[-1]:
            print("╟" + "─" * 118 + "╢")

    print("╚" + "═" * 118 + "╝")


def print_boundary_analysis(results: list[ChunkStats]):
    """分析各方法在边界处的表现。"""
    print("\n\n📐 边界质量分析（chunk 结尾是否为自然断句标点「。！？；\\n」）")
    print("-" * 80)

    for sample_name in SAMPLES:
        print(f"\n  【{sample_name}】")
        group = [r for r in results if r.sample == sample_name]
        group.sort(key=lambda r: r.boundary_score, reverse=True)
        for s in group:
            bar = "█" * int(s.boundary_score / 5) + "░" * (20 - int(s.boundary_score / 5))
            print(f"    {s.method:12s}  {bar}  {s.boundary_score:.0f}%")


def print_chunk_preview(results: list[ChunkStats]):
    """展示各方法产出的前几个 chunk 内容片段。"""
    print("\n\n🔍 Chunk 内容预览（每种方法对「中文散文」的前 3 个 chunk）")
    print("-" * 80)

    prose_results = [r for r in results if r.sample == "中文散文"]
    for s in prose_results:
        print(f"\n  ── {s.method} ──")
        for i, c in enumerate(s.chunks[:3]):
            preview = c[:120].replace("\n", "\\n")
            if len(c) > 120:
                preview += f"...(+{len(c)-120}字)"
            print(f"    [{i+1}] ({len(c)}字) {preview}")


def print_overlap_demo(results: list[ChunkStats]):
    """展示相邻 chunk 的重叠情况。"""
    print("\n\n🔄 重叠分析（相邻 chunk 公共子串示例）")
    print("-" * 80)

    for s in results:
        if s.count < 2:
            continue
        # 找重叠最大的相邻对
        best_ov = ""
        best_pair = (0, 0)
        for i in range(s.count - 1):
            ov = longest_common_substring(s.chunks[i], s.chunks[i + 1])
            if len(ov) > len(best_ov):
                best_ov = ov
                best_pair = (i, i + 1)
        print(f"  {s.method:12s} [{s.sample:12s}] "
              f"平均重叠 {s.avg_overlap_chars:5.0f} 字, "
              f"最大重叠 {len(best_ov)} 字 → 「{best_ov[:50]}」")


def print_method_summary():
    """打印每种方法的算法特点总结。"""
    print("\n\n📋 方法特点总结")
    print("=" * 80)
    summaries = [
        ("固定大小 (fixed)",
         "算法: 先按句末标点(。！？；\\n)原子化，再贪心填充到 chunk_size，超长原子硬切。\n"
         "      重叠通过滑动窗口实现——新 chunk 开始时从旧 chunk 头部弹出原子直到剩余 ≤ overlap。\n"
         "优点: 实现最简单，速度最快，无递归开销，所有文本类型通用。\n"
         "缺点: 不感知文档结构，可能在段落/标题中间断开；重叠策略粗糙，可能截断长句。\n"
         "适用: 纯文本、无结构文档，或作为兜底方案。"),

        ("递归切分 (recursive)",
         "算法: 按 \\n\\n → \\n → 。→ ！→ ？→ ；→ ，→ 空格 → 硬切 的优先级逐级递归。\n"
         "      先用高优先级分隔符切开，子段超长则用下一级分隔符递归。最后合并到 chunk_size+overlap。\n"
         "优点: 语义边界更自然——能识别段落、句子、子句三级结构；与 LangChain 的 RecursiveCharacterTextSplitter 同款。\n"
         "缺点: 递归调用有栈开销（但通常很浅）；对非中文文本的空格切分可能产生过多碎片。\n"
         "适用: 通用中文文档，尤其是有清晰段落/句子边界的文本。"),

        ("Markdown 标题感知 (markdown)",
         "算法: 正则匹配 # ~ ###### 标题 → 按标题位置分段 → 每段内部用 recursive 算法切分。\n"
         "      每个 chunk 前缀带上标题路径（如「## 概述」），帮助检索时匹配结构上下文。\n"
         "优点: 充分利用文档结构信息，chunk 自带层级上下文；无标题时自动退回 recursive。\n"
         "缺点: 仅对 Markdown 格式有效；标题嵌套过深时前缀可能占据过多空间。\n"
         "适用: Markdown 技术文档、笔记、API 文档等结构化内容。"),

        ("语义切分 (semantic)",
         "算法: 句子级原子化 → 逐句 embedding → 计算相邻句余弦相似度 → 相似度 < 阈值(默认0.6)处断开。\n"
         "      断点确定后，在每个语义段内按 chunk_size 合并句子，同样带 overlap 滑动窗口。\n"
         "优点: 真正感知语义边界——在「话题转换」处断开；chunk 内部语义一致性强，检索精度最高。\n"
         "缺点: 需要额外 embedding 调用（N 句 = N 次 embedding），入库速度显著慢于其他方法；\n"
         "      阈值调优依赖经验（太高=断太少，太低=断太多）。\n"
         "适用: 对检索精度要求高的场景；文本话题分散、语义边界不明显的长文档。"),

        ("句子窗口 (sentence_window)",
         "算法: 每条句子独立成块，但内容带上前后各 window_size 句作为上下文窗口。\n"
         "优点: 极致细粒度——每条句子都有独立向量，检索匹配最精确；\n"
         "      LLM 拿到的上下文就是「目标句 + 前后文」，无需额外拼接。\n"
         "缺点: chunk 数量等于句子数，向量库膨胀；长文档可能产生数千个向量；\n"
         "      单句信息量有限，可能影响检索召回。\n"
         "适用: 问答型应用、FAQ 知识库，追求精确匹配的场景。"),
    ]
    for title, body in summaries:
        print(f"\n  ◆ {title}")
        for line in body.split("\n"):
            print(f"    {line}")
        print()


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def main():
    print("╔" + "═" * 60 + "╗")
    print("║" + "  文本切分方法对比分析".center(52) + "║")
    print("║" + f"  chunk_size={CHUNK_SIZE}, overlap={OVERLAP}".center(52) + "║")
    print("╚" + "═" * 60 + "╝")

    results = run_all()

    print_summary_table(results)
    print_boundary_analysis(results)
    print_chunk_preview(results)
    print_overlap_demo(results)
    print_method_summary()

    # 补充说明 semantic
    print("\n⚠️  semantic（语义切分）未参与自动对比——该方法需要 embedding_client（异步），"
          "请在完整应用环境中手动测试。")
    print("   关键参数: threshold=0.6（相邻句余弦相似度低于此值即断开）")
    print("   评估要点: 观察断点处是否确实发生了话题转换；比较 chunk 内部句子间的平均相似度。")


if __name__ == "__main__":
    main()
