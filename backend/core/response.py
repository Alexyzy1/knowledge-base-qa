"""统一响应结构 {code, msg, data}。code=0 成功，非 0 失败。"""
from typing import Any
from fastapi.responses import JSONResponse


def success(data: Any = None, msg: str = "ok") -> dict:
    return {"code": 0, "msg": msg, "data": data}


def fail(code: int = 1, msg: str = "error", data: Any = None) -> JSONResponse:
    # 用 JSONResponse 显式包，异常处理器里直接返回它
    return JSONResponse(status_code=200, content={"code": code, "msg": msg, "data": data})
