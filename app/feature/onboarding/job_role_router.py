from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.feature.onboarding.job_role_schema import JobRoleResponse
from app.feature.onboarding.job_role_service import fetch_all_active_job_roles

router = APIRouter()


@router.get("/job-roles", response_model=List[JobRoleResponse], status_code=status.HTTP_200_OK)
def get_job_roles(db: Session = Depends(get_db)):
    """
    Return all job roles stored in the database.
    Used by the RoleSelectionPage on the frontend.
    """
    try:
        return fetch_all_active_job_roles(db)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch job roles: {str(e)}",
        )
