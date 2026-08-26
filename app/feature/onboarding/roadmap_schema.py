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


class SkillDifficultyBreakdown(BaseModel):
    """Per-skill correct-answer counts by difficulty tier (dev-mode, v3 scoring)."""

    easy: int = Field(ge=0, le=4, description="Correct answers on Easy questions (0-4)")
    medium: int = Field(ge=0, le=4, description="Correct answers on Medium questions (0-4)")
    hard: int = Field(ge=0, le=4, description="Correct answers on Hard questions (0-4)")

    def earned_weight(self) -> int:
        """Weighted sum: Easy×1 + Medium×2 + Hard×3."""
        return self.easy * 1 + self.medium * 2 + self.hard * 3


class DevPlacementOverrideRequest(BaseModel):
    """Dev-mode placement override: per-skill difficulty breakdown (v3 scoring)."""

    D_doc: SkillDifficultyBreakdown
    C_comm: SkillDifficultyBreakdown
    T_trouble: SkillDifficultyBreakdown
    G_custom: SkillDifficultyBreakdown

    def as_fractions(self) -> dict[str, float]:
        """Convert difficulty breakdowns to weighted-accuracy fractions (0.0-1.0).

        Fraction = earned_weight / MAX_SKILL_WEIGHT, clamped to [0, 1].
        """
        from app.feature.onboarding.placement_test_service import MAX_SKILL_WEIGHT

        result = {}
        for key in SKILL_KEYS:
            breakdown: SkillDifficultyBreakdown = getattr(self, key)
            result[key] = min(breakdown.earned_weight() / MAX_SKILL_WEIGHT, 1.0)
        return result


class RoadmapSelectRequest(BaseModel):
    """Force-recompute the roadmap. `skills` is the dev-mode override."""

    role_id: int | None = None
    skills: DevPlacementOverrideRequest | None = None


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

from typing import Literal

class EvaluateAnswerRequest(BaseModel):
    section_type: Literal["reading", "dialogue", "listening"]
    context: str
    question: str
    reference_answer: str
    user_answer: str

class EvaluateAnswerResponse(BaseModel):
    feedback_summary: str
