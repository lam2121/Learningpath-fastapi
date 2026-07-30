from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.feature.career.career_repository import CareerRepository
from app.feature.career.career_service import CareerService
from app.feature.career.career_schema import (
    JobRoleResponse,
    JobRoleDetailResponse,
)

router = APIRouter()
@router.get(
    "/job-roles",
    response_model=list[JobRoleResponse]
)
def get_job_roles(
    db: Session = Depends(get_db)
):
    repository = CareerRepository(db)
    service = CareerService(repository)

    return service.get_all_job_roles()
@router.get(
    "/job-roles/{job_role_id}",
    response_model=JobRoleDetailResponse
)
def get_job_role(
    job_role_id: int,
    db: Session = Depends(get_db)
):
    repository = CareerRepository(db)
    service = CareerService(repository)

    return service.get_job_role(job_role_id)