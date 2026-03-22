"""
routers/websocket.py — Реалтайм чат (WebSocket) + WebRTC-сигнализация

Протокол сообщений (JSON):
────────────────────────────────────────────────────────────────
  Клиент → Сервер:
    { "type": "chat_message",  "chat_id": 1, "text": "...", "reply_to": null }
    { "type": "media_message", "chat_id": 1, "media_id": 42, "text": "" }
    { "type": "typing",        "chat_id": 1 }
    { "type": "stop_typing",   "chat_id": 1 }
    { "type": "read",          "chat_id": 1, "message_id": 99 }
    { "type": "call_offer",    "call_id": 1, "sdp": "..." }
    { "type": "call_answer",   "call_id": 1, "sdp": "..." }
    { "type": "ice_candidate", "call_id": 1, "candidate": {...} }

  Сервер → Клиент:
    { "type": "new_message",   "message": {...} }
    { "type": "user_typing",   "chat_id": 1, "user_id": 2, "name": "Макс" }
    { "type": "user_stop_typing", ... }
    { "type": "message_read",  "chat_id": 1, "message_id": 99, "user_id": 2 }
    { "type": "call_offer",    "call_id": 1, "sdp": "...", "caller": {...} }
    { "type": "call_answer",   "call_id": 1, "sdp": "..." }
    { "type": "ice_candidate", "call_id": 1, "candidate": {...} }
    { "type": "call_ended",    "call_id": 1 }
    { "type": "user_online",   "user_id": 2 }
    { "type": "user_offline",  "user_id": 2 }
────────────────────────────────────────────────────────────────
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, AsyncSessionLocal
from core.security import get_ws_user
from core.ws_manager import manager
from models.user import User
from models.chat import Chat, ChatMember
from models.message import Message, MessageType, MessageRead
from models.media import MediaFile
from models.call import Call, CallStatus

router = APIRouter(tags=["WebSocket"])


# ── Главный WebSocket-эндпоинт ────────────────────────────────
@router.websocket("/ws/chat/{chat_id}")
async def chat_ws(
    websocket: WebSocket,
    chat_id: int,
    db: AsyncSession = Depends(get_db),
):
    user = await get_ws_user(websocket, db)
    if not user:
        return

    # Проверить что пользователь состоит в чате
    member = await db.execute(
        select(ChatMember).where(
            ChatMember.chat_id == chat_id,
            ChatMember.user_id == user.id
        )
    )
    if not member.scalar_one_or_none():
        await websocket.close(code=4003)
        return

    room = f"chat:{chat_id}"
    await manager.connect(room, websocket, user.id)

    # Уведомить участников о появлении онлайн
    user.is_online = True
    await db.commit()
    await manager.broadcast_chat(chat_id, {
        "type": "user_online",
        "user_id": user.id,
        "display_name": user.display_name,
    }, exclude_ws=websocket)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "")

            # ── Текстовое сообщение ───────────────────────────
            if msg_type == "chat_message":
                text = str(data.get("text", "")).strip()
                if not text:
                    continue
                msg = await _save_message(
                    db=db,
                    chat_id=chat_id,
                    sender_id=user.id,
                    msg_type=MessageType.TEXT,
                    text=text,
                    reply_to_id=data.get("reply_to"),
                )
                payload = await _message_payload(msg, user)
                await manager.broadcast_chat(chat_id, payload)

            # ── Медиасообщение (фото/видео/голос/файл) ────────
            elif msg_type == "media_message":
                media_id = data.get("media_id")
                if not media_id:
                    continue
                media = await db.get(MediaFile, media_id)
                if not media:
                    continue

                # Определить тип сообщения по MIME
                if media.mime_type.startswith("image/"):
                    m_type = MessageType.IMAGE
                elif media.mime_type.startswith("video/"):
                    m_type = MessageType.VIDEO
                elif media.mime_type.startswith("audio/"):
                    m_type = MessageType.VOICE
                else:
                    m_type = MessageType.FILE

                msg = await _save_message(
                    db=db,
                    chat_id=chat_id,
                    sender_id=user.id,
                    msg_type=m_type,
                    text=data.get("text", ""),
                    media_id=media_id,
                    reply_to_id=data.get("reply_to"),
                    meta={
                        "filename": media.filename,
                        "size": media.file_size,
                        "duration": media.duration_sec,
                        "width": media.width,
                        "height": media.height,
                    },
                )
                payload = await _message_payload(msg, user)
                payload["media_url"] = f"/static/uploads/{media.file_path}"
                await manager.broadcast_chat(chat_id, payload)

            # ── Typing indicators ─────────────────────────────
            elif msg_type == "typing":
                await manager.broadcast_chat(chat_id, {
                    "type": "user_typing",
                    "chat_id": chat_id,
                    "user_id": user.id,
                    "display_name": user.display_name,
                }, exclude_ws=websocket)

            elif msg_type == "stop_typing":
                await manager.broadcast_chat(chat_id, {
                    "type": "user_stop_typing",
                    "chat_id": chat_id,
                    "user_id": user.id,
                }, exclude_ws=websocket)

            # ── Отметить прочитанным ──────────────────────────
            elif msg_type == "read":
                message_id = data.get("message_id")
                if message_id:
                    existing = await db.execute(
                        select(MessageRead).where(
                            MessageRead.message_id == message_id,
                            MessageRead.user_id == user.id
                        )
                    )
                    if not existing.scalar_one_or_none():
                        db.add(MessageRead(message_id=message_id, user_id=user.id))
                        await db.commit()
                    await manager.broadcast_chat(chat_id, {
                        "type": "message_read",
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "user_id": user.id,
                    })

            # ── WebRTC: пересылка SDP/ICE ─────────────────────
            elif msg_type in ("call_offer", "call_answer", "ice_candidate"):
                call_id = data.get("call_id")
                if call_id:
                    await manager.relay_signal(call_id, {
                        **data,
                        "from_user_id": user.id,
                    }, exclude_ws=websocket)

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(room, websocket)
        user.is_online = False
        user.last_seen = datetime.now(timezone.utc)
        await db.commit()
        await manager.broadcast_chat(chat_id, {
            "type": "user_offline",
            "user_id": user.id,
        })


# ── WebRTC звонки (отдельная комната сигнализации) ────────────
@router.websocket("/ws/call/{call_id}")
async def call_ws(
    websocket: WebSocket,
    call_id: int,
    db: AsyncSession = Depends(get_db),
):
    user = await get_ws_user(websocket, db)
    if not user:
        return

    room = f"call:{call_id}"
    await manager.connect(room, websocket, user.id)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # Пересылаем все WebRTC-сигналы другим участникам звонка
            await manager.relay_signal(call_id, {
                **data,
                "from_user_id": user.id,
            }, exclude_ws=websocket)

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(room, websocket)


# ── Helpers ───────────────────────────────────────────────────
async def _save_message(
    db: AsyncSession,
    chat_id: int,
    sender_id: int,
    msg_type: MessageType,
    text: str = "",
    media_id: int | None = None,
    reply_to_id: int | None = None,
    meta: dict | None = None,
) -> Message:
    msg = Message(
        chat_id=chat_id,
        sender_id=sender_id,
        type=msg_type,
        text=text,
        media_id=media_id,
        reply_to_id=reply_to_id,
        meta=meta or {},
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)
    return msg


async def _message_payload(msg: Message, sender: User) -> dict:
    return {
        "type": "new_message",
        "message": {
            "id": msg.id,
            "chat_id": msg.chat_id,
            "sender_id": sender.id,
            "sender_name": sender.display_name,
            "sender_avatar": sender.avatar_url,
            "msg_type": msg.type,
            "text": msg.text,
            "reply_to_id": msg.reply_to_id,
            "media_url": None,
            "meta": msg.meta,
            "created_at": msg.created_at.isoformat(),
        }
    }
