"""
routers/chats.py — Создание чатов, список чатов, участники
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from pydantic import BaseModel
from datetime import datetime

from core.database import get_db
from core.security import get_current_user
from core.ws_manager import manager
from models.user import User
from models.chat import Chat, ChatType, ChatMember

router = APIRouter(prefix="/api/chats", tags=["Chats"])


# ── Схемы ─────────────────────────────────────────────────────
class CreatePersonalChat(BaseModel):
    target_user_id: int


class CreateGroupChat(BaseModel):
    name:        str
    member_ids:  list[int]
    description: str = ""


class ChatOut(BaseModel):
    id:          int
    type:        str
    name:        str | None
    avatar_url:  str
    created_at:  datetime
    member_count: int = 0

    class Config:
        from_attributes = True


# ── Эндпоинты ─────────────────────────────────────────────────
@router.get("/")
async def list_my_chats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Список всех чатов текущего пользователя"""
    result = await db.execute(
        select(Chat)
        .join(ChatMember, ChatMember.chat_id == Chat.id)
        .where(ChatMember.user_id == current_user.id, Chat.is_active == True)
    )
    chats = result.scalars().all()
    return [
        {
            "id": c.id,
            "type": c.type,
            "name": c.name,
            "avatar_url": c.avatar_url,
            "created_at": c.created_at,
            "is_online": manager.is_user_online(current_user.id),
        }
        for c in chats
    ]


@router.post("/personal", status_code=201)
async def create_personal_chat(
    data: CreatePersonalChat,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Создать личный чат с пользователем (или вернуть существующий)"""
    # Проверить что целевой пользователь существует
    target = await db.get(User, data.target_user_id)
    if not target:
        raise HTTPException(404, "Пользователь не найден")

    # Поискать существующий чат между двумя пользователями
    existing = await db.execute(
        select(Chat)
        .join(ChatMember, ChatMember.chat_id == Chat.id)
        .where(
            Chat.type == ChatType.PERSONAL,
            ChatMember.user_id == current_user.id
        )
    )
    for chat in existing.scalars().all():
        members_res = await db.execute(
            select(ChatMember).where(
                ChatMember.chat_id == chat.id,
                ChatMember.user_id == data.target_user_id
            )
        )
        if members_res.scalar_one_or_none():
            return {"chat_id": chat.id, "existing": True}

    # Создать новый чат
    chat = Chat(type=ChatType.PERSONAL, created_by=current_user.id)
    db.add(chat)
    await db.flush()

    for uid in [current_user.id, data.target_user_id]:
        db.add(ChatMember(chat_id=chat.id, user_id=uid))

    return {"chat_id": chat.id, "existing": False}


@router.post("/group", status_code=201)
async def create_group_chat(
    data: CreateGroupChat,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Создать групповой чат"""
    chat = Chat(
        type=ChatType.GROUP,
        name=data.name,
        description=data.description,
        created_by=current_user.id,
    )
    db.add(chat)
    await db.flush()

    all_members = list(set(data.member_ids + [current_user.id]))
    for uid in all_members:
        db.add(ChatMember(
            chat_id=chat.id,
            user_id=uid,
            is_admin=(uid == current_user.id)
        ))

    return {"chat_id": chat.id}


@router.get("/{chat_id}/members")
async def get_members(
    chat_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Проверка доступа
    member = await db.execute(
        select(ChatMember).where(
            ChatMember.chat_id == chat_id,
            ChatMember.user_id == current_user.id
        )
    )
    if not member.scalar_one_or_none():
        raise HTTPException(403, "Нет доступа к чату")

    result = await db.execute(
        select(User, ChatMember)
        .join(ChatMember, ChatMember.user_id == User.id)
        .where(ChatMember.chat_id == chat_id)
    )
    return [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "avatar_url": u.avatar_url,
            "is_online": u.is_online or manager.is_user_online(u.id),
            "is_admin": m.is_admin,
        }
        for u, m in result.all()
    ]


@router.post("/{chat_id}/members/{user_id}")
async def add_member(
    chat_id: int, user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Только администратор группы может добавлять участников
    my_membership = await db.execute(
        select(ChatMember).where(
            ChatMember.chat_id == chat_id,
            ChatMember.user_id == current_user.id,
            ChatMember.is_admin == True
        )
    )
    if not my_membership.scalar_one_or_none():
        raise HTTPException(403, "Только администратор может добавлять участников")

    db.add(ChatMember(chat_id=chat_id, user_id=user_id))
    await manager.send_personal(user_id, {"type": "chat_added", "chat_id": chat_id})
    return {"detail": "Участник добавлен"}
