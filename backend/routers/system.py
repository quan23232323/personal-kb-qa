from fastapi import APIRouter

from config import config
from database import db
from models.common import ok
from services import retrieval_service

router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    status = {
        "status": "ok",
        "database": "ok",
        "chroma": "unknown",
        "embedding": "unknown",
        "llm_mode": config.get("llm.mode", "ollama"),
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

    try:
        if config.get("embedding.mode", "local") == "openai":
            import openai  # noqa: F401

            status["embedding"] = "openai"
        else:
            import sentence_transformers  # noqa: F401

            status["embedding"] = "local (sentence-transformers available)"
    except Exception as e:
        status["embedding"] = f"unavailable: {e}"

    return ok(status)
