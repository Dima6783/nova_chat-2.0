"""
routers/messages.py — История сообщений, редактирование, удаление
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from datetime import datetime

from core.database import get_db
from core.security import get_current_user
from models.user import User
from models.chat import ChatMember
from models.message import Message, MessageType, MessageRead

router = APIRouter(prefix="/api/messages", tags=["Messages"])


# ── Схемы ─────────────────────────────────────────────────────
class MessageOut(BaseModel):
    id:          int
    chat_id:     int
    sender_id:   int
    sender_name: str
    type:        str
    text:        str
    media_url:   str | None
    reply_to_id: int | None
    is_edited:   bool
    created_at:  datetime
    read_count:  int = 0


# ── Эндпоинты ─────────────────────────────────────────────────
@router.get("/{chat_id}")
async def get_history(
    chat_id: int,
    before_id: int | None = Query(None, description="Курсор пагинации — id сообщения"),
    limit: int = Query(50, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Получить историю сообщений чата (пагинация курсором)"""
    # Проверка доступа
    member = await db.execute(
        select(ChatMember).where(
            ChatMember.chat_id == chat_id,
            ChatMember.user_id == current_user.id
        )
    )
    if not member.scalar_one_or_none():
        raise HTTPException(403, "Нет доступа к чату")

    query = (
        select(Message)
        .where(Message.chat_id == chat_id, Message.is_deleted == False)
        .order_by(desc(Message.id))
        .limit(limit)
    )
    if before_id:
        query = query.where(Message.id < before_id)

    result = await db.execute(query)
    msgs = result.scalars().all()

    # Собираем данные sender
    out = []
    for m in reversed(msgs):
        sender = await db.get(User, m.sender_id)
        media_url = None
        if m.media:
            media_url = f"/static/uploads/{m.media.file_path}"
        out.append({
            "id": m.id,
            "chat_id": m.chat_id,
            "sender_id": m.sender_id,
            "sender_name": sender.display_name if sender else "Удалён",
            "sender_avatar": sender.avatar_url if sender else "",
            "type": m.type,
            "text": m.text,
            "media_url": media_url,
            "reply_to_id": m.reply_to_id,
            "is_edited": m.is_edited,
            "created_at": m.created_at,
            "meta": m.meta,
        })
    return out


@router.patch("/{message_id}")
async def edit_message(
    message_id: int,
    text: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    msg = await db.get(Message, message_id)
    if not msg:
        raise HTTPException(404, "Сообщение не найдено")
    if msg.sender_id != current_user.id:
        raise HTTPException(403, "Нельзя редактировать чужое сообщение")
    if msg.type != MessageType.TEXT:
        raise HTTPException(400, "Можно редактировать только текстовые сообщения")

    from datetime import timezone
    msg.text = text
    msg.is_edited = True
    msg.edited_at = datetime.now(timezone.utc)
    return {"detail": "Отредактировано"}


@router.delete("/{message_id}")
async def delete_message(
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    msg = await db.get(Message, message_id)
    if not msg:
        raise HTTPException(404, "Сообщение не найдено")
    if msg.sender_id != current_user.id:
        raise HTTPException(403, "Нельзя удалить чужое сообщение")

    msg.is_deleted = True
    msg.text = ""
    return {"detail": "Удалено"}


@router.post("/{chat_id}/read/{message_id}")
async def mark_read(
    chat_id: int,
    message_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отметить сообщение прочитанным"""
    existing = await db.execute(
        select(MessageRead).where(
            MessageRead.message_id == message_id,
            MessageRead.user_id == current_user.id
        )
    )
    if not existing.scalar_one_or_none():
        db.add(MessageRead(message_id=message_id, user_id=current_user.id))
    return {"detail": "ok"}
