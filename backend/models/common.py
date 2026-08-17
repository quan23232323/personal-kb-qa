"""统一响应格式。

所有非流式接口均返回 {code, data, message} 结构：
  - code == 0 表示成功
  - code != 0 表示失败（HTTP 错误时 code 取 HTTP 状态码）
"""
from typing import Any


def ok(data: Any = None) -> dict:
    return {"code": 0, "data": data, "message": "success"}


def fail(message: str, code: int = -1) -> dict:
    return {"code": code, "data": None, "message": message}
