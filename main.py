"""
main.py — Nova Chat Server
════════════════════════════════════════════════════════════════
Запуск:
  pip install -r requirements.txt
  cp .env.example .env          # заполни секреты
  uvicorn main:app --reload     # разработка
  uvicorn main:app --host 0.0.0.0 --port 8000  # продакшн
════════════════════════════════════════════════════════════════
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from core.config import settings
from core.database import create_tables

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("nova")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / Shutdown"""
    logger.info("🚀 Nova Chat запускается...")
    await create_tables()
    logger.info("✅ База данных инициализирована")
    yield
    logger.info("👋 Nova Chat завершает работу")


# ── Приложение ────────────────────────────────────────────────
app = FastAPI(
    title="Nova Chat API",
    description="Мессенджер с голосовыми звонками, медиафайлами и WebRTC",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Статические файлы (медиа) ─────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Роутеры ───────────────────────────────────────────────────
from routers import auth, chats, messages, media, calls, websocket  # noqa: E402

app.include_router(auth.router)
app.include_router(chats.router)
app.include_router(messages.router)
app.include_router(media.router)
app.include_router(calls.router)
app.include_router(websocket.router)


# ── Главная страница → отдаём фронтенд ───────────────────────
@app.get("/", include_in_schema=False)
async def index():
    return FileResponse("static/index.html")


# ── Health check ─────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health():
    from core.ws_manager import manager
    return {
        "status": "ok",
        "ws_connections": manager.total_connections,
        "version": "1.0.0",
    }


# ── Запуск напрямую ───────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=6000,
        reload=True,
        log_level="info",
    )
