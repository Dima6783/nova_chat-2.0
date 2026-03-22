"""
models/chat.py — Чаты и участники
"""
from sqlalchemy import String, Boolean, DateTime, Text, Integer, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from core.database import Base
import enum


class ChatType(str, enum.Enum):
    PERSONAL = "personal"   # Личный чат (1-на-1)
    GROUP    = "group"       # Групповой чат
    CHANNEL  = "channel"     # Канал (только чтение)


class Chat(Base):
    __tablename__ = "chats"

    id:          Mapped[int]      = mapped_column(Integer, primary_key=True, index=True)
    type:        Mapped[ChatType] = mapped_column(SAEnum(ChatType), default=ChatType.PERSONAL)
    name:        Mapped[str]      = mapped_column(String(255), nullable=True)   # Только для групп
    description: Mapped[str]      = mapped_column(Text, default="")
    avatar_url:  Mapped[str]      = mapped_column(String(500), default="")
    is_active:   Mapped[bool]     = mapped_column(Boolean, default=True)
    created_at:  Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by:  Mapped[int]      = mapped_column(Integer, ForeignKey("users.id"), nullable=True)

    # Связи
    members:  Mapped[list["ChatMember"]] = relationship("ChatMember", back_populates="chat", cascade="all, delete-orphan")
    messages: Mapped[list["Message"]]    = relationship("Message", back_populates="chat", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Chat id={self.id} type={self.type} name={self.name}>"


class ChatMember(Base):
    __tablename__ = "chat_members"

    id:        Mapped[int]  = mapped_column(Integer, primary_key=True, index=True)
    chat_id:   Mapped[int]  = mapped_column(Integer, ForeignKey("chats.id", ondelete="CASCADE"), index=True)
    user_id:   Mapped[int]  = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    is_admin:  Mapped[bool] = mapped_column(Boolean, default=False)
    is_muted:  Mapped[bool] = mapped_column(Boolean, default=False)
    joined_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Последнее прочитанное сообщение
    last_read_message_id: Mapped[int] = mapped_column(Integer, nullable=True)

    # Связи
    chat: Mapped["Chat"] = relationship("Chat", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="chat_memberships")
