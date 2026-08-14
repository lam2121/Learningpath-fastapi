from copy import deepcopy

from sqlalchemy import JSON, Boolean, Column, ForeignKey, String
from sqlalchemy.dialects.mysql import BIGINT, LONGTEXT

from app.core.database import Base

DEFAULT_BASELINE = {
    "D_doc": 25,
    "C_comm": 25,
    "T_trouble": 25,
    "G_custom": 25,
}

DEFAULT_SKILL_DESCRIPTIONS = {
    "D_doc": (
        "Ability to read and write clear, concise, and structured "
        "technical documentation."
    ),
    "C_comm": (
        "Effective verbal and written communication in professional "
        "IT contexts."
    ),
    "T_trouble": (
        "Skills in identifying, analyzing, and resolving technical issues."
    ),
    "G_custom": (
        "Specific domain knowledge and expertise required for this role."
    ),
}


def default_skill_definitions() -> dict[str, dict[str, str | list[str]]]:
    return {
        key: {
            "description": description,
            "example_questions": [],
        }
        for key, description in deepcopy(DEFAULT_SKILL_DESCRIPTIONS).items()
    }


class JobRole(Base):
    __tablename__ = "job_role"

    id = Column(BIGINT, primary_key=True, autoincrement=True)

    name = Column(String(45), nullable=False)

    # v2.1 columns
    job_description = Column(LONGTEXT, nullable=False)
    baseline = Column(JSON, nullable=False, default=dict(DEFAULT_BASELINE))
    skill_definitions = Column(JSON, nullable=False, default=default_skill_definitions)
    seed_tier_1 = Column(LONGTEXT, nullable=False)
    seed_tier_2 = Column(LONGTEXT, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")
    created_by = Column(
        BIGINT, ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
