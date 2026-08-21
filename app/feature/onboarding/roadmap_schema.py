"""Pydantic schemas for the user roadmap (Phase A, §12.3 / §12.9)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

SKILL_KEYS = ("D_doc", "C_comm", "T_trouble", "G_custom")


class RoadmapLessonResponse(BaseModel):
    id: int
    title: str
    primary_skill: str
    difficulty_tier: str
    estimated_minutes: int | None = None
    is_generated: bool
    is_unlocked: bool
    theory_content: Any | None = None
    quiz_content: Any | None = None


class RoadmapTopicResponse(BaseModel):
    id: int
    name: str
    primary_skill: str
    seed_tier: str
    sort_order: int
    total_estimated_minutes: int = 0
    lessons: list[RoadmapLessonResponse] = []


class RoadmapResponse(BaseModel):
    track: str
    topics: list[RoadmapTopicResponse]
    assigned_lessons: dict[str, int] = {}
    total_estimated_minutes: int = 0


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


class LessonQuizAnswerSubmission(BaseModel):
    question_id: str
    question_type: str
    answer: str = ""
    used_hint: bool = False


class LessonQuizSubmitRequest(BaseModel):
    question_order: list[str] = []
    answers: list[LessonQuizAnswerSubmission]


class LessonQuizQuestionResultResponse(BaseModel):
    question_id: str
    question_type: str
    question_text: str = ""
    options: list[str] = []
    user_answer: str
    correct_answer: str
    explanation: str
    is_correct: bool
    used_hint: bool


class LessonQuizStateResponse(BaseModel):
    lesson_id: int
    skill: str
    status: str
    lesson_passed: bool
    best_score_percent: float
    attempt_count: int
    failed_attempts: int
    completed_at: datetime | None = None
    current_skill_score: float | None = None
    first_pass_score_percent: float | None = None


class LessonQuizSavedAnswerResponse(BaseModel):
    question_id: str
    question_type: str
    answer: str
    used_hint: bool


class LessonQuizResultDetailResponse(BaseModel):
    lesson_id: int
    lesson_title: str
    topic_name: str | None = None
    skill: str
    difficulty_tier: str
    status: str
    best_score_percent: float | None = None
    attempt_count: int = 0
    failed_attempts: int = 0
    correct_no_hint_count: int = 0
    total_no_hint_questions: int = 0
    correct_with_hint_count: int = 0
    total_with_hint_questions: int = 0
    total_questions: int = 0
    recorded_at: datetime | None = None
    question_order: list[str] = []
    answers: list[LessonQuizSavedAnswerResponse] = []
    question_results: list[LessonQuizQuestionResultResponse] = []


class LessonQuizSubmitResponse(LessonQuizStateResponse):
    current_attempt_passed: bool
    weighted_score_percent: float
    correct_no_hint_count: int
    correct_with_hint_count: int
    total_questions: int
    first_pass_radar_applied: bool
    current_attempt_is_new_best: bool
    question_results: list[LessonQuizQuestionResultResponse]
