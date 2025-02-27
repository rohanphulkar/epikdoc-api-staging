from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from .model import Chat, Message, SupportTicket, TicketPriority
from .schema import ChatMessage, SupportTicketCreate, ChatResponse, ChatHistoryResponse, SupportTicketResponse
from db.db import get_db
from sqlalchemy.orm import Session
from utils.auth import get_current_user
from utils.chatbot import get_answer
from typing import Dict, List
from auth.model import User
from utils.email import send_support_ticket_email
import json

support_router = APIRouter()


@support_router.get(
    "/get-chat",
    response_model=Dict,
    summary="Get or create user chat",
    description="Retrieves existing chat for the user or creates a new one if none exists"
)
async def get_chat(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    
    chat = db.query(Chat).filter(Chat.user == user_id).first()
    if not chat:
        chat = Chat(user=user_id)
        db.add(chat)
        db.commit()
        db.refresh(chat)
    return {"chat_id": chat.id}


@support_router.post(
    "/send-message/{chat_id}",
    response_model=ChatResponse,
    summary="Send chat message",
    description="Send a message in the chat and get AI response"
)
async def send_message(
    chat_id: str,
    message: ChatMessage,
    db: Session = Depends(get_db)
):
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        return JSONResponse(status_code=404, content={"detail": "Chat not found"})
    
    answer = get_answer(message.question)
    msg = Message(chat=chat.id, question=message.question, answer=answer)
    db.add(msg)
    db.commit()
    db.refresh(msg)

    return ChatResponse(id=msg.id, chat=msg.chat, question=msg.question, answer=msg.answer, created_at=msg.created_at, updated_at=msg.updated_at)


@support_router.get(
    "/get-chats",
    response_model=ChatHistoryResponse,
    summary="Get user chat history",
    description="Retrieves all messages from user's chat history"
)
async def get_chats(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    
    chat = db.query(Chat).filter(Chat.user == user_id).first()
    if not chat:
        return JSONResponse(status_code=404, content={"detail": "No chats found"})
        
    messages = db.query(Message).filter(Message.chat == chat.id).all()
    return ChatHistoryResponse(
        chat_id=chat.id,
        user=chat.user,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=[ChatResponse.from_orm(msg) for msg in messages]
    )


@support_router.post(
    "/create-ticket",
    response_model=SupportTicketResponse,
    summary="Create support ticket",
    description="Creates a new support ticket with specified title, description and priority"
)
async def create_ticket(
    request: Request,
    ticket_data: SupportTicketCreate,
    db: Session = Depends(get_db)
):
    user_id = get_current_user(request)
    if not user_id:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        return JSONResponse(status_code=404, content={"detail": "User not found"})
    
    try:
        priority = TicketPriority[ticket_data.priority.upper()]
    except KeyError:
        return JSONResponse(status_code=400, content={"detail": "Invalid priority level"})
        
    ticket = SupportTicket(
        user=user_id,
        title=ticket_data.title,
        description=ticket_data.description,
        priority=priority
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    email_sent = send_support_ticket_email(user.email, ticket.title, ticket.description, ticket.priority.value, ticket.status.value)

    if not email_sent:
        return JSONResponse(status_code=500, content={"detail": "Failed to send email notification"})
    
    return SupportTicketResponse.from_orm(ticket)
