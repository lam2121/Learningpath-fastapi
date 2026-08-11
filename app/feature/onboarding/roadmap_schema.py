"""Pydantic schemas for the user roadmap (Phase A, §12.3 / §12.9)."""

from typing import Any

from pydantic import BaseModel, Field

SKILL_KEYS = ("D_doc", "C_comm", "T_trouble", "G_custom")


class RoadmapLessonResponse(BaseModel):
    id: int
    title: str
    primary_skill: str
    difficulty_tier: str
    is_generated: bool
    theory_content: Any | None = None
    quiz_content: Any | None = None


class RoadmapTopicResponse(BaseModel):
    id: int
    name: str
    primary_skill: str
    seed_tier: str
    sort_order: int
    lessons: list[RoadmapLessonResponse] = []


class RoadmapResponse(BaseModel):
    track: str
    topics: list[RoadmapTopicResponse]
    assigned_lessons: dict[str, int] = {}


class SkillOverrideRequest(BaseModel):
    """Dev-mode skill-score override (0-12 each, §12.9)."""

    D_doc: int = Field(ge=0, le=12)
    C_comm: int = Field(ge=0, le=12)
    T_trouble: int = Field(ge=0, le=12)
    G_custom: int = Field(ge=0, le=12)

    def as_fractions(self) -> dict[str, float]:
        """Convert the 0-12 slider values to correct/12 fractions."""
        return {key: self.model_dump()[key] / 12.0 for key in SKILL_KEYS}


class RoadmapSelectRequest(BaseModel):
    """Force-recompute the roadmap. `skills` is the dev-mode override."""

    role_id: int | None = None
    skills: SkillOverrideRequest | None = None


class LessonGenerateResponse(BaseModel):
    lesson_id: int
    status: str
    message: str
