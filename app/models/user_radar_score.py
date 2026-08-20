from sqlalchemy import Column, JSON, DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.mysql import BIGINT
from app.core.database import Base

class UserRadarScore(Base):
    __tablename__ = 'user_radar_score'
    __table_args__ = (
        Index('uq_user_radar_score', 'user_id', unique=True),
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False)
    user_id = Column(BIGINT, ForeignKey('user.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False)
    start_vector = Column(JSON, nullable=False, comment='Diem goc luc bat dau course nay') #[cite: 2]
    current_vector = Column(JSON, nullable=True, comment='Diem hien tai thuoc ve lesson moi nhat') #[cite: 2]
    prev_stack = Column(JSON, nullable=False, comment='Mang luu cac lesson vector truoc do trong course') #[cite: 2]
    updated_at = Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP')) #[cite: 2]