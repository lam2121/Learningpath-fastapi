from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    name: str
    role_id: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class StudyHistoryEntryResponse(BaseModel):
    studied_on: date
    minutes: int = 0


class LessonQuizHistoryEntryResponse(BaseModel):
    lesson_id: int
    lesson_title: str
    topic_name: str | None = None
    topic_sort_order: int | None = None
    skill: str
    difficulty_tier: str
    status: str
    best_score_percent: float | None = None
    passed: bool = False
    attempt_count: int = 0
    failed_attempts: int = 0
    correct_no_hint_count: int = 0
    total_no_hint_questions: int = 0
    correct_with_hint_count: int = 0
    total_with_hint_questions: int = 0
    total_questions: int = 0
    recorded_at: datetime | None = None
    completed_at: datetime | None = None
    last_submitted_at: datetime | None = None


class UserProfileResponse(UserResponse):
    started_at: datetime | None = None
    estimated_finish: date | None = None
    total_estimated_minutes: int = 0
    daily_study_minutes: int = 120
    total_studied_minutes: int = 0
    study_history: list[StudyHistoryEntryResponse] = []
    lesson_quiz_history: list[LessonQuizHistoryEntryResponse] = []
    initial_skill_scores: dict[str, float] | None = None
    current_skill_scores: dict[str, float] | None = None


class StudySettingsUpdateRequest(BaseModel):
    daily_study_minutes: int = Field(ge=60, le=360, multiple_of=60)


class AICoachMessageRequest(BaseModel):
    day_streak: int
    lesson_learner: int
    total_lesson_in_track: int
    accuracy: float
    daily_study_per_day: int


class AICoachMessageResponse(BaseModel):
    feedback_summary: str

