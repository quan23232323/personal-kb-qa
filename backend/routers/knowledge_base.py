from fastapi import APIRouter, HTTPException

from models.common import ok
from models.knowledge_base import KnowledgeBaseCreate
from services import kb_service

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-bases"])


@router.post("")
def create_kb(body: KnowledgeBaseCreate):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="知识库名称不能为空")
    return ok(kb_service.create_kb(name, body.description.strip()))


@router.get("")
def list_kbs():
    return ok(kb_service.list_kbs())


@router.get("/{kb_id}")
def get_kb(kb_id: str):
    kb = kb_service.get_kb(kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return ok(kb)


@router.delete("/{kb_id}")
def delete_kb(kb_id: str):
    if not kb_service.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    kb_service.delete_kb(kb_id)
    return ok({"ok": True})
