from sqlalchemy import Column, JSON
from sqlalchemy.dialects.mysql import BIGINT
from app.core.database import Base

class Survey(Base):
    __tablename__ = 'survey'
    __table_args__ = {'comment': 'Cau hoi Survey rating 1-10, ho tro deep-dive branching'}

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False)
    content = Column(JSON, nullable=False)