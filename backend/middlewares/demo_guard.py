"""演示模式写操作闸门（纯 ASGI 中间件，兼容 SSE 流式响应）。

演示环境面向公网开放，知识库是共享的只读资产：如果允许访客上传或删除，
第一个访问者就能把它改坏。这里按「方法 + 路径」做白名单——只放行问答接口，
其余写操作直接返回 403，并给出体面的中文说明（而不是让前端弹一个 500）。
"""
from starlette.responses import JSONResponse

from services import demo_service

_FRIENDLY_MESSAGE = (
    "这是公网演示环境，知识库内容已固定，暂不支持上传、修改或删除。"
    "你仍可直接向知识库提问，体验检索与问答全流程。"
)


class DemoWriteGuardMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and demo_service.is_write_blocked(
            scope.get("method", "GET"), scope.get("path", "")
        ):
            resp = JSONResponse(
                status_code=403,
                content={"code": 403, "data": None, "message": _FRIENDLY_MESSAGE},
            )
            await resp(scope, receive, send)
            return
        await self.app(scope, receive, send)
