from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT

from app.core.database import Base


class UserTopicQuiz(Base):
    __tablename__ = "user_topic_quiz"
    __table_args__ = (
        Index("fk_user_topic_quiz_user_idx", "user_id"),
        Index("fk_user_topic_quiz_topic_idx", "topic_id"),
        UniqueConstraint("user_id", "topic_id", name="uq_user_topic_quiz_user_topic"),
        {"comment": "User topic quiz attempts and pass state (§4.2, zero AI)"},
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
    status = Column(
        String(20),
        nullable=False,
        server_default="unlocked",
        comment="unlocked | passed | failed",
    )
    attempt_count = Column(Integer, nullable=False, server_default="0")
    failed_attempts = Column(Integer, nullable=False, server_default="0")
    best_score_percent = Column(Float, nullable=False, server_default="0")
    last_score_percent = Column(Float, nullable=False, server_default="0")
    weakest_lesson_ids = Column(
        JSON,
        nullable=True,
        comment="[lesson_id_1, lesson_id_2] for review flag",
    )
    user_answers = Column(
        JSON,
        nullable=True,
        comment="Latest attempt snapshot and active question bank",
    )
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )
