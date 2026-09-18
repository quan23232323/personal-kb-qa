"""可选 API Key 鉴权（纯 ASGI 中间件，兼容 SSE 流式响应）。"""
import hmac

from starlette.responses import JSONResponse

from config import config


class ApiKeyMiddleware:
    """security.api_key 为空时自动禁用；启用后校验 /api/* 的 X-API-Key 请求头。

    使用纯 ASGI 中间件而非 BaseHTTPMiddleware，避免后者缓冲破坏 SSE 流式响应。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            api_key = config.get("security.api_key", "")
            # OPTIONS 为 CORS 预检请求，不含业务头，跳过鉴权
            if api_key and scope.get("method") != "OPTIONS" and scope["path"].startswith("/api"):
                headers = {
                    k.decode("latin-1").lower(): v.decode("latin-1")
                    for k, v in scope.get("headers", [])
                }
                supplied = headers.get("x-api-key", "")
                # compare_digest 恒定时间比较，避免时序侧信道逐字节探测 key
                if not hmac.compare_digest(supplied, api_key):
                    resp = JSONResponse(
                        status_code=401,
                        content={"code": 401, "data": None, "message": "API Key 无效"},
                    )
                    await resp(scope, receive, send)
                    return
        await self.app(scope, receive, send)
