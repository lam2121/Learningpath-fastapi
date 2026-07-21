from sqlalchemy import Column, String, Date, DateTime, Integer, ForeignKey, Index, text
from sqlalchemy.dialects.mysql import BIGINT
from app.core.database import Base

class Queue(Base):
    __tablename__ = 'queue'
    __table_args__ = (
        Index('fk_queue_user_idx', 'user_id'), #[cite: 2]
        Index('fk_queue_quiz_idx', 'quiz_id'), #[cite: 2]
        {'comment': 'Hang doi on tap giai cach kieu SM-2 (toeicapp_spaced_rep_queue)'} #[cite: 2]
    )

    id = Column(BIGINT(unsigned=True), primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    user_id = Column(BIGINT, ForeignKey('user.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False) #[cite: 2]
    quiz_id = Column(BIGINT, ForeignKey('quiz.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False) #[cite: 2]
    status = Column(String(20), nullable=False, comment='CANH_BAO / TRUOT') #[cite: 2]
    next_review_date = Column(Date, nullable=False) #[cite: 2]
    created_at = Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP')) #[cite: 2]
    last_reviewed_at = Column(DateTime, nullable=False) #[cite: 2]
    count = Column(Integer, nullable=False) #[cite: 2]