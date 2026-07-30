from fastapi import APIRouter
from app.feature.auth.auth_router import router as auth_router
from app.feature.onboarding.survey_router import router as survey_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(survey_router, prefix="/onboarding", tags=["Onboarding"])
