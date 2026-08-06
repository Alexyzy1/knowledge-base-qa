"""IP 白名单访问控制中间件。

开启后，非白名单 IP 只能访问公开端点（登录/注册/健康检查/静态资源），
其余所有请求直接返回 403。

配置来源（优先级从高到低）：
  1. backend/ip_whitelist.conf  每行一个 IP/前缀，# 开头为注释
  2. 环境变量 IP_ACCESS_ALLOWED  逗号分隔的 IP/前缀（兜底）

开关：IP_ACCESS_ENABLED="true" 开启（默认 "false" 关闭）

示例 ip_whitelist.conf:
  # 本机
  127.0.0.1
  # 内网 / Docker
  192.168.
  10.
  172.17.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import Request, HTTPException
from loguru import logger

from backend.core.deps import get_client_ip


# ── 配置 ──
_ENABLED = os.getenv("IP_ACCESS_ENABLED", "false").lower() == "true"

_ALLOWED: set[str] = set()
_CONF_PATH = Path(__file__).resolve().parent.parent / "ip_whitelist.conf"

if _CONF_PATH.exists():
    # 优先读配置文件，一行一个 IP/前缀，支持 # 注释
    for raw in _CONF_PATH.read_text(encoding="utf-8").splitlines():
        ip = raw.split("#")[0].strip()
        if ip:
            _ALLOWED.add(ip)
            logger.info("IP 访问白名单添加 (conf): {}", ip)
elif _ENABLED:
    # 没有配置文件时，从环境变量兜底
    _ALLOWED_RAW = os.getenv("IP_ACCESS_ALLOWED", "")
    if _ALLOWED_RAW:
        for ip in _ALLOWED_RAW.split(","):
            ip = ip.strip()
            if ip:
                _ALLOWED.add(ip)
                logger.info("IP 访问白名单添加 (env): {}", ip)

if _ENABLED and not _ALLOWED:
    logger.warning(
        "IP 访问白名单已启用但未配置任何 IP，"
        "请创建 backend/ip_whitelist.conf 或设置 IP_ACCESS_ALLOWED 环境变量"
    )

# 公开路径：不需要 IP 白名单即可访问
_PUBLIC_EXACT = {"/api/auth/login", "/api/auth/register", "/api/health"}
_PUBLIC_PREFIX = ("/css/", "/js/", "/favicon.ico")


def _is_ip_allowed(ip: str) -> bool:
    """检查 IP 是否在白名单中（支持前缀匹配，与 rate_limit 同逻辑）。"""
    if not ip:
        return False
    for w in _ALLOWED:
        if ip == w or (len(w) < 14 and ip.startswith(w)):
            return True
    return False


def _is_public_path(path: str) -> bool:
    """判断路径是否为公开端点（无需 IP 白名单即可访问）。"""
    # 精确匹配
    if path in _PUBLIC_EXACT:
        return True
    # 首页（仅 /，不匹配所有路径）
    if path == "/":
        return True
    # 前缀匹配（静态资源）
    for prefix in _PUBLIC_PREFIX:
        if path.startswith(prefix):
            return True
    return False


async def ip_access_middleware(request: Request, call_next):
    """FastAPI 中间件：IP 白名单访问控制。

    在所有其他中间件之前执行——未授权 IP 直接拒绝，不消耗后续资源。
    """
    # 未启用 → 直接放行
    if not _ENABLED:
        return await call_next(request)

    path = request.url.path

    # 公开路径 → 不检查 IP
    if _is_public_path(path):
        return await call_next(request)

    ip = get_client_ip(request) or "unknown"
    if not _is_ip_allowed(ip):
        logger.warning("IP 访问被拒 ip={} path={}", ip, path)
        raise HTTPException(status_code=403, detail="IP 不在访问白名单中")

    return await call_next(request)
