from sqlalchemy import Column, ForeignKey, Index, String
from sqlalchemy.dialects.mysql import BIGINT, LONGTEXT

from app.core.database import Base


class Quiz(Base):
    __tablename__ = 'quiz'
    __table_args__ = (
        Index('fk_quiz_lesson_idx', 'lesson_id'), #[cite: 2]
        Index('fk_quiz_type_idx', 'quiz_type_id'), #[cite: 2]
        {'comment': '30 cau quiz polymorphic / lesson, sinh boi Generator C'} #[cite: 2]
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    question = Column(LONGTEXT, nullable=False) #[cite: 2]
    skill = Column(String(45), nullable=False) #[cite: 2]
    quiz_type_id = Column(BIGINT, ForeignKey('quiz_type.id', ondelete='RESTRICT', onupdate='CASCADE'), nullable=False) #[cite: 2]
    lesson_id = Column(BIGINT, ForeignKey('lesson.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False) #[cite: 2]