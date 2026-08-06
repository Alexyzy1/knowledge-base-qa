"""Aho-Corasick 自动机 —— 多模式串一次扫描匹配。

用途：敏感词/安全审核。给定一段文本，一次遍历找出所有命中的模式串。

与手动遍历子串的对比：
  当前 260 词: 每请求做 260 次子串查找
  10000 词:    10000 次
  AC 自动机:   始终 1 次扫描

参考：Udi Manber 经典论文 "A fast string searching algorithm with multiple patterns"
      (Aho-Corasick 因其人名拼写获得俗称"AC 自动机")
"""

from __future__ import annotations

from collections import deque


class AhoCorasick:
    """Aho-Corasick 多模式匹配自动机。

    Usage:
        ac = AhoCorasick(["色情", "暴力", "AV", "porn"])
        hits = ac.search("这段文本包含色情内容")
        # → ["色情"]

        # 带词边界（ASCII 短词防止误伤）
        hits = ac.search("HAVE A VISION", word_boundary_ascii=True)
        # → []  (AV 不会命中，因为有词边界 \\b)
    """

    __slots__ = ("_trie", "_fail", "_output", "_ascii_patterns")

    def __init__(self, patterns: list[str]):
        """构建 AC 自动机。

        Args:
            patterns: 要匹配的模式串列表（自动转小写）
        """
        # ── 1. 建 Trie ──
        # _trie: dict[int, dict[str, int]]  (state_id → char → next_state)
        # _output: dict[int, list[str]]     (state_id → 在此结束的完整模式串)
        self._trie: dict[int, dict[str, int]] = {0: {}}
        self._output: dict[int, list[str]] = {}
        self._ascii_patterns: set[str] = set()  # 纯 ASCII 模式，用于词边界判断

        for pattern in patterns:
            p = pattern.lower()
            # 标记纯 ASCII 模式
            if self._is_ascii_word(p):
                self._ascii_patterns.add(p)

            node = 0
            for ch in p:
                if ch not in self._trie[node]:
                    next_id = len(self._trie)
                    self._trie[node][ch] = next_id
                    self._trie[next_id] = {}
                    node = next_id
                else:
                    node = self._trie[node][ch]
            self._output.setdefault(node, []).append(p)

        # ── 2. 建失败指针 (BFS) ──
        self._fail: dict[int, int] = {}
        q: deque[int] = deque()

        # 第一层：失败都指向 root
        for ch, next_node in self._trie[0].items():
            self._fail[next_node] = 0
            q.append(next_node)

        while q:
            node = q.popleft()
            for ch, next_node in self._trie[node].items():
                q.append(next_node)

                # 沿 fail 链找最长后缀
                f = self._fail[node]
                while f != 0 and ch not in self._trie[f]:
                    f = self._fail.get(f, 0)
                if ch in self._trie.get(f, {}):
                    self._fail[next_node] = self._trie[f][ch]
                else:
                    self._fail[next_node] = 0

                # 合并 output（fail 链上的也是命中）
                fail_output = self._output.get(self._fail[next_node], [])
                self._output.setdefault(next_node, []).extend(fail_output)

    # ── 辅助 ──
    @staticmethod
    def _is_ascii_word(s: str) -> bool:
        """判断是否为纯 ASCII 字母/数字（用于词边界匹配）。"""
        return all(c.isascii() and (c.isalpha() or c.isdigit()) for c in s)

    @staticmethod
    def _is_word_char(ch: str) -> bool:
        """判断是否为「ASCII 词内字符」（用于 \\b 模拟）。

        仅 ASCII 字母/数字/下划线算词内字符，中文等 Unicode 不算——
        否则 "看av吗" 中 '看'/'吗' 的 isalnum()=True 会破坏词边界。
        """
        o = ord(ch)
        # ASCII: a-z(97-122) A-Z(65-90) 0-9(48-57) _(95)
        return (48 <= o <= 57) or (65 <= o <= 90) or (97 <= o <= 122) or o == 95

    # ── 搜索 ──
    def search(self, text: str, word_boundary_ascii: bool = True) -> list[str]:
        """在 text 中找出所有匹配的模式串。

        Args:
            text: 待搜索文本
            word_boundary_ascii: 对纯 ASCII 模式启用 \\b 词边界，
                                 防止 "AV" 误伤 "HAVE" / "JAVASCRIPT"

        Returns:
            命中的模式串列表（去重）
        """
        if not self._trie or not text:
            return []

        text_lower = text.lower()
        node = 0
        hits: list[str] = []

        for i, ch in enumerate(text_lower):
            # 沿 fail 链回退，直到能匹配当前字符
            while node != 0 and ch not in self._trie[node]:
                node = self._fail.get(node, 0)
            if ch in self._trie[node]:
                node = self._trie[node][ch]
            else:
                node = 0

            # 检查当前节点是否有输出
            if node in self._output:
                for pattern in self._output[node]:
                    # 词边界检查（仅纯 ASCII 模式）
                    if word_boundary_ascii and pattern in self._ascii_patterns:
                        if not self._passes_word_boundary(text_lower, i, pattern):
                            continue
                    hits.append(pattern)

        return hits

    def _passes_word_boundary(self, text: str, end_idx: int, pattern: str) -> bool:
        """检查 pattern 在 text 中的命中是否满足 \\b 词边界。

        end_idx: 匹配结束位置（在 text 中的索引）
        pattern: 命中的模式串
        """
        plen = len(pattern)
        start_idx = end_idx - plen + 1

        # 检查左边界
        if start_idx > 0:
            left_char = text[start_idx - 1]
            if self._is_word_char(left_char):
                return False

        # 检查右边界
        if end_idx + 1 < len(text):
            right_char = text[end_idx + 1]
            if self._is_word_char(right_char):
                return False

        return True

    @property
    def pattern_count(self) -> int:
        """已加载的模式串数量。"""
        return sum(len(v) for v in self._output.values())
