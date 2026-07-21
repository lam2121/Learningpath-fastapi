from sqlalchemy import Column, String, DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.mysql import BIGINT
from app.core.database import Base

class Course(Base):
    __tablename__ = 'course'
    __table_args__ = (
        Index('fk_course_job_role_idx', 'job_role_id'), #[cite: 2]
        {'comment': 'Ban thiet ke lo trinh khung (Blueprint)'} #[cite: 2]
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    name = Column(String(255), nullable=False) #[cite: 2]
    created_at = Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')) #[cite: 2]
    job_role_id = Column(BIGINT, ForeignKey('job_role.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False) #[cite: 2]