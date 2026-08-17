from pydantic import BaseModel


class Source(BaseModel):
    content: str
    document_name: str
    similarity: float


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None


class ChatSession(BaseModel):
    id: str
    kb_id: str
    title: str
    created_at: str
    updated_at: str


class ChatMessage(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    sources: list[Source] = []
    created_at: str
