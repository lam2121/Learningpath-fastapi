from sqlalchemy import JSON, Column, ForeignKey, Index
from sqlalchemy.dialects.mysql import BIGINT

from app.core.database import Base


class UserPlacementTest(Base):
    __tablename__ = 'user_placement_test'
    __table_args__ = (
        Index('fk_user_placement_test_1_idx', 'user_id'),
        Index('fk_user_placement_test_2', 'placement_test_question_id'),
    )

    id = Column(BIGINT, primary_key=True, autoincrement=True, nullable=False)
    placement_test_question_id = Column(
        BIGINT,
        ForeignKey('placement_test_question.id'),
        nullable=False,
    )
    user_id = Column(BIGINT, ForeignKey('user.id'), nullable=False)
    user_answer = Column(JSON, nullable=False)
