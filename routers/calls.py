"""
routers/calls.py — Управление голосовыми и видеозвонками

Процесс звонка:
  1. Caller: POST /api/calls/start  → получает call_id
  2. Все участники получают WS-событие "incoming_call"
  3. Caller и Callee подключаются к /ws/call/{call_id}
  4. Через WebSocket обмениваются SDP offer/answer и ICE-кандидатами
  5. После соединения — прямой P2P-канал WebRTC
  6. При завершении: POST /api/calls/{call_id}/end
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from core.config import settings
from core.database import get_db
from core.security import get_current_user
from core.ws_manager import manager
from models.user import User
from models.chat import ChatMember
from models.call import Call, CallStatus, CallType

router = APIRouter(prefix="/api/calls", tags=["Calls"])


class StartCallRequest(BaseModel):
    chat_id: int
    type: str = "voice"   # "voice" | "video"


@router.post("/start")
async def start_call(
    data: StartCallRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Инициировать звонок — уведомить всех участников чата"""
    # Проверка членства
    member = await db.execute(
        select(ChatMember).where(
            ChatMember.chat_id == data.chat_id,
            ChatMember.user_id == current_user.id
        )
    )
    if not member.scalar_one_or_none():
        raise HTTPException(403, "Нет доступа к чату")

    call = Call(
        chat_id=data.chat_id,
        caller_id=current_user.id,
        type=CallType(data.type),
        status=CallStatus.RINGING,
        session_id=uuid.uuid4().hex,
    )
    db.add(call)
    await db.flush()

    # Уведомить всех в чате через WebSocket
    await manager.broadcast_chat(data.chat_id, {
        "type": "incoming_call",
        "call_id": call.id,
        "call_type": data.type,
        "caller": {
            "id": current_user.id,
            "display_name": current_user.display_name,
            "avatar_url": current_user.avatar_url,
        },
        # ICE-серверы для клиента
        "ice_servers": [{"urls": s} for s in settings.STUN_SERVERS],
    })

    return {
        "call_id": call.id,
        "session_id": call.session_id,
        "ice_servers": [{"urls": s} for s in settings.STUN_SERVERS],
    }


@router.post("/{call_id}/accept")
async def accept_call(
    call_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    call = await db.get(Call, call_id)
    if not call:
        raise HTTPException(404, "Звонок не найден")

    call.status = CallStatus.ACCEPTED
    call.accepted_at = datetime.now(timezone.utc)

    # Уведомить caller
    await manager.send_personal(call.caller_id, {
        "type": "call_accepted",
        "call_id": call_id,
        "by_user": current_user.id,
        "ice_servers": [{"urls": s} for s in settings.STUN_SERVERS],
    })
    return {"detail": "Принято", "call_id": call_id}


@router.post("/{call_id}/reject")
async def reject_call(
    call_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    call = await db.get(Call, call_id)
    if not call:
        raise HTTPException(404)
    call.status = CallStatus.REJECTED
    call.ended_at = datetime.now(timezone.utc)

    await manager.send_personal(call.caller_id, {
        "type": "call_rejected",
        "call_id": call_id,
        "by_user": current_user.id,
    })
    await manager.relay_signal(call_id, {"type": "call_ended", "call_id": call_id})
    return {"detail": "Отклонено"}


@router.post("/{call_id}/end")
async def end_call(
    call_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    call = await db.get(Call, call_id)
    if not call:
        raise HTTPException(404)

    call.status = CallStatus.ENDED
    call.ended_at = datetime.now(timezone.utc)
    if call.accepted_at:
        delta = call.ended_at - call.accepted_at
        call.duration_sec = int(delta.total_seconds())

    # Уведомить всех участников звонка
    await manager.relay_signal(call_id, {"type": "call_ended", "call_id": call_id})
    await manager.broadcast_chat(call.chat_id, {
        "type": "call_ended",
        "call_id": call_id,
        "duration_sec": call.duration_sec,
    })
    return {
        "detail": "Завершён",
        "duration_sec": call.duration_sec,
    }


@router.get("/history/{chat_id}")
async def call_history(
    chat_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """История звонков в чате"""
    result = await db.execute(
        select(Call).where(Call.chat_id == chat_id).order_by(Call.started_at.desc()).limit(50)
    )
    calls = result.scalars().all()
    return [
        {
            "id": c.id,
            "type": c.type,
            "status": c.status,
            "caller_id": c.caller_id,
            "started_at": c.started_at,
            "duration_sec": c.duration_sec,
        }
        for c in calls
    ]
