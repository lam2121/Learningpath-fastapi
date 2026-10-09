from sqlalchemy import Column, ForeignKey, Index, String
from sqlalchemy.dialects.mysql import BIGINT

from app.core.infra.database import Base


class UserFlashcard(Base):
    __tablename__ = "user_flashcard"
    __table_args__ = (
        Index("fk_user_flashcard_1_idx", "user_id"),
        Index("uq_user_flashcard_user_word", "user_id", "word_eng", unique=True),
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False)
    user_id = Column(BIGINT, ForeignKey("user.id"), nullable=False)
    word_eng = Column(String(45), nullable=False)
    word_vi = Column(String(50), nullable=True)
    word_ja = Column(String(150), nullable=True)
    transcription = Column(String(45), nullable=True)
    context = Column(String(500), nullable=True)
    workspace_example = Column(String(500), nullable=True)
