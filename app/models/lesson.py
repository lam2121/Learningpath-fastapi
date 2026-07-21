from sqlalchemy import Column, String, Integer, JSON, ForeignKey, Index
from sqlalchemy.dialects.mysql import BIGINT
from app.core.database import Base

class Lesson(Base):
    __tablename__ = 'lesson'
    __table_args__ = (
        Index('fk_lesson_topic_idx', 'topic_id'), #[cite: 2]
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    theory = Column(JSON, nullable=True) #[cite: 2]
    topic_id = Column(BIGINT, ForeignKey('topic.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False) #[cite: 2]
    name = Column(String(45), nullable=False) #[cite: 2]
    skill_weight = Column(JSON, nullable=False) #[cite: 2]
    english_level = Column(Integer, nullable=False) #[cite: 2]
    business_level = Column(Integer, nullable=False) #[cite: 2]