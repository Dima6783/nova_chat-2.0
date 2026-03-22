"""
routers/auth.py — Регистрация, вход, профиль
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime, timezone

from core.database import get_db
from core.security import hash_password, verify_password, create_access_token, get_current_user
from models.user import User
from routers.media import save_upload

router = APIRouter(prefix="/api/auth", tags=["Auth"])


# ── Схемы ─────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    username:     str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    email:        EmailStr
    display_name: str = Field(min_length=1, max_length=100)
    password:     str = Field(min_length=6)


class UserOut(BaseModel):
    id:           int
    username:     str
    email:        str
    display_name: str
    bio:          str
    avatar_url:   str
    is_online:    bool
    created_at:   datetime

    class Config:
        from_attributes = True


class TokenOut(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user:         UserOut


# ── Эндпоинты ─────────────────────────────────────────────────
@router.post("/register", response_model=TokenOut, status_code=201)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Проверка уникальности
    existing = await db.execute(
        select(User).where((User.username == data.username) | (User.email == data.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(400, "Пользователь с таким именем или email уже существует")

    user = User(
        username=data.username,
        email=data.email,
        display_name=data.display_name,
        password_hash=hash_password(data.password),
        is_online=True,
    )
    db.add(user)
    await db.flush()  # получаем id

    token = create_access_token({"sub": str(user.id)})
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(User).where((User.username == form.username) | (User.email == form.username))
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(form.password, user.password_hash):
        raise HTTPException(401, "Неверный логин или пароль")
    if not user.is_active:
        raise HTTPException(403, "Аккаунт заблокирован")

    user.is_online = True
    token = create_access_token({"sub": str(user.id)})
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.post("/logout")
async def logout(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    current_user.is_online = False
    current_user.last_seen = datetime.now(timezone.utc)
    return {"detail": "Вышли из системы"}


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)


@router.patch("/me", response_model=UserOut)
async def update_profile(
    display_name: str | None = None,
    bio: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if display_name:
        current_user.display_name = display_name
    if bio is not None:
        current_user.bio = bio
    return UserOut.model_validate(current_user)


@router.post("/me/avatar", response_model=UserOut)
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    media = await save_upload(file, "avatars", current_user.id, db)
    current_user.avatar_url = f"/static/uploads/avatars/{media.stored_name}"
    return UserOut.model_validate(current_user)


@router.get("/users/search")
async def search_users(
    q: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(User).where(
            (User.username.ilike(f"%{q}%") | User.display_name.ilike(f"%{q}%")) &
            (User.id != current_user.id)
        ).limit(20)
    )
    return [UserOut.model_validate(u) for u in result.scalars().all()]
