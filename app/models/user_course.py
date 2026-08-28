from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Index, String
from sqlalchemy.dialects.mysql import BIGINT

from app.core.database import Base


class UserCourse(Base):
    __tablename__ = 'user_course'
    __table_args__ = (
        Index('fk_uc_user_idx', 'user_id'), #[cite: 2]
        Index('fk_uc_course_idx', 'course_id'), #[cite: 2]
        {'comment': 'Luu toan bo lo trinh hoc tap cua user do AI boc ra'} #[cite: 2]
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    user_id = Column(BIGINT, ForeignKey('user.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False) #[cite: 2]
    course_id = Column(BIGINT, ForeignKey('course.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False) #[cite: 2]
    syllabus = Column(JSON, nullable=False, comment='{"topic_id_1": [lesson_1, lesson_2], "topic_id_2": [...]}') #[cite: 2]
    status = Column(String(20), nullable=False, server_default='locked', comment='locked / in_progress / completed') #[cite: 2]
    completed_at = Column(DateTime, nullable=True) #[cite: 2]
    progress = Column(Float, nullable=False, server_default='0') #[cite: 2]
    unlocked_at = Column(DateTime, nullable=False) #[cite: 2]
    user_answers = Column(JSON, nullable=False) #[cite: 2]