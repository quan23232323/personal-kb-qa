from pydantic import BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""


class KnowledgeBase(BaseModel):
    id: str
    name: str
    description: str
    created_at: str
    updated_at: str
    document_count: int = 0
