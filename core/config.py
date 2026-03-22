"""
core/config.py — Настройки приложения через Pydantic Settings
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List
import json


class Settings(BaseSettings):
    # ── Безопасность ──────────────────────────────────────────
    SECRET_KEY: str = "dev-secret-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 дней

    # ── База данных ───────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./nova_chat.db"

    # ── AI (Anthropic) ────────────────────────────────────────
    ANTHROPIC_API_KEY: str = ""

    # ── Медиафайлы ────────────────────────────────────────────
    MAX_FILE_SIZE: int = 104_857_600  # 100 MB
    MEDIA_DIR: str = "static/uploads"
    ALLOWED_IMAGE_TYPES: List[str] = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    ALLOWED_VIDEO_TYPES: List[str] = ["video/mp4", "video/webm", "video/ogg"]
    ALLOWED_AUDIO_TYPES: List[str] = ["audio/webm", "audio/ogg", "audio/mpeg", "audio/wav"]
    ALLOWED_FILE_TYPES: List[str] = [
        "application/pdf", "application/zip",
        "text/plain", "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ]

    # ── CORS ──────────────────────────────────────────────────
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000", "http://127.0.0.1:8000"]

    # ── WebRTC ────────────────────────────────────────────────
    STUN_SERVERS: List[str] = [
        "stun:stun.l.google.com:19302",
        "stun:stun1.l.google.com:19302"
    ]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
