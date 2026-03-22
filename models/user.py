"""
models/user.py — Модель пользователя
"""
from sqlalchemy import String, Boolean, DateTime, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from core.database import Base


class User(Base):
    __tablename__ = "users"

    id:         Mapped[int]  = mapped_column(Integer, primary_key=True, index=True)
    username:   Mapped[str]  = mapped_column(String(50), unique=True, index=True, nullable=False)
    email:      Mapped[str]  = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name:  Mapped[str] = mapped_column(String(100), nullable=False)
    bio:        Mapped[str]  = mapped_column(Text, default="")
    avatar_url: Mapped[str]  = mapped_column(String(500), default="")
    is_active:  Mapped[bool] = mapped_column(Boolean, default=True)
    is_online:  Mapped[bool] = mapped_column(Boolean, default=False)

    # Последняя активность
    last_seen:  Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    # Связи
    sent_messages:    Mapped[list["Message"]] = relationship("Message", back_populates="sender", foreign_keys="Message.sender_id")
    chat_memberships: Mapped[list["ChatMember"]] = relationship("ChatMember", back_populates="user")
    calls_initiated:  Mapped[list["Call"]] = relationship("Call", back_populates="caller", foreign_keys="Call.caller_id")

    def __repr__(self):
        return f"<User id={self.id} username={self.username}>"
