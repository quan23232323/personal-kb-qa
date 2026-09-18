"""FastAPI 入口：注册路由、CORS、可选鉴权、统一异常处理。"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from config import BASE_DIR, config
from database import init_db
from middlewares.auth import ApiKeyMiddleware
from models.common import fail
from routers import chat, document, knowledge_base, system
from services import document_service

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
)
logger = logging.getLogger("app")

# 前端构建产物目录（backend/../frontend/dist），一键启动时由后端托管
FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    document_service.reset_stale_processing()
    yield


app = FastAPI(title="PersonalKB-QA", version="1.1.0", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.get("server.cors_origins", ["http://localhost:5173"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 可选鉴权（纯 ASGI 中间件，兼容 SSE 流式响应）
app.add_middleware(ApiKeyMiddleware)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content=fail(exc.detail, exc.status_code))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content=fail("请求参数校验失败", 422))


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    # 异常详情（可能含内部路径/配置）只进日志，不回传给客户端
    logger.exception("未处理异常 %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content=fail("服务器内部错误，请查看后端日志", 500))


app.include_router(knowledge_base.router)
app.include_router(document.router)
app.include_router(chat.router)
app.include_router(system.router)


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str):
    """托管前端 SPA：命中静态文件返回文件，否则回退到 index.html。

    - 仅当 config `server.serve_frontend=true` 且 dist 已构建时生效；
    - `/api` 前缀不在此处理，保留 API 的 JSON 404 语义。
    """
    if not config.get("server.serve_frontend", True) or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")

    if full_path:
        candidate = (FRONTEND_DIST / full_path).resolve()
        if candidate.is_relative_to(FRONTEND_DIST.resolve()) and candidate.is_file():
            return FileResponse(candidate)

    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="前端未构建：请在 frontend 目录执行 npm run build")
