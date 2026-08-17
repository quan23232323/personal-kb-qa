"""知识库 CRUD 业务逻辑。"""
import shutil
import uuid

from config import config
from database import db
from utils.time_utils import now_iso
from . import retrieval_service


def _row_to_kb(row) -> dict:
    d = dict(row)
    d.setdefault("document_count", 0)
    return d


def create_kb(name: str, description: str) -> dict:
    kb_id = str(uuid.uuid4())
    now = now_iso()
    with db() as conn:
        conn.execute(
            "INSERT INTO knowledge_bases(id, name, description, created_at, updated_at) VALUES (?,?,?,?,?)",
            (kb_id, name, description, now, now),
        )
    return get_kb(kb_id)


def list_kbs() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT kb.*,
                   (SELECT COUNT(*) FROM documents d WHERE d.kb_id = kb.id) AS document_count
            FROM knowledge_bases kb
            ORDER BY kb.created_at DESC
            """
        ).fetchall()
    return [_row_to_kb(r) for r in rows]


def get_kb(kb_id: str) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT kb.*,
                   (SELECT COUNT(*) FROM documents d WHERE d.kb_id = kb.id) AS document_count
            FROM knowledge_bases kb
            WHERE kb.id = ?
            """,
            (kb_id,),
        ).fetchone()
    return _row_to_kb(row) if row else None


def delete_kb(kb_id: str) -> None:
    # 1) 删除 SQLite 记录（documents/sessions/messages 靠外键级联删除）
    with db() as conn:
        conn.execute("DELETE FROM knowledge_bases WHERE id = ?", (kb_id,))
    # 2) 删除原始文件目录
    upload_dir = config.resolve_path(config.get("storage.upload_dir", "./data/uploads")) / kb_id
    shutil.rmtree(upload_dir, ignore_errors=True)
    # 3) 删除 ChromaDB Collection
    retrieval_service.delete_collection(kb_id)
