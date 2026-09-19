from fastapi import APIRouter, Request

from config import config
from database import db
from models.common import ok
from services import demo_service, embedding_service, retrieval_service

router = APIRouter(tags=["system"])


@router.get("/health")
def health(request: Request):
    info = embedding_service.describe()
    status = {
        "status": "ok",
        "database": "ok",
        "chroma": "unknown",
        "embedding": "unknown",
        "embedding_mode": info["mode"],
        "embedding_model": info["model"],
        "llm_mode": config.get("llm.mode", "ollama"),
        "demo": demo_service.snapshot(request),
    }
    try:
        with db() as conn:
            conn.execute("SELECT 1")
    except Exception as e:
        status["database"] = f"error: {e}"
        status["status"] = "degraded"

    try:
        retrieval_service.get_client()
        status["chroma"] = "ok"
    except Exception as e:
        status["chroma"] = f"unavailable: {e}"

    # 只检查当前后端真正需要的依赖，避免「配置了 fastembed 却去 import torch」的误报
    try:
        mode = info["mode"]
        if mode == "fastembed":
            import fastembed  # noqa: F401

            status["embedding"] = f"fastembed ({info['model']})"
        elif mode == "openai":
            import openai  # noqa: F401

            status["embedding"] = f"openai ({info['model']})"
        else:
            import sentence_transformers  # noqa: F401

            status["embedding"] = f"sentence-transformers ({info['model']})"
    except Exception as e:
        status["embedding"] = f"unavailable: {e}"

    return ok(status)
