from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Index
from sqlalchemy.dialects.mysql import BIGINT, LONGTEXT
from app.core.database import Base

class PlacementTestQuestion(Base):
    __tablename__ = 'placement_test_question'
    __table_args__ = (
        Index('fk_placement_test_quiz__idx', 'quiz_type_id'), #[cite: 2]
        Index('fk_placement_test_question_job_role_idx', 'job_role_id'), #[cite: 2]
        {'comment': 'Cau hoi test dau vao, sinh boi Generator A'} #[cite: 2]
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    question = Column(LONGTEXT, nullable=False) #[cite: 2]
    created_at = Column(DateTime, nullable=False) #[cite: 2]
    skill = Column(String(45), nullable=False) #[cite: 2]
    level = Column(Integer, nullable=False) #[cite: 2]
    quiz_type_id = Column(BIGINT, ForeignKey('quiz_type.id', ondelete='NO ACTION', onupdate='NO ACTION'), nullable=False) #[cite: 2]
    job_role_id = Column(BIGINT, ForeignKey('job_role.id', ondelete='NO ACTION', onupdate='NO ACTION'), nullable=False) #[cite: 2]