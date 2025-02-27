from pydantic import BaseModel
from datetime import datetime

class ChatMessage(BaseModel):
    question: str

class ChatResponse(BaseModel):
    id: str
    chat: str
    question: str
    answer: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ChatHistoryResponse(BaseModel):
    chat_id: str
    user: str
    created_at: datetime
    updated_at: datetime
    messages: list[ChatResponse]


class SupportTicketCreate(BaseModel):
    title: str
    description: str
    priority: str

class SupportTicketResponse(BaseModel):
    id: str
    user: str
    title: str
    description: str
    status: str
    priority: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True