"""
core/ws_manager.py — Менеджер WebSocket-соединений

Управляет активными подключениями и рассылкой сообщений:
  • chat:{chat_id}  — комната чата
  • user:{user_id}  — личные уведомления пользователя
  • call:{call_id}  — WebRTC-сигнализация звонка
"""
from __future__ import annotations
import asyncio
import json
import logging
from collections import defaultdict
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger("nova.ws")


class ConnectionManager:
    def __init__(self):
        # room_key -> set of WebSocket
        self._rooms: Dict[str, Set[WebSocket]] = defaultdict(set)
        # WebSocket -> user_id (для логирования)
        self._ws_user: Dict[WebSocket, int] = {}
        self._lock = asyncio.Lock()

    # ── Подключение / отключение ──────────────────────────────
    async def connect(self, room: str, ws: WebSocket, user_id: int):
        await ws.accept()
        async with self._lock:
            self._rooms[room].add(ws)
            self._ws_user[ws] = user_id
        logger.info(f"[WS] user={user_id} joined room={room}")

    async def disconnect(self, room: str, ws: WebSocket):
        async with self._lock:
            self._rooms[room].discard(ws)
            user_id = self._ws_user.pop(ws, "?")
            if not self._rooms[room]:
                del self._rooms[room]
        logger.info(f"[WS] user={user_id} left room={room}")

    # ── Отправка ──────────────────────────────────────────────
    async def send_to(self, room: str, payload: dict, exclude: WebSocket | None = None):
        """Разослать сообщение всем в комнате"""
        data = json.dumps(payload, ensure_ascii=False, default=str)
        dead: list[WebSocket] = []

        for ws in list(self._rooms.get(room, [])):
            if ws is exclude:
                continue
            try:
                await ws.send_text(data)
            except Exception as e:
                logger.warning(f"[WS] send failed: {e}")
                dead.append(ws)

        # Удаляем мёртвые соединения
        for ws in dead:
            await self.disconnect(room, ws)

    async def send_personal(self, user_id: int, payload: dict):
        """Личное сообщение конкретному пользователю"""
        await self.send_to(f"user:{user_id}", payload)

    async def broadcast_chat(self, chat_id: int, payload: dict, exclude_ws: WebSocket | None = None):
        """Разослать в чат-комнату"""
        await self.send_to(f"chat:{chat_id}", payload, exclude=exclude_ws)

    async def relay_signal(self, call_id: int, payload: dict, exclude_ws: WebSocket | None = None):
        """Пересылка WebRTC-сигнала (SDP offer/answer, ICE candidates)"""
        await self.send_to(f"call:{call_id}", payload, exclude=exclude_ws)

    # ── Утилиты ───────────────────────────────────────────────
    def get_online_users(self, chat_id: int) -> Set[int]:
        """Множество user_id онлайн в данном чате"""
        room = f"chat:{chat_id}"
        return {self._ws_user[ws] for ws in self._rooms.get(room, []) if ws in self._ws_user}

    def is_user_online(self, user_id: int) -> bool:
        room = f"user:{user_id}"
        return bool(self._rooms.get(room))

    @property
    def total_connections(self) -> int:
        return sum(len(v) for v in self._rooms.values())


# Глобальный экземпляр
manager = ConnectionManager()
