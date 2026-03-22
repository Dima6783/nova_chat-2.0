"""
models/message.py — Сообщения (текст, голос, фото, видео, файлы)
"""
from sqlalchemy import String, Boolean, DateTime, Text, Integer, ForeignKey, Enum as SAEnum, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from core.database import Base
import enum


class MessageType(str, enum.Enum):
    TEXT   = "text"           # Обычное текстовое сообщение
    IMAGE  = "image"          # Фотография
    VIDEO  = "video"          # Видеофайл
    VOICE  = "voice"          # Голосовое сообщение
    FILE   = "file"           # Документ / файл
    SYSTEM = "system"         # Системное (пользователь вошёл и т.д.)
    CALL   = "call"           # Запись о звонке


class Message(Base):
    __tablename__ = "messages"

    id:        Mapped[int]         = mapped_column(Integer, primary_key=True, index=True)
    chat_id:   Mapped[int]         = mapped_column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    sender_id: Mapped[int]         = mapped_column(Integer, ForeignKey("users.id"), index=True)
    type:      Mapped[MessageType] = mapped_column(SAEnum(MessageType), default=MessageType.TEXT)

    # Текст (для TEXT-сообщений и подписей к медиа)
    text: Mapped[str] = mapped_column(Text, default="")

    # Медиа (ссылка на файл)
    media_id:  Mapped[int] = mapped_column(Integer, ForeignKey("media_files.id"), nullable=True)

    # Reply
    reply_to_id: Mapped[int] = mapped_column(Integer, ForeignKey("messages.id"), nullable=True)

    # Состояние
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_edited:  Mapped[bool] = mapped_column(Boolean, default=False)

    # Метаданные (длительность голосового, размеры фото и т.д.)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    edited_at:  Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)

    # Связи
    chat:     Mapped["Chat"]      = relationship("Chat", back_populates="messages")
    sender:   Mapped["User"]      = relationship("User", back_populates="sent_messages", foreign_keys=[sender_id])
    media:    Mapped["MediaFile"] = relationship("MediaFile", foreign_keys=[media_id])
    reply_to: Mapped["Message"]   = relationship("Message", remote_side="Message.id", foreign_keys=[reply_to_id])
    read_by:  Mapped[list["MessageRead"]] = relationship("MessageRead", back_populates="message", cascade="all, delete-orphan")


class MessageRead(Base):
    """Отслеживание прочитанных сообщений"""
    __tablename__ = "message_reads"

    id:         Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    user_id:    Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    read_at:    Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    message: Mapped["Message"] = relationship("Message", back_populates="read_by")
