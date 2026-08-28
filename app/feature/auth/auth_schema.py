from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field


# 1. Base Schema: Chứa các trường chung nhất
class UserBase(BaseModel):
    email: EmailStr
    name: str


# 2. Schema cho Đăng ký (Kế thừa từ Base và thêm password)
class UserCreate(UserBase):
    password: str = Field(
        ..., min_length=6, description="Mật khẩu phải có ít nhất 6 ký tự"
    )


# 3. Schema cho Đăng nhập
class UserLogin(BaseModel):
    email: EmailStr
    password: str


# 4. Schema trả về cho Client (Giấu hoàn toàn hashed_password)
class UserResponse(UserBase):
    id: int
    role_id: int | None = None
    created_at: datetime

    # Cấu hình này giúp Pydantic đọc được dữ liệu từ SQLAlchemy Model
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


# 5. Schema trả về từ login (token + user info)
class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    name: str
    role_id: int | None = None


class AICoachMessageRequest(BaseModel):
    day_streak: int
    lesson_learner: int
    total_lesson_in_track: int
    accuracy: float
    daily_study_per_day: int


class AICoachMessageResponse(BaseModel):
    feedback_summary: str
