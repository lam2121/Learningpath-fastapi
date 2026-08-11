from sqlalchemy import Column, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.mysql import BIGINT

from app.core.database import Base


class Topic(Base):
    __tablename__ = "topic"
    __table_args__ = (
        Index("fk_topic_job_role_idx", "role_id"),
        {"comment": "Pool 20 Topics / Role, sinh boi Generator B"},
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False)
    role_id = Column(
        BIGINT,
        ForeignKey("job_role.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    primary_skill = Column(
        String(45), nullable=False, comment="D_doc | C_comm | T_trouble | G_custom"
    )
    seed_tier = Column(String(10), nullable=False, comment="tier_1 | tier_2")
    sort_order = Column(Integer, nullable=False)
