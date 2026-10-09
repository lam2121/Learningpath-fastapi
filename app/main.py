import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.infra.limiter import limiter

import logging
from app.api_router import api_router
from app.core.ai.client.gemini import close_gemini_client_pool, get_gemini_client_pool
from app.core.ensure_queue_schema import ensure_queue_schema
from app.core.infra.config import app_config
from app.core.infra.database import SessionLocal
from app.core.infra.notification_stream import notification_stream_broker
from app.feature.admin.admin_service import mark_stale_generations_all
from app.feature.audio.tts_service import clean_audio_cache

logger = logging.getLogger(__name__)


def _fingerprint(secret: str) -> str:
    """A comparable, non-disclosing stand-in for a secret in startup output."""
    return f"{secret[:6]}… ({len(secret)} chars)" if secret else "<unset>"


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
            f"  .env SECRET_KEY                = {_fingerprint(app_config.SECRET_KEY)}\n"
            f"  auth-service JWT_SECRET_KEY    = {_fingerprint(app_config.AUTH_SHARED_SECRET)}\n"
            "Set careerpath-fastapi/.env SECRET_KEY to the auth-service secret.\n"
            "*******************************************************************\n"
        )


def _cleanup_stale_generations_sync() -> int:
    """Synchronously cleans stale generation jobs in a thread-pool worker."""
    db = SessionLocal()
    try:
        return mark_stale_generations_all(db)
    finally:
        db.close()


async def _periodic_stale_generation_cleanup() -> None:
    while True:
        try:
            await asyncio.sleep(app_config.STALE_CLEANUP_INTERVAL_SECONDS)
            count = await anyio.to_thread.run_sync(_cleanup_stale_generations_sync)
            if count > 0:
                logger.info("Periodic cleanup: marked %d stale generation jobs as failed", count)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("Error in periodic stale generation cleanup: %s", e)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Startup / shutdown lifecycle hook."""
    # Warn at startup if the shared JWT secret diverges (auth provisioning guard)
    _check_shared_jwt_secret()
    # Ensure queue schema supports spaced repetition review (legacy runtime patch)
    try:
        ensure_queue_schema()
    except Exception as e:
        logger.warning("ensure_queue_schema encountered notice/error: %s", e)
    # Clean stale audio cache on boot in thread
    await anyio.to_thread.run_sync(clean_audio_cache)
    # Clean stale generation jobs on boot in thread (resilient to unreachable DB)
    try:
        stale_count = await anyio.to_thread.run_sync(_cleanup_stale_generations_sync)
        if stale_count > 0:
            logger.info("Startup cleanup: marked %d stale generation jobs as failed", stale_count)
    except Exception as e:
        logger.warning("Startup database cleanup skipped (database unreachable): %s", e)

    notification_stream_broker.attach_loop()
    # Optionally pull the ~4.8GB of Wav2Vec2 checkpoints into cache before the first
    # learner hits /audio/pronunciation. Fire-and-forget on a worker thread so boot
    # stays instant: doing it synchronously would re-download/re-load on every
    # `uvicorn --reload` restart. Off by default (see PRONUNCIATION_PRELOAD_MODELS).
    if app_config.PRONUNCIATION_PRELOAD_MODELS:
        from app.feature.audio.pronunciation_service import warm_up_models

        asyncio.create_task(anyio.to_thread.run_sync(warm_up_models))

    cleanup_task = asyncio.create_task(_periodic_stale_generation_cleanup())
    # Initialize LLM client pool singleton (resilient to missing AI credentials)
    try:
        get_gemini_client_pool()
    except Exception as e:
        logger.warning(
            "LLM client pool could not be initialized at startup: %s. "
            "AI generation endpoints will be unavailable until credentials are provided.",
            e,
        )
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        try:
            await close_gemini_client_pool()
        except Exception:
            pass
        await notification_stream_broker.close()



# 1. Khởi tạo FastAPI
app = FastAPI(title="TOEIC Learning Path API", lifespan=lifespan)

# 2. Gắn limiter vào app state và đăng ký Exception Handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 3. Thêm SlowAPIMiddleware vào ứng dụng
app.add_middleware(SlowAPIMiddleware)

# Ensure static directory exists
STATIC_DIR = app_config.RESOLVED_STATIC_DIR
STATIC_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "audio_cache").mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "uploads" / "avatars").mkdir(parents=True, exist_ok=True)

# Cho phép frontend (Vite dev server) gọi API
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_config.CORS_ORIGINS_LIST,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for audio cache access
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/api/static", StaticFiles(directory=str(STATIC_DIR)), name="api_static")

# Bơm "tổng đài" API vào app chính với prefix chung là /api
app.include_router(api_router, prefix="/api")


@app.get("/")
def read_root():
    return {"message": "Welcome to TOEIC Learning Path API!"}