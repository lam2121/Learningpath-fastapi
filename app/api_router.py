from fastapi import APIRouter

from app.feature.admin.admin_router import router as admin_router
from app.feature.audio.audio_router import router as audio_router
from app.feature.onboarding.job_role_router import router as job_role_router
from app.feature.onboarding.placement_test_router import router as placement_test_router
from app.feature.user.user_router import router as user_router

api_router = APIRouter()

api_router.include_router(user_router, prefix="/user", tags=["User Profile"])
api_router.include_router(job_role_router, prefix="/onboarding", tags=["Onboarding"])
api_router.include_router(placement_test_router, prefix="/onboarding", tags=["Onboarding"])
api_router.include_router(admin_router, prefix="/admin", tags=["Admin"])
api_router.include_router(audio_router, prefix="/audio", tags=["Audio"])
