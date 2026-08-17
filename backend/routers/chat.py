from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from models.chat import ChatRequest
from models.common import ok
from services import chat_service, kb_service

router = APIRouter(tags=["chat"])


def _ensure_kb(kb_id: str):
    if not kb_service.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")


@router.post("/api/knowledge-bases/{kb_id}/chat")
def chat(kb_id: str, body: ChatRequest):
    _ensure_kb(kb_id)
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")
    return ok(chat_service.chat(kb_id, question, body.session_id))


@router.post("/api/knowledge-bases/{kb_id}/chat/stream")
def chat_stream(kb_id: str, body: ChatRequest):
    _ensure_kb(kb_id)
    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")
    return EventSourceResponse(chat_service.chat_stream(kb_id, question, body.session_id))


@router.get("/api/knowledge-bases/{kb_id}/sessions")
def list_sessions(kb_id: str):
    _ensure_kb(kb_id)
    return ok(chat_service.list_sessions(kb_id))


@router.get("/api/sessions/{session_id}/messages")
def list_messages(session_id: str):
    return ok(chat_service.list_messages(session_id))
