from fastapi import APIRouter
from app.feature.auth.auth_router import router as auth_router
from app.feature.onboarding.survey_router import router as onboarding_router
from app.feature.onboarding.job_role_router import router as job_role_router

api_router = APIRouter()

# Gom toàn bộ router của các feature lại
api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(onboarding_router, prefix="/onboarding", tags=["Onboarding"])
api_router.include_router(job_role_router, prefix="/onboarding", tags=["Onboarding"])