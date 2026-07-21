from sqlalchemy import Column, String, DateTime, Float, JSON, ForeignKey, Index, text
from sqlalchemy.dialects.mysql import BIGINT
from app.core.database import Base

class UserLesson(Base):
    __tablename__ = 'user_lesson'
    __table_args__ = (
        Index('fk_ul_user_idx', 'user_id'), #[cite: 2]
        Index('fk_ul_lesson_idx', 'lesson_id'), #[cite: 2]
        {'comment': 'Quan ly trang thai va bai lam cua tung lesson le (Lazy Load)'} #[cite: 2]
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    user_id = Column(BIGINT, ForeignKey('user.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False) #[cite: 2]
    lesson_id = Column(BIGINT, ForeignKey('lesson.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False) #[cite: 2]
    user_answers = Column(JSON, nullable=False, comment='Luu ket qua 30 cau quiz cua lesson') #[cite: 2]
    status = Column(String(20), nullable=False, server_default='locked', comment='locked / in_progress / completed') #[cite: 2]
    completed_at = Column(DateTime, nullable=True) #[cite: 2]
    progress = Column(Float, nullable=False, server_default='0') #[cite: 2]
    unlocked_at = Column(DateTime, nullable=True) #[cite: 2]