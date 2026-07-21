from sqlalchemy import Column, JSON, DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.mysql import BIGINT
from app.core.database import Base

class UserCourseSkillVector(Base):
    __tablename__ = 'user_course_skill_vector'
    __table_args__ = (
        Index('uq_user_course_vector', 'user_course_id', unique=True), #[cite: 2]
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    user_course_id = Column(BIGINT, ForeignKey('user_course.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False) #[cite: 2]
    start_vector = Column(JSON, nullable=False, comment='Diem goc luc bat dau course nay') #[cite: 2]
    current_vector = Column(JSON, nullable=True, comment='Diem hien tai thuoc ve lesson moi nhat') #[cite: 2]
    prev_stack = Column(JSON, nullable=False, comment='Mang luu cac lesson vector truoc do trong course') #[cite: 2]
    updated_at = Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')) #[cite: 2]