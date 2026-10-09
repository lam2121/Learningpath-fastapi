from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.mysql import BIGINT, LONGTEXT

from app.core.infra.database import Base


class PlacementTestQuestion(Base):
    __tablename__ = "placement_test_question"
    __table_args__ = (
        Index("fk_placement_test_question_job_role_idx", "job_role_id"),  # [cite: 2]
        {"comment": "Cau hoi test dau vao, sinh boi Generator A"},  # [cite: 2]
    )

    id = Column(
        BIGINT, primary_key=True, autoincrement=True, nullable=False
    )  # [cite: 2]
    question = Column(LONGTEXT, nullable=False)  # [cite: 2]
    created_at = Column(DateTime, nullable=False)  # [cite: 2]
    skill = Column(
        String(45),
        nullable=False,
        comment="v2.1 tag: D_doc | C_comm | T_trouble | G_custom",
    )  # [cite: 2]
    level = Column(String(45), nullable=False, comment="Easy|Medium|Hard|Expert")  # [cite: 2]
    expanded_skill = Column(
        String(45),
        nullable=True,
        comment="Context_layer|Language_layer",
    )  # [cite: 2]
    job_role_id = Column(
        BIGINT,
        ForeignKey("job_role.id", ondelete="NO ACTION", onupdate="NO ACTION"),
        nullable=False,
    )  # [cite: 2]
