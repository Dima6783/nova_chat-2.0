"""
routers/media.py — Загрузка медиафайлов (фото, видео, голосовые, документы)
"""
import uuid
import os
import aiofiles
from pathlib import Path
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from core.config import settings
from core.database import get_db
from core.security import get_current_user
from models.user import User
from models.media import MediaFile

router = APIRouter(prefix="/api/media", tags=["Media"])


class MediaOut(BaseModel):
    id:          int
    filename:    str
    file_path:   str
    mime_type:   str
    file_size:   int
    width:       int | None
    height:      int | None
    duration_sec: int | None
    thumb_path:  str | None

    class Config:
        from_attributes = True


# ── Вспомогательные функции ───────────────────────────────────
def get_media_subdir(mime_type: str) -> str:
    """Определить подпапку по MIME-типу"""
    if mime_type.startswith("image/"):
        return "images"
    if mime_type.startswith("video/"):
        return "videos"
    if mime_type.startswith("audio/"):
        return "voice"
    return "files"


def is_allowed(mime_type: str) -> bool:
    all_allowed = (
        settings.ALLOWED_IMAGE_TYPES +
        settings.ALLOWED_VIDEO_TYPES +
        settings.ALLOWED_AUDIO_TYPES +
        settings.ALLOWED_FILE_TYPES
    )
    return mime_type in all_allowed


async def save_upload(
    file: UploadFile,
    subdir: str,
    user_id: int,
    db: AsyncSession,
) -> MediaFile:
    """Сохранить файл на диск и запись в БД"""
    mime = file.content_type or "application/octet-stream"
    if not is_allowed(mime):
        raise HTTPException(415, f"Тип файла не поддерживается: {mime}")

    # Читаем данные
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(413, "Файл слишком большой")

    # Уникальное имя файла
    ext = Path(file.filename or "file").suffix or ""
    stored_name = f"{uuid.uuid4().hex}{ext}"
    rel_path = f"{subdir}/{stored_name}"
    abs_path = Path(settings.MEDIA_DIR) / rel_path

    # Создать директорию если нет
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    # Записать файл асинхронно
    async with aiofiles.open(abs_path, "wb") as f:
        await f.write(content)

    # Получить размеры для изображений
    width = height = None
    if mime.startswith("image/"):
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(content))
            width, height = img.size
        except Exception:
            pass

    media = MediaFile(
        uploader_id=user_id,
        filename=file.filename or stored_name,
        stored_name=stored_name,
        file_path=rel_path,
        mime_type=mime,
        file_size=len(content),
        width=width,
        height=height,
    )
    db.add(media)
    await db.flush()
    return media


# ── Эндпоинты ─────────────────────────────────────────────────
@router.post("/upload/image", response_model=MediaOut)
async def upload_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    media = await save_upload(file, "images", current_user.id, db)
    return MediaOut.model_validate(media)


@router.post("/upload/video", response_model=MediaOut)
async def upload_video(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    media = await save_upload(file, "videos", current_user.id, db)
    return MediaOut.model_validate(media)


@router.post("/upload/voice", response_model=MediaOut)
async def upload_voice(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Голосовое сообщение (WebM/OGG/MP3)"""
    media = await save_upload(file, "voice", current_user.id, db)
    return MediaOut.model_validate(media)


@router.post("/upload/file", response_model=MediaOut)
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    media = await save_upload(file, "files", current_user.id, db)
    return MediaOut.model_validate(media)
