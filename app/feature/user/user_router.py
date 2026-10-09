"""FastAPI routes for user profile, study settings, track reset, and quiz reviews.

Business logic has been extracted to:
  - user_service.py: Profile building, quiz histories, career track reset, AI coach
  - user_serializers.py: Normalization, attempt parsing, hint metrics
  - quiz_review_service.py: Review queue management and submission
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.infra.config import app_config
from app.core.infra.database import get_db
from app.core.infra.dependencies import get_current_user
from app.core.infra.limiter import limiter
from app.feature.user.quiz_review_service import (
    get_user_quiz_review_items,
    submit_user_quiz_review,
)
from app.feature.user.user_schema import (
    AICoachMessageRequest,
    AICoachMessageResponse,
    QuizReviewListResponse,
    QuizReviewSubmitRequest,
    QuizReviewSubmitResponse,
    StreakRestoreRequest,
    StreakStatusResponse,
    StudySettingsUpdateRequest,
    UserProfileResponse,
)
from app.feature.user.user_serializers import (  # noqa: F401
    SKILL_KEYS,
    _coerce_json_object,
    _coerce_skill_percent,
    _compute_hint_breakdown,
    _derive_lesson_quiz_status,
    _extract_attempt_score,
    _extract_best_passing_attempt,
    _extract_best_passing_score,
    _extract_latest_attempt,
    _extract_question_results,
    _is_attempt_snapshot,
    _is_passing_attempt_snapshot,
    _normalize_skill_vector,
    _parse_iso_datetime,
)
from app.feature.user.user_service import (  # noqa: F401
    DEFAULT_DAILY_STUDY_MINUTES,
    _build_final_quiz_history,
    _build_lesson_quiz_history,
    _build_skill_score_snapshots,
    _build_study_history,
    _build_topic_quiz_history,
    _build_user_profile_response,
    _reset_user_career_track,
    build_user_profile_response,
    generate_ai_coach_message_service,
    get_user_streak_status,
    reset_user_career_track,
    restore_user_streak,
)
from app.models.user import User

router = APIRouter()

# Avatar upload configuration
AVATAR_UPLOAD_DIR = app_config.RESOLVED_STATIC_DIR / "uploads" / "avatars"
AVATAR_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_IMAGE_TYPES = app_config.ALLOWED_IMAGE_TYPES_SET
MAX_AVATAR_SIZE_BYTES = app_config.MAX_AVATAR_SIZE_BYTES


@router.get("/me", response_model=UserProfileResponse)
def get_user_profile(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return build_user_profile_response(db, current_user)


@router.get("/me/streak", response_model=StreakStatusResponse)
@limiter.limit("60/minute")
def get_user_streak(
    request: Request,
    client_study_minutes: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve current user's streak and restoration credit status."""
    return get_user_streak_status(db, current_user, client_study_minutes)


@router.post("/me/streak/restore", response_model=StreakStatusResponse)
@limiter.limit("30/minute")
def restore_streak(
    request: Request,
    payload: StreakRestoreRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Restore missed streak day(s) by spending accumulated 120-minute study credits."""
    return restore_user_streak(
        db,
        current_user,
        dates=payload.dates,
        client_study_minutes=payload.client_study_minutes,
    )



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
    return build_user_profile_response(db, current_user)


@router.delete("/me/career-track", status_code=status.HTTP_204_NO_CONTENT)
def delete_career_track(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reset_user_career_track(db, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/me/avatar", response_model=UserProfileResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload or replace the user's profile avatar image.

    Accepts JPEG, PNG, or WebP images up to 5 MB. The file is saved to disk
    and the relative path is stored in the user record.
    """
    # Validate content type
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid image type '{file.content_type}'. Allowed: JPEG, PNG, WebP.",
        )

    # Read and validate file size
    contents = await file.read()
    if len(contents) > MAX_AVATAR_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image too large ({len(contents)} bytes). Maximum is {MAX_AVATAR_SIZE_BYTES} bytes (5 MB).",
        )

    # Determine file extension from content type
    ext_map = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    ext = ext_map.get(file.content_type, ".jpg")

    # Generate unique filename: {user_id}_{uuid}{ext}
    filename = f"{current_user.id}_{uuid.uuid4().hex[:12]}{ext}"
    filepath = AVATAR_UPLOAD_DIR / filename

    # Delete old avatar file if it exists
    if current_user.avatar_path:
        old_file = app_config.RESOLVED_STATIC_DIR / "uploads" / current_user.avatar_path
        if old_file.exists():
            try:
                old_file.unlink()
            except OSError:
                pass  # Best-effort cleanup

    # Write new file
    with open(filepath, "wb") as f:
        f.write(contents)

    # Update database
    current_user.avatar_path = f"avatars/{filename}"
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    return build_user_profile_response(db, current_user)


@router.delete("/me/avatar", status_code=status.HTTP_200_OK, response_model=UserProfileResponse)
def delete_avatar(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove the user's profile avatar and revert to the default."""
    if current_user.avatar_path:
        old_file = app_config.RESOLVED_STATIC_DIR / "uploads" / current_user.avatar_path
        if old_file.exists():
            try:
                old_file.unlink()
            except OSError:
                pass

    current_user.avatar_path = None
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    return build_user_profile_response(db, current_user)


@router.post("/me/ai-coach-message", response_model=AICoachMessageResponse)
@limiter.limit("15/minute")
async def generate_ai_coach_message(
    request: Request,
    payload: AICoachMessageRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ = current_user
    # Release DB connection back to the pool before awaiting long-running LLM generation
    db.close()
    return await generate_ai_coach_message_service(payload)


@router.get("/me/quiz-review", response_model=QuizReviewListResponse)
def get_my_quiz_review(
    limit: int = 5,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve up to 5 wrong questions from previous lesson quizzes for morning review."""
    return get_user_quiz_review_items(db, current_user.id, limit=limit)


@router.post("/me/quiz-review/submit", response_model=QuizReviewSubmitResponse)
def submit_my_quiz_review(
    payload: QuizReviewSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Submit answers for review questions. Correct answers are removed from Queue;

    incorrect answers remain for future review.
    """
    return submit_user_quiz_review(
        db,
        current_user.id,
        [answer.model_dump() for answer in payload.answers],
    )

