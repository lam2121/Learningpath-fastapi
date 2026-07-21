from sqlalchemy import Column, Integer, ForeignKey, Index
from sqlalchemy.dialects.mysql import BIGINT
from app.core.database import Base

class SurveyUser(Base):
    __tablename__ = 'survey_user'
    __table_args__ = (
        Index('fk_survey_user_survey_idx', 'survey_id'), #[cite: 2]
        Index('fk_survey_user_user_idx', 'user_id'), #[cite: 2]
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    survey_id = Column(BIGINT, ForeignKey('survey.id', ondelete='CASCADE'), nullable=False) #[cite: 2]
    answer = Column(Integer, nullable=False) #[cite: 2]
    user_id = Column(BIGINT, ForeignKey('user.id', ondelete='CASCADE'), nullable=False) #[cite: 2]