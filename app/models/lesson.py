from sqlalchemy import JSON, Boolean, Column, ForeignKey, Index, String
from sqlalchemy.dialects.mysql import BIGINT

from app.core.database import Base


class Lesson(Base):
    __tablename__ = "lesson"
    __table_args__ = (
        Index("fk_lesson_topic_idx", "topic_id"),
        {"comment": "Lesson shells / Role, sinh boi Generator B2"},
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False)
    topic_id = Column(
        BIGINT,
        ForeignKey("topic.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    title = Column(String(255), nullable=False)
    primary_skill = Column(
        String(45), nullable=False, comment="D_doc | C_comm | T_trouble | G_custom"
    )
    difficulty_tier = Column(
        String(20), nullable=False, comment="basic | intermediate | advanced"
    )
    theory_content = Column(JSON, nullable=True)  # NULL until lazily generated (C-1)
    quiz_content = Column(JSON, nullable=True)  # NULL until lazily generated (C-2)
    is_generated = Column(Boolean, nullable=False, server_default="0")
