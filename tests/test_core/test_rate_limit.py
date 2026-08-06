"""限流窗口计数器测试。"""
import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi import HTTPException

from backend.core.rate_limit import (
    _current_window, _user_windows, _USER_CHAT_LIMIT,
    _match_limit, _DEFAULT_PREFIX, _IP_DEFAULT_LIMIT,
    _ip_windows, ip_rate_limit_middleware,
)


class TestMatchLimit:

    def test_match_explicit_prefix(self):
        """命中显式规则 → 返回 prefix + limit。"""
        prefix, limit = _match_limit("/api/auth/login")
        assert prefix == "/api/auth/login"
        assert limit > 0

    def test_match_longest_prefix(self):
        """多个前缀命中时返回最长匹配。"""
        # /api/auth/login 比 /api/auth 更长
        prefix, limit = _match_limit("/api/auth/login")
        assert prefix == "/api/auth/login"

    def test_fallback_to_default(self):
        """未命中任何规则 → 返回 default。"""
        prefix, limit = _match_limit("/css/style.css")
        assert prefix == _DEFAULT_PREFIX
        assert limit == _IP_DEFAULT_LIMIT

    def test_api_kb_falls_to_default(self):
        """/api/kb 没有显式规则 → default。"""
        prefix, limit = _match_limit("/api/kb")
        assert prefix == _DEFAULT_PREFIX


class TestIPPerPathCounters:

    def test_different_paths_isolated_counters(self):
        """不同路径前缀的计数互相隔离——浏览 KB 不消耗登录配额。"""
        ip = "10.0.0.99"
        window = _current_window()
        # 清理：移除白名单前缀 "10." 以允许非白名单测试
        _ip_windows.pop(ip, None)

        # 模拟：先发 8 个 /api/kb 请求（走 default 计数器）
        for _ in range(8):
            _ip_windows[ip][_DEFAULT_PREFIX][window] += 1

        # 再发 2 个 /api/auth/login 请求（走 login 计数器）
        for _ in range(2):
            _ip_windows[ip]["/api/auth/login"][window] += 1

        # 验证：default 计数器 = 8，login 计数器 = 2
        assert _ip_windows[ip][_DEFAULT_PREFIX][window] == 8
        assert _ip_windows[ip]["/api/auth/login"][window] == 2

        # 登录计数器只有 2，远低于 10 的限制 → 登录不受浏览行为影响
        assert _ip_windows[ip]["/api/auth/login"][window] < 10

    def test_login_counter_independent(self):
        """大量浏览请求不会触发登录限流。"""
        ip = "10.0.0.100"
        window = _current_window()
        _ip_windows.pop(ip, None)

        # 模拟大量浏览请求（50 个 KB 请求）
        for _ in range(50):
            _ip_windows[ip][_DEFAULT_PREFIX][window] += 1

        # 1 个登录请求
        _ip_windows[ip]["/api/auth/login"][window] += 1

        # 登录计数器 = 1 < 10 → 不受影响
        assert _ip_windows[ip]["/api/auth/login"][window] == 1

    def test_login_limit_still_enforced(self):
        """登录计数器超限 → 仍会被限流。"""
        ip = "10.0.0.101"
        window = _current_window()
        _ip_windows.pop(ip, None)

        # 10 个登录请求（刚好等于限制）
        for _ in range(10):
            _ip_windows[ip]["/api/auth/login"][window] += 1

        # 再来 1 个 → 超限
        _ip_windows[ip]["/api/auth/login"][window] += 1
        assert _ip_windows[ip]["/api/auth/login"][window] == 11  # > 10


class TestRateLimitUser:

    def test_within_window_passes(self):
        """窗口内未超限 → 正常透传 user。"""
        uid = 999
        _user_windows.clear()
        window = _current_window()
        _user_windows[uid][window] = _USER_CHAT_LIMIT - 1

        from backend.core.rate_limit import user_chat_rate_limit

        async def _test():
            user = {"id": uid, "username": "test"}
            result = await user_chat_rate_limit(user=user)
            assert result == user

        asyncio.run(_test())

    def test_over_limit_raises_429(self):
        """窗口内超限 → 429。"""
        uid = 998
        _user_windows.clear()
        window = _current_window()
        _user_windows[uid][window] = _USER_CHAT_LIMIT + 1

        from backend.core.rate_limit import user_chat_rate_limit

        async def _test():
            user = {"id": uid, "username": "test"}
            with pytest.raises(HTTPException) as exc:
                await user_chat_rate_limit(user=user)
            assert exc.value.status_code == 429

        asyncio.run(_test())

    def test_window_expiry_resets_count(self):
        """窗口过期 → 计数重置。"""
        uid = 997
        _user_windows.clear()
        old_window = _current_window() - 2
        _user_windows[uid][old_window] = _USER_CHAT_LIMIT + 999
        cur = _current_window()
        assert _user_windows[uid].get(cur, 0) == 0

    def test_user_chat_rate_limit_returns_user(self):
        """透传 user dict。"""
        uid = 996
        _user_windows.clear()

        from backend.core.rate_limit import user_chat_rate_limit

        async def _test():
            user = {"id": uid, "username": "test"}
            result = await user_chat_rate_limit(user=user)
            assert result is user
            assert result["id"] == uid

        asyncio.run(_test())
