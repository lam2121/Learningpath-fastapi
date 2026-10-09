from fastapi import APIRouter

from app.feature.admin.admin_router import router as admin_router
from app.feature.audio.audio_router import router as audio_router
from app.feature.flashcard.flashcard_router import router as flashcard_router
from app.feature.onboarding.job_role_router import router as job_role_router
from app.feature.onboarding.placement_router import router as placement_router
from app.feature.roadmap.roadmap_router import router as roadmap_router
from app.feature.quiz.quiz_router import router as quiz_router
from app.feature.user.user_router import router as user_router

api_router = APIRouter()

api_router.include_router(user_router, prefix="/user", tags=["User Profile"])
api_router.include_router(job_role_router, prefix="/onboarding", tags=["Onboarding"])
api_router.include_router(placement_router, prefix="/onboarding", tags=["Onboarding - Placement"])
api_router.include_router(roadmap_router, prefix="/onboarding", tags=["Curriculum Roadmap"])
api_router.include_router(quiz_router, prefix="/onboarding", tags=["Quizzes & Evaluation"])
api_router.include_router(admin_router, prefix="/admin", tags=["Admin"])
api_router.include_router(audio_router, prefix="/audio", tags=["Audio"])
api_router.include_router(flashcard_router, prefix="/flashcard", tags=["Flashcard"])
