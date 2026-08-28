from sqlalchemy import Column, ForeignKey, Index, String
from sqlalchemy.dialects.mysql import BIGINT, TINYINT

from app.core.database import Base


class QuizDetail(Base):
    __tablename__ = 'quiz_detail'
    __table_args__ = (
        Index('fk_quiz_detail_id_idx', 'quiz_id'), #[cite: 2]
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    quiz_id = Column(BIGINT, ForeignKey('quiz.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False) #[cite: 2]
    answer = Column(String(45), nullable=False) #[cite: 2]
    is_correct = Column(TINYINT(1), nullable=True) #[cite: 2]