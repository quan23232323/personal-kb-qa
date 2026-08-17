from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile

from config import config
from models.common import ok
from services import document_service, kb_service, retrieval_service
from utils import file_utils

router = APIRouter(tags=["documents"])


@router.post("/api/knowledge-bases/{kb_id}/documents")
def upload_document(kb_id: str, background: BackgroundTasks, file: UploadFile = File(...)):
    if not kb_service.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    content = file.file.read()
    max_bytes = config.get("document.max_file_size_mb", 50) * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"文件超过大小限制（{max_bytes // 1024 // 1024}MB）")

    file_type = file_utils.detect_type(file.filename or "", content[:8])
    if file_type is None:
        raise HTTPException(status_code=400, detail="不支持的文件类型，或文件内容与扩展名不符")

    doc = document_service.create_document_from_upload(kb_id, file.filename or "", file_type, content)
    background.add_task(
        document_service.process_document,
        doc["id"],
        kb_id,
        doc["file_path"],
        file_type,
        doc["filename"],
    )
    return ok(doc)


@router.post("/api/knowledge-bases/{kb_id}/documents/batch")
def upload_documents(
    kb_id: str, background: BackgroundTasks, files: list[UploadFile] = File(...)
):
    """批量上传：逐个校验/入库，单个文件失败不影响其余文件。"""
    if not kb_service.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")

    max_bytes = config.get("document.max_file_size_mb", 50) * 1024 * 1024
    succeeded: list[dict] = []
    failed: list[dict] = []

    for f in files:
        filename = f.filename or ""
        content = f.file.read()
        if len(content) > max_bytes:
            failed.append(
                {"filename": filename, "error": f"文件超过大小限制（{max_bytes // 1024 // 1024}MB）"}
            )
            continue
        file_type = file_utils.detect_type(filename, content[:8])
        if file_type is None:
            failed.append({"filename": filename, "error": "不支持的文件类型，或内容与扩展名不符"})
            continue
        doc = document_service.create_document_from_upload(kb_id, filename, file_type, content)
        background.add_task(
            document_service.process_document,
            doc["id"],
            kb_id,
            doc["file_path"],
            file_type,
            doc["filename"],
        )
        succeeded.append({"id": doc["id"], "filename": doc["filename"]})

    return ok(
        {
            "total": len(files),
            "succeeded_count": len(succeeded),
            "failed_count": len(failed),
            "succeeded": succeeded,
            "failed": failed,
        }
    )


@router.get("/api/knowledge-bases/{kb_id}/documents")
def list_documents(kb_id: str):
    if not kb_service.get_kb(kb_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    return ok(document_service.list_documents(kb_id))


@router.get("/api/documents/{doc_id}/chunks")
def document_chunks(doc_id: str):
    """查看某文档提取出的全部分块（用于前端预览知识）。"""
    doc = document_service.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    chunks = retrieval_service.get_document_chunks(doc["kb_id"], doc_id)
    return ok({"chunk_count": len(chunks), "chunks": chunks})


@router.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    if not document_service.delete_document(doc_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    return ok({"ok": True})


@router.post("/api/documents/{doc_id}/reprocess")
def reprocess_document(doc_id: str, background: BackgroundTasks):
    doc = document_service.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc["status"] == "processing":
        raise HTTPException(status_code=400, detail="文档正在处理中")
    document_service.start_reprocess(doc_id)
    background.add_task(
        document_service.process_document,
        doc_id,
        doc["kb_id"],
        doc["file_path"],
        doc["file_type"],
        doc["filename"],
    )
    return ok(document_service.get_document(doc_id))
