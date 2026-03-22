"""
models/call.py — Голосовые и видеозвонки
"""
from sqlalchemy import String, Boolean, DateTime, Integer, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from core.database import Base
import enum


class CallStatus(str, enum.Enum):
    RINGING  = "ringing"   # Звонок идёт
    ACCEPTED = "accepted"  # Принят
    REJECTED = "rejected"  # Отклонён
    MISSED   = "missed"    # Пропущен
    ENDED    = "ended"     # Завершён


class CallType(str, enum.Enum):
    VOICE = "voice"
    VIDEO = "video"


class Call(Base):
    __tablename__ = "calls"

    id:          Mapped[int]        = mapped_column(Integer, primary_key=True, index=True)
    chat_id:     Mapped[int]        = mapped_column(Integer, ForeignKey("chats.id"), index=True)
    caller_id:   Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), index=True)
    type:        Mapped[CallType]   = mapped_column(SAEnum(CallType), default=CallType.VOICE)
    status:      Mapped[CallStatus] = mapped_column(SAEnum(CallStatus), default=CallStatus.RINGING)

    # Время начала, принятия, завершения
    started_at:  Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    accepted_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at:    Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)

    # Длительность в секундах (заполняется при завершении)
    duration_sec: Mapped[int] = mapped_column(Integer, nullable=True)

    # WebRTC session ID
    session_id: Mapped[str] = mapped_column(String(100), nullable=True)

    # Связи
    caller: Mapped["User"] = relationship("User", back_populates="calls_initiated", foreign_keys=[caller_id])
    chat:   Mapped["Chat"] = relationship("Chat", foreign_keys=[chat_id])
