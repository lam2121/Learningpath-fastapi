import json
from copy import deepcopy
from typing import Any

from sqlalchemy import JSON, Boolean, Column, ForeignKey, String
from sqlalchemy.dialects.mysql import BIGINT, LONGTEXT

from app.core.infra.database import Base


def get_job_description_text(desc: Any, lang: str = "en") -> str:
    """Extract a language-specific job description string from str or dict."""
    if not desc:
        return ""
    if isinstance(desc, dict):
        normalized = "jp" if lang in ("jp", "ja") else ("vi" if lang == "vi" else "en")
        return str(desc.get(normalized) or desc.get("en") or next(iter(desc.values()), "")).strip()
    if isinstance(desc, str):
        v = desc.strip()
        if v.startswith("{") and v.endswith("}"):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    normalized = "jp" if lang in ("jp", "ja") else ("vi" if lang == "vi" else "en")
                    return str(parsed.get(normalized) or parsed.get("en") or next(iter(parsed.values()), "")).strip()
            except Exception:
                pass
        return v
    return str(desc).strip()


def get_job_description_dict(desc: Any, fallback: bool = True) -> dict[str, str]:
    """Ensure a job description is returned as a {'en': ..., 'vi': ..., 'jp': ...} dict."""
    if not desc:
        return {"en": "", "vi": "", "jp": ""}
    if isinstance(desc, dict):
        en = str(desc.get("en", "")).strip()
        vi = str(desc.get("vi", "")).strip()
        jp = str(desc.get("jp", "")).strip()
        if fallback:
            vi = vi or en
            jp = jp or en
        return {"en": en, "vi": vi, "jp": jp}
    if isinstance(desc, str):
        v = desc.strip()
        if v.startswith("{") and v.endswith("}"):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    en = str(parsed.get("en", "")).strip()
                    vi = str(parsed.get("vi", "")).strip()
                    jp = str(parsed.get("jp", "")).strip()
                    if fallback:
                        vi = vi or en
                        jp = jp or en
                    return {"en": en, "vi": vi, "jp": jp}
            except Exception:
                pass
        return {"en": v, "vi": v if fallback else "", "jp": v if fallback else ""}
    s = str(desc).strip()
    return {"en": s, "vi": s if fallback else "", "jp": s if fallback else ""}

DEFAULT_BASELINE = {
    "D_doc": 25,
    "C_comm": 25,
    "T_trouble": 25,
    "G_custom": 25,
}

DEFAULT_SKILL_DESCRIPTIONS = {
    "D_doc": {
        "en": "Ability to read and write clear, concise, and structured technical documentation.",
        "vi": "Khả năng đọc và viết tài liệu kỹ thuật rõ ràng, súc tích và có cấu trúc.",
        "jp": "明確で簡潔、かつ構造化された技術ドキュメントの作成・読解能力。",
    },
    "C_comm": {
        "en": "Effective verbal and written communication in professional IT contexts.",
        "vi": "Kỹ năng giao tiếp bằng văn bản và lời nói hiệu quả trong môi trường IT chuyên nghiệp.",
        "jp": "ITの専門的な現場における、効果的な口頭および書面でのコミュニケーション能力。",
    },
    "T_trouble": {
        "en": "Skills in identifying, analyzing, and resolving technical issues.",
        "vi": "Kỹ năng xác định, phân tích và giải quyết các vấn đề kỹ thuật.",
        "jp": "技術的な課題を特定、分析、解決するスキル。",
    },
    "G_custom": {
        "en": "Specific domain knowledge and expertise required for this role.",
        "vi": "Kiến thức và chuyên môn sâu theo lĩnh vực yêu cầu cho vai trò này.",
        "jp": "この役職に求められる専門知識および特定分野のスキル。",
    },
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

    @property
    def job_description_en(self) -> str:
        return get_job_description_text(self.job_description, "en")

    def get_job_description(self, lang: str = "en") -> str:
        return get_job_description_text(self.job_description, lang)
