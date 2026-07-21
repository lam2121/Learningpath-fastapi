from sqlalchemy import Column, String, JSON
from sqlalchemy.dialects.mysql import BIGINT, LONGTEXT
from app.core.database import Base

class JobRole(Base):
    __tablename__ = 'job_role'

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False) #[cite: 2]
    name = Column(String(45), nullable=False) #[cite: 2]
    JD = Column(LONGTEXT, nullable=False) #[cite: 2]
    seed_tier = Column(JSON, nullable=False) #[cite: 2]
    init_weights = Column(JSON, nullable=False) #[cite: 2]
    example_question = Column(JSON, nullable=False) #[cite: 2]