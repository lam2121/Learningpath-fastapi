from fastapi import APIRouter
from app.feature.auth.auth_router import router as auth_router
from app.feature.onboarding.survey_router import router as onboarding_router

api_router = APIRouter()

# Gom toàn bộ router của các feature lại
api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(onboarding_router, prefix="/onboarding", tags=["Onboarding"])