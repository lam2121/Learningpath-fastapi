from sqlalchemy import Column, String, JSON
from sqlalchemy.dialects.mysql import BIGINT, LONGTEXT
from app.core.database import Base


class JobRole(Base):
    __tablename__ = "job_role"

    id = Column(BIGINT, primary_key=True, autoincrement=True)

    name = Column(String(100), nullable=False)

    JD = Column(LONGTEXT, nullable=False)
    seed_tier = Column(JSON, nullable=False)
    init_weights = Column(JSON, nullable=False)
    example_question = Column(JSON, nullable=False)