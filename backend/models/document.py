from pydantic import BaseModel


class Document(BaseModel):
    id: str
    kb_id: str
    filename: str
    file_path: str
    file_type: str
    file_size: int
    chunk_count: int
    status: str
    error_message: str | None = None
    created_at: str
