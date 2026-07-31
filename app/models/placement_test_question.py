from sqlalchemy import Column, String, Integer, DateTime, JSON, ForeignKey, Index
from sqlalchemy.dialects.mysql import BIGINT
from app.core.database import Base

class PlacementTestQuestion(Base):
    __tablename__ = 'placement_test_question'
    __table_args__ = (
        Index('fk_placement_test_quiz__idx', 'quiz_type_id'),
        Index('fk_placement_test_question_job_role_idx', 'job_role_id'),
        {'comment': 'Cau hoi test dau vao, sinh boi Generator A'}
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False)
    question = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False)
    skill = Column(String(45), nullable=False)
    level = Column(Integer, nullable=False)
    quiz_type_id = Column(BIGINT, ForeignKey('quiz_type.id', ondelete='NO ACTION', onupdate='NO ACTION'), nullable=False)
    job_role_id = Column(BIGINT, ForeignKey('job_role.id', ondelete='NO ACTION', onupdate='NO ACTION'), nullable=False)