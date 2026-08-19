from datetime import date, timedelta
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.roadmap import lesson_is_assigned
from app.core.security import get_password_hash, verify_password, create_access_token
from app.feature.auth.auth_schema import (
    LoginResponse,
    StudySettingsUpdateRequest,
    UserCreate,
    UserProfileResponse,
    UserResponse,
)
from app.models.lesson import Lesson
from app.models.user import User
from app.models.user_lesson import UserLesson
from app.models.user_radar_score import UserRadarScore
from app.models.user_roadmap import UserRoadmap

router = APIRouter()
DEFAULT_DAILY_STUDY_MINUTES = 120
SKILL_KEYS = ("D_doc", "C_comm", "T_trouble", "G_custom")


def _coerce_skill_percent(value: object) -> int:
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return 0

    if numeric_value <= 1:
        numeric_value *= 100

    return max(0, min(100, round(numeric_value)))


def _normalize_skill_vector(value: object | None) -> dict[str, int] | None:
    if value is None:
        return None

    if isinstance(value, dict):
        if not any(skill in value for skill in SKILL_KEYS):
            return None
        return {
            skill: _coerce_skill_percent(value.get(skill, 0))
            for skill in SKILL_KEYS
        }

    if isinstance(value, (list, tuple)):
        return {
            skill: _coerce_skill_percent(value[index]) if index < len(value) else 0
            for index, skill in enumerate(SKILL_KEYS)
        }

    return None


def _build_skill_score_snapshots(
    db: Session,
    user_id: int,
) -> tuple[dict[str, int] | None, dict[str, int] | None]:
    vector_row = (
        db.query(UserRadarScore)
        .filter(UserRadarScore.user_id == user_id)
        .order_by(UserRadarScore.updated_at.desc(), UserRadarScore.id.desc())
        .first()
    )

    if vector_row is None:
        return None, None

    initial_scores = _normalize_skill_vector(vector_row.start_vector)
    current_scores = (
        _normalize_skill_vector(vector_row.current_vector) or initial_scores
    )

    return initial_scores, current_scores


def _build_study_history(db: Session, user_id: int) -> tuple[int, list[dict[str, object]]]:
    completed_lessons = (
        db.query(UserLesson.completed_at, Lesson.estimated_minutes)
        .join(Lesson, Lesson.id == UserLesson.lesson_id)
        .filter(
            UserLesson.user_id == user_id,
            UserLesson.status == "completed",
            UserLesson.completed_at.isnot(None),
        )
        .all()
    )

    total_studied_minutes = 0
    monthly_minutes: dict[date, int] = {}
    today = date.today()

    for completed_at, estimated_minutes in completed_lessons:
        minutes = max(0, estimated_minutes or 0)
        if minutes <= 0 or completed_at is None:
            continue

        total_studied_minutes += minutes
        completed_on = completed_at.date()

        if completed_on.year == today.year and completed_on.month == today.month:
            monthly_minutes[completed_on] = monthly_minutes.get(completed_on, 0) + minutes

    study_history = [
        {"studied_on": studied_on, "minutes": minutes}
        for studied_on, minutes in sorted(monthly_minutes.items())
    ]

    return total_studied_minutes, study_history


def _build_user_profile_response(db: Session, user: User) -> UserProfileResponse:
    roadmap_rows = (
        db.query(UserRoadmap)
        .filter(UserRoadmap.user_id == user.id)
        .order_by(UserRoadmap.created_at.asc(), UserRoadmap.sort_order.asc())
        .all()
    )

    started_at = user.created_at
    total_estimated_minutes = 0

    if roadmap_rows:
        started_at = roadmap_rows[0].created_at or user.created_at
        track = roadmap_rows[0].track
        topic_ids = [row.topic_id for row in roadmap_rows]
        assigned_lessons = (
            db.query(Lesson)
            .filter(Lesson.topic_id.in_(topic_ids))
            .order_by(Lesson.id.asc())
            .all()
        )
        total_estimated_minutes = sum(
            lesson.estimated_minutes or 0
            for lesson in assigned_lessons
            if lesson_is_assigned(track, lesson.difficulty_tier)
        )

    daily_study_minutes = user.daily_study_minutes or DEFAULT_DAILY_STUDY_MINUTES
    total_studied_minutes, study_history = _build_study_history(db, user.id)
    initial_skill_scores, current_skill_scores = _build_skill_score_snapshots(
        db,
        user.id,
    )
    estimated_finish = None
    if total_estimated_minutes > 0:
        days_needed = max(1, ceil(total_estimated_minutes / daily_study_minutes))
        estimated_finish = date.today() + timedelta(days=days_needed - 1)

    return UserProfileResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        role_id=user.role_id,
        created_at=user.created_at,
        started_at=started_at,
        estimated_finish=estimated_finish,
        total_estimated_minutes=total_estimated_minutes,
        daily_study_minutes=daily_study_minutes,
        total_studied_minutes=total_studied_minutes,
        study_history=study_history,
        initial_skill_scores=initial_skill_scores,
        current_skill_scores=current_skill_scores,
    )


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    # 1. Kiểm tra xem email đã tồn tại trong Database chưa
    user_exists = db.query(User).filter(User.email == user_in.email).first()
    if user_exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email đã được đăng ký."
        )

    # 2. Băm mật khẩu và tạo bản ghi mới
    hashed_pwd = get_password_hash(user_in.password)
    new_user = User(email=user_in.email, name=user_in.name, hashed_password=hashed_pwd, role_id=1)

    # 3. Lưu xuống Database
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return new_user


# Đã thay đổi UserLogin thành OAuth2PasswordRequestForm
@router.post("/login", response_model=LoginResponse)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    # 1. Tìm user theo email
    # Swagger sẽ gửi email vào trường form_data.username
    user = db.query(User).filter(
        (User.email == form_data.username) | (User.name == form_data.username)
    ).first()

    # 2. Kiểm tra user có tồn tại và mật khẩu có khớp không
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email hoặc mật khẩu không chính xác.",
        )

    # 3. Nếu đúng, tạo JWT Token chứa user_id (sub)
    access_token = create_access_token(data={"sub": str(user.id)})

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user.id,
        email=user.email,
        name=user.name,
        role_id=user.role_id,
    )


@router.get("/me", response_model=UserProfileResponse)
def get_user_profile(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    API này yêu cầu phải có Token hợp lệ.
    Nếu Token đúng, nó sẽ trả về thông tin của chính user đó.
    """
    return _build_user_profile_response(db, current_user)


@router.patch("/me/study-settings", response_model=UserProfileResponse)
def update_study_settings(
    payload: StudySettingsUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.daily_study_minutes = payload.daily_study_minutes
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return _build_user_profile_response(db, current_user)
