from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT

from app.core.infra.database import Base


class UserRoadmap(Base):
    __tablename__ = "user_roadmap"
    __table_args__ = (
        Index("fk_user_roadmap_user_idx", "user_id"),
        Index("fk_user_roadmap_topic_idx", "topic_id"),
        UniqueConstraint("user_id", "topic_id", name="uq_user_roadmap_user_topic"),
        {"comment": "8-topic learning roadmap per user (Phase A, zero AI)"},
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False)
    user_id = Column(
        BIGINT,
        ForeignKey("user.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    topic_id = Column(
        BIGINT,
        ForeignKey("topic.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    sort_order = Column(Integer, nullable=False)
    track = Column(
        String(20), nullable=False, comment="basic | intermediate | advanced"
    )
    created_at = Column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
