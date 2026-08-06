"""轻量内存限流：无需外部依赖，脱机环境可用。

两个层次：
  1) IP 限流（中间件级）：按客户端 IP + 路径前缀分别做固定窗口计数，
     不同路径的请求互不干扰（登录不会被浏览行为误伤）。
  2) 用户限流（依赖级）：对 /api/chat 按 user_id 做独立窗口，防 Token 滥用。

配置通过 os.getenv 读取，默认值兼顾实用与宽容。
"""
from __future__ import annotations

import os
import time
import threading
from collections import defaultdict

from fastapi import Request, HTTPException, Depends
from loguru import logger

from backend.core.deps import get_current_user, get_client_ip


# ── 可配置参数 ──
_WINDOW_SEC = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # 窗口秒数

# IP 限流（按路径前缀分别计数，单位：次/窗口）
_IP_LIMITS: dict[str, int] = {
    "/api/chat":            int(os.getenv("RL_IP_CHAT",       "60")),
    "/api/auth/login":      int(os.getenv("RL_IP_LOGIN",      "10")),
    "/api/auth/register":   int(os.getenv("RL_IP_REGISTER",    "5")),
}
_IP_DEFAULT_LIMIT = int(os.getenv("RL_IP_DEFAULT", "120"))  # 其他接口

# 用户限流（per-user，仅 chat）
_USER_CHAT_LIMIT = int(os.getenv("RL_USER_CHAT", "30"))


# ── IP 白名单（对此列表中的 IP 不做任何限流）──
# 内置：localhost、内网常见网段、Docker 网桥
_IP_WHITELIST: set[str] = {
    "127.0.0.1", "::1", "localhost",
    "172.17.",              # Docker 网桥前缀（172.17.0.0/16）
    "172.18.", "172.19.",   # Docker 额外网桥段
    "192.168.",             # 内网 C 类前缀
    "10.",                  # 内网 A 类前缀
}
# 可通过环境变量追加：RL_WHITELIST_IPS="10.0.0.5,192.168.1.100"
_extra = os.getenv("RL_WHITELIST_IPS", "")
if _extra:
    for ip in _extra.split(","):
        ip = ip.strip()
        if ip:
            _IP_WHITELIST.add(ip)
            logger.info("限流白名单添加 IP: {}", ip)


def _is_whitelisted(ip: str) -> bool:
    """检查 IP 是否在白名单中（支持前缀匹配）。"""
    for w in _IP_WHITELIST:
        if ip == w or (len(w) < 14 and ip.startswith(w)):
            return True
    return False


# ── 计数器 ──
# IP 计数器：_ip_windows[ip][prefix][window] = count（按路径前缀分别计数）
_ip_windows: dict[str, dict[str, dict[int, int]]] = defaultdict(
    lambda: defaultdict(lambda: defaultdict(int)))
# 用户计数器：_user_windows[user_id][window] = count
_user_windows: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
_lock = threading.Lock()

# 前缀匹配时未命中任何显式规则的 fallback key
_DEFAULT_PREFIX = "__default__"


def _match_limit(path: str) -> tuple[str, int]:
    """按最长前缀匹配限流规则，返回 (prefix_key, limit)。

    未命中任何显式规则时返回 (_DEFAULT_PREFIX, _IP_DEFAULT_LIMIT)。
    """
    for prefix, cap in sorted(_IP_LIMITS.items(), key=lambda x: -len(x[0])):
        if path.startswith(prefix):
            return prefix, cap
    return _DEFAULT_PREFIX, _IP_DEFAULT_LIMIT


def _current_window() -> int:
    """当前窗口编号 = 当前秒数 // 窗口秒数。"""
    return int(time.time()) // _WINDOW_SEC


def _prune_ip(window: int, ip: str, prefix: str) -> None:
    """清理过期窗口（留当前+上一窗口，删其余）。"""
    for w in list(_ip_windows[ip][prefix].keys()):
        if w < window - 1:
            del _ip_windows[ip][prefix][w]


def _prune_user(window: int, uid: int) -> None:
    for w in list(_user_windows[uid].keys()):
        if w < window - 1:
            del _user_windows[uid][w]


async def ip_rate_limit_middleware(request: Request, call_next):
    """FastAPI 中间件：按 IP + 路径前缀分别做固定窗口限流。

    每个路径前缀维护独立的计数器——浏览知识库不会消耗登录配额，
    反之亦然。超出返回 HTTP 429 + Retry-After 头。
    """
    path = request.url.path
    ip = get_client_ip(request) or "127.0.0.1"

    if _is_whitelisted(ip):
        return await call_next(request)

    # 最长前缀匹配 → 拿到独立的 prefix key 和限额
    prefix, limit = _match_limit(path)

    window = _current_window()
    with _lock:
        _prune_ip(window, ip, prefix)
        _ip_windows[ip][prefix][window] += 1
        count = _ip_windows[ip][prefix][window]

    if count > limit:
        logger.warning("IP 限流触发 ip={} path={} prefix={} count={} limit={}",
                       ip, path, prefix, count, limit)
        raise HTTPException(
            status_code=429,
            detail=f"请求太频繁，请 {_WINDOW_SEC} 秒后再试",
            headers={"Retry-After": str(_WINDOW_SEC)},
        )

    return await call_next(request)


async def user_chat_rate_limit(user: dict = Depends(get_current_user)):
    """依赖注入：对 /api/chat 做 per-user 限流。
    挂在 chat 路由上，在 IP 限流之后校验。返回 user dict（透传）。"""
    uid = user["id"]
    limit = _USER_CHAT_LIMIT
    window = _current_window()
    with _lock:
        _prune_user(window, uid)
        _user_windows[uid][window] += 1
        count = _user_windows[uid][window]

    if count > limit:
        logger.warning("用户限流触发 user_id={} username={} count={} limit={}",
                       uid, user.get("username"), count, limit)
        raise HTTPException(
            status_code=429,
            detail=f"提问太频繁，请 {_WINDOW_SEC} 秒后再试",
            headers={"Retry-After": str(_WINDOW_SEC)},
        )
    return user


def get_debug_stats() -> dict:
    """返回当前限流状态快照（调试用，仅 super_admin 可调）。"""
    window = _current_window()
    with _lock:
        ip_state: dict[str, dict] = {}
        for ip, prefixes in list(_ip_windows.items()):
            # 展平：每个 (ip, prefix) 一条记录
            for prefix, wins in prefixes.items():
                count = wins.get(window, 0)
                if count > 0:
                    key = f"{ip} [{prefix}]"
                    limit = _IP_LIMITS.get(prefix, _IP_DEFAULT_LIMIT)
                    ip_state[key] = {
                        "window": window, "count": count, "limit": limit,
                        "whitelisted": _is_whitelisted(ip),
                    }
        user_state = {}
        for uid, wins in list(_user_windows.items()):
            count = wins.get(window, 0)
            if count > 0:
                user_state[str(uid)] = {"window": window, "count": count}
    return {
        "window_sec": _WINDOW_SEC,
        "current_window": window,
        "ip_limits": dict(_IP_LIMITS),
        "ip_default": _IP_DEFAULT_LIMIT,
        "user_chat_limit": _USER_CHAT_LIMIT,
        "ip_counts": ip_state,
        "user_counts": user_state,
    }
