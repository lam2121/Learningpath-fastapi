from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import BIGINT

from app.core.database import Base


class UserCourse(Base):
    __tablename__ = "user_course"
    __table_args__ = (
        Index("fk_uc_user_idx", "user_id"),
        Index("fk_uc_course_idx", "course_id"),
        UniqueConstraint("user_id", "course_id", name="uq_user_course_user_course"),
        {"comment": "User course progress, syllabus, and final graduation quiz attempts"},
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False)
    user_id = Column(
        BIGINT,
        ForeignKey("user.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    course_id = Column(
        BIGINT,
        ForeignKey("course.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    syllabus = Column(
        JSON,
        nullable=True,
        comment='{"topic_id_1": [lesson_1, lesson_2], "topic_id_2": [...]}',
    )
    status = Column(
        String(20),
        nullable=False,
        server_default="locked",
        comment="locked | ready | passed | failed",
    )
    completed_at = Column(DateTime, nullable=True)
    progress = Column(Float, nullable=False, server_default="0")
    unlocked_at = Column(DateTime, nullable=True)
    user_answers = Column(
        JSON,
        nullable=True,
        comment="Latest attempt snapshot and active question bank",
    )
    attempt_count = Column(Integer, nullable=False, server_default="0")
    failed_attempts = Column(Integer, nullable=False, server_default="0")
    best_score_percent = Column(Float, nullable=False, server_default="0")
    last_score_percent = Column(Float, nullable=False, server_default="0")
    skill_scores = Column(
        JSON,
        nullable=True,
        comment="Latest per-skill accuracy percentages e.g. {'D_doc': 85.0, ...}",
    )
    weakest_lesson_ids = Column(
        JSON,
        nullable=True,
        comment="[lesson_id_1, lesson_id_2] for review flag",
    )
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