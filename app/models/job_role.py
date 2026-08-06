from sqlalchemy import JSON, Boolean, Column, ForeignKey, String
from sqlalchemy.dialects.mysql import BIGINT, LONGTEXT

from app.core.database import Base

DEFAULT_BASELINE = {
    "D_doc": 25,
    "C_comm": 25,
    "T_trouble": 25,
    "G_custom": 25,
}


class JobRole(Base):
    __tablename__ = "job_role"

    id = Column(BIGINT, primary_key=True, autoincrement=True)

    name = Column(String(100), nullable=False)

    # v2.1 columns
    job_description = Column(LONGTEXT, nullable=False)
    baseline = Column(JSON, nullable=False, default=dict(DEFAULT_BASELINE))
    g_skill_description = Column(LONGTEXT, nullable=False)
    seed_tier_1 = Column(LONGTEXT, nullable=False)
    seed_tier_2 = Column(LONGTEXT, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    created_by = Column(
        BIGINT, ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    # Legacy column kept for back-compat (unused by v2.1 core flow)
    example_question = Column(JSON, nullable=True)
