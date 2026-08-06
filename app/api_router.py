from fastapi import APIRouter
from app.feature.auth.auth_router import router as auth_router
from app.feature.onboarding.survey_router import router as survey_router
from app.feature.onboarding.job_role_router import router as job_role_router
from app.feature.admin.admin_router import router as admin_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(survey_router, prefix="/onboarding", tags=["Onboarding"])
api_router.include_router(job_role_router, prefix="/onboarding", tags=["Onboarding"])
api_router.include_router(admin_router, prefix="/admin", tags=["Admin"])
