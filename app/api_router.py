from fastapi import APIRouter
from app.feature.auth.auth_router import router as auth_router
# Các router khác sau này bạn cứ import vào đây, ví dụ:
# from app.feature.assessment.assessment_router import router as assessment_router

api_router = APIRouter()

# Gom toàn bộ router của các feature lại
api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
# api_router.include_router(assessment_router, prefix="/assessments", tags=["Assessment"])