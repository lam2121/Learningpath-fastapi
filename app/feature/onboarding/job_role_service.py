from sqlalchemy.orm import Session

from app.models.job_role import JobRole


def fetch_all_active_job_roles(db: Session):
    """Return all job_role rows ordered by id."""
    return db.query(JobRole).order_by(JobRole.id).all()
