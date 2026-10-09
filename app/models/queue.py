from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT

from app.core.infra.database import Base


class Queue(Base):
    __tablename__ = 'queue'
    __table_args__ = (
        Index('fk_queue_user_idx', 'user_id'),
        Index('fk_queue_lesson_idx', 'lesson_id'),
        UniqueConstraint('user_id', 'lesson_id', 'question_id', name='uq_queue_user_lesson_question'),
        {'comment': 'Spaced repetition review queue for wrong quiz answers (toeicapp_spaced_rep_queue)'},
    )

    id = Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, nullable=False)
    user_id = Column(BIGINT, ForeignKey('user.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False)
    quiz_id = Column(BIGINT, nullable=True)  # Kept for backward compatibility
    lesson_id = Column(BIGINT, ForeignKey('lesson.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=True)
    question_id = Column(String(50), nullable=True)
    question_type = Column(String(50), nullable=True)  # fill_blank, multi_select, ordering
    stem = Column(Text, nullable=True)
    options = Column(JSON, nullable=True)
    correct_answer = Column(Text, nullable=True)
    explanation = Column(Text, nullable=True)
    last_wrong_answer = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, server_default='pending')
    next_review_date = Column(Date, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP'))
    last_reviewed_at = Column(DateTime, nullable=True)
    count = Column(Integer, nullable=False, server_default='1')
