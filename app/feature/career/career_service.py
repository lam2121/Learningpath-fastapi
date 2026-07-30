from fastapi import HTTPException, status

from app.feature.career.career_repository import CareerRepository


class CareerService:

    def __init__(self, repository: CareerRepository):
        self.repository = repository

    def get_all_job_roles(self):
        return self.repository.get_all_job_roles()

    def get_job_role(self, job_role_id: int):
        job_role = self.repository.get_job_role_by_id(job_role_id)

        if not job_role:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job role không tồn tại."
            )

        return job_role