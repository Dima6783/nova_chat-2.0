"""
models/media.py — Медиафайлы (изображения, видео, голосовые, документы)
"""
from sqlalchemy import String, Integer, ForeignKey, DateTime, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from core.database import Base


class MediaFile(Base):
    __tablename__ = "media_files"

    id:           Mapped[int]  = mapped_column(Integer, primary_key=True, index=True)
    uploader_id:  Mapped[int]  = mapped_column(Integer, ForeignKey("users.id"), index=True)

    # Оригинальное имя файла
    filename:     Mapped[str]  = mapped_column(String(500))
    # Имя файла на диске (uuid-based)
    stored_name:  Mapped[str]  = mapped_column(String(500), unique=True)
    # Относительный путь от MEDIA_DIR
    file_path:    Mapped[str]  = mapped_column(String(1000))

    mime_type:    Mapped[str]  = mapped_column(String(100))
    file_size:    Mapped[int]  = mapped_column(BigInteger)   # Байты

    # Для изображений и видео
    width:        Mapped[int]  = mapped_column(Integer, nullable=True)
    height:       Mapped[int]  = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[int]  = mapped_column(Integer, nullable=True)   # Для аудио/видео

    # Thumbnail (для видео)
    thumb_path:   Mapped[str]  = mapped_column(String(1000), nullable=True)

    created_at:   Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    uploader: Mapped["User"] = relationship("User", foreign_keys=[uploader_id])
