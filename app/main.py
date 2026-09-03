from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api_router import api_router
from app.core.notification_stream import notification_stream_broker
from app.feature.audio.tts_service import clean_audio_cache


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup / shutdown lifecycle hook."""
    # Clean stale audio cache on boot
    clean_audio_cache()
    notification_stream_broker.attach_loop()
    yield


# 1. Khởi tạo Limiter toàn cục
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="TOEIC Learning Path API", lifespan=lifespan)

# 2. Gắn limiter vào app state và đăng ký Exception Handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 3. Thêm SlowAPIMiddleware vào ứng dụng
app.add_middleware(SlowAPIMiddleware)

# Ensure static directory exists
STATIC_DIR = Path("static")
STATIC_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "audio_cache").mkdir(parents=True, exist_ok=True)

# Cho phép frontend (Vite dev server) gọi API
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://english-practice.tma.com.vn",
        "https://localhost:8001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for audio cache access
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/api/static", StaticFiles(directory="static"), name="api_static")

# Bơm "tổng đài" API vào app chính với prefix chung là /api
app.include_router(api_router, prefix="/api")


@app.get("/")
def read_root():
    return {"message": "Welcome to TOEIC Learning Path API!"}