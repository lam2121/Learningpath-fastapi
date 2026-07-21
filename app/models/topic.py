from sqlalchemy import Column, String, Integer, JSON, ForeignKey, Index
from sqlalchemy.dialects.mysql import BIGINT
from app.core.database import Base

class Topic(Base):
    __tablename__ = 'topic'
    __table_args__ = (
        Index('fk_topic_course_idx', 'course_id'), #[cite: 2]
        {'comment': 'Pool 20 Topics / Role, sinh boi Generator B'} #[cite: 2]
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    name = Column(String(255), nullable=False) #[cite: 2]
    english_level = Column(Integer, nullable=False, comment='Essentials -> Advanced Jargon') #[cite: 2]
    skill_weight = Column(JSON, nullable=False) #[cite: 2]
    business_level = Column(Integer, nullable=False) #[cite: 2]
    course_id = Column(BIGINT, ForeignKey('course.id', ondelete='CASCADE', onupdate='CASCADE'), nullable=False) #[cite: 2]