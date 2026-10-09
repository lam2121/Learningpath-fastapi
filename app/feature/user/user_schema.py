from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    name: str
    role_id: int | None = None
    avatar_url: str | None = None
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


class TopicQuizHistoryEntryResponse(BaseModel):
    topic_id: int
    topic_name: str
    topic_sort_order: int | None = None
    status: str
    best_score_percent: float | None = None
    passed: bool = False
    attempt_count: int = 0
    failed_attempts: int = 0
    correct_count: int = 0
    total_questions: int = 0
    recorded_at: datetime | None = None
    completed_at: datetime | None = None


class FinalQuizHistoryEntryResponse(BaseModel):
    job_role_id: int
    role_name: str
    status: str
    best_score_percent: float | None = None
    passed: bool = False
    progress: float = 0.0
    attempt_count: int = 0
    failed_attempts: int = 0
    correct_count: int = 0
    total_questions: int = 0
    skill_scores: dict[str, float] | None = None
    unlocked_at: datetime | None = None
    completed_at: datetime | None = None
    recorded_at: datetime | None = None


class UserProfileResponse(UserResponse):
    started_at: datetime | None = None
    estimated_finish: date | None = None
    total_estimated_minutes: int = 0
    daily_study_minutes: int = 120
    total_studied_minutes: int = 0
    study_history: list[StudyHistoryEntryResponse] = []
    lesson_quiz_history: list[LessonQuizHistoryEntryResponse] = []
    topic_quiz_history: list[TopicQuizHistoryEntryResponse] = []
    final_quiz_history: list[FinalQuizHistoryEntryResponse] = []
    initial_skill_scores: dict[str, float] | None = None
    current_skill_scores: dict[str, float] | None = None
    quiz_review_count: int = 0


class StudySettingsUpdateRequest(BaseModel):
    daily_study_minutes: int = Field(ge=5, le=360, multiple_of=5)


class AICoachMessageRequest(BaseModel):
    day_streak: int
    lesson_learner: int
    total_lesson_in_track: int
    accuracy: float
    daily_study_per_day: int


class AICoachMessageResponse(BaseModel):
    feedback_summary: str


class QuizReviewQuestionItem(BaseModel):
    review_id: int
    lesson_id: int
    lesson_title: str
    question_id: str
    question_type: str
    stem: str
    options: list[str] = []
    explanation: str = ""
    wrong_count: int = 1


class QuizReviewListResponse(BaseModel):
    total_count: int
    review_questions: list[QuizReviewQuestionItem] = []


class QuizReviewAnswerItem(BaseModel):
    review_id: int
    answer: str = Field(..., max_length=1000)


class QuizReviewSubmitRequest(BaseModel):
    answers: list[QuizReviewAnswerItem]


class QuizReviewItemResult(BaseModel):
    review_id: int
    question_id: str
    question_type: str
    stem: str
    options: list[str] = []
    user_answer: str
    correct_answer: str
    explanation: str
    is_correct: bool
    removed: bool


class QuizReviewSubmitResponse(BaseModel):
    results: list[QuizReviewItemResult]
    cleared_count: int
    failed_count: int
    total_reviewed: int
    remaining_count: int


class StreakRestoreRequest(BaseModel):
    dates: list[str] = Field(..., min_length=1, max_length=30)
    client_study_minutes: int | None = Field(default=None, ge=0)


class StreakStatusResponse(BaseModel):
    total_studied_minutes: int
    required_minutes_per_day: int
    total_earned_credits: int
    used_credits: int
    available_credits: int
    progress_minutes: int
    progress_percent: float
    restored_dates: list[str] = []
    current_streak: int = 0
    longest_streak: int = 0



