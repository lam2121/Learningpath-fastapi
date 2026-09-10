from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api_router import api_router
from app.core.config import app_config
from app.core.ensure_queue_schema import ensure_queue_schema
from app.core.notification_stream import notification_stream_broker
from app.feature.audio.tts_service import clean_audio_cache


def _check_shared_jwt_secret() -> None:
    """Warn loudly (but do not crash) if SECRET_KEY diverges from the external
    auth-service's signing secret. A mismatch makes every authenticated request
    fail with 401 and prevents users from being provisioned into
    toeic_learningpath.user — a silent, hard-to-debug login failure."""
    if (
        app_config.AUTH_SHARED_SECRET
        and app_config.SECRET_KEY
        and app_config.SECRET_KEY != app_config.AUTH_SHARED_SECRET
    ):
        print(
            "\n"
            "*******************************************************************\n"
            "WARNING: careerpath-fastapi SECRET_KEY does NOT match the shared\n"
            "auth-service JWT secret. Login will fail (401) and users will NOT\n"
            "be provisioned into toeic_learningpath.user.\n"
            f"  .env SECRET_KEY                = {app_config.SECRET_KEY!r}\n"
            f"  auth-service JWT_SECRET_KEY    = {app_config.AUTH_SHARED_SECRET!r}\n"
            "Set careerpath-fastapi/.env SECRET_KEY to the auth-service secret.\n"
            "*******************************************************************\n"
        )


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup / shutdown lifecycle hook."""
    # Warn at startup if the shared JWT secret diverges (auth provisioning guard)
    _check_shared_jwt_secret()
    # Ensure queue schema supports spaced repetition review
    ensure_queue_schema()
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
        "https://builtbylam.com",
        "https://www.builtbylam.com",
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