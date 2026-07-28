from sqlalchemy import Column
from sqlalchemy.dialects.mysql import BIGINT, LONGTEXT, JSON
from app.core.database import Base

class Survey(Base):
    __tablename__ = 'survey'
    __table_args__ = {'comment': 'Cau hoi Survey rating 1-10, ho tro deep-dive branching'} #[cite: 2]

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    content = Column(JSON, nullable=False) #[cite: 2]