from sqlalchemy.orm import Session

from app.models.job_role import JobRole


class CareerRepository:

    def __init__(self, db: Session):
        self.db = db

    def get_all_job_roles(self):
        return self.db.query(JobRole).all()

    def get_job_role_by_id(self, job_role_id: int):
        return (
            self.db.query(JobRole)
            .filter(JobRole.id == job_role_id)
            .first()
        )