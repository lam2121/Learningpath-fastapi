from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import app_config
from app.core.database import get_db
from app.core.dependencies import get_current_user_optional
from app.feature.onboarding.placement_test_schema import (
    CompletePlacementTestRequest,
    CompletePlacementTestResponse,
    OnboardingStatusResponse,
    PlacementResultResponse,
    PlacementTestQuestionResponse,
)
from app.feature.onboarding.placement_test_service import (
    complete_placement_test,
    fetch_questions_by_role,
    get_placement_test_result,
    get_user_roadmap,
    recompute_roadmap,
)
from app.feature.onboarding.roadmap_schema import (
    LessonGenerateResponse,
    RoadmapResponse,
    RoadmapSelectRequest,
)
from app.models.job_role import JobRole
from app.models.lesson import Lesson
from app.models.user import User
from app.models.user_roadmap import UserRoadmap

router = APIRouter()


@router.get(
    "/status",
    response_model=OnboardingStatusResponse,
    status_code=status.HTTP_200_OK,
)
def get_onboarding_status(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Check whether the authenticated user has finished the placement test."""
    if not current_user:
        return OnboardingStatusResponse(user_id=0, learning_status="none")

    return OnboardingStatusResponse(
        user_id=current_user.id,
        learning_status=getattr(current_user, "learning_status", "none"),
    )


@router.post(
    "/placement-test/complete",
    response_model=CompletePlacementTestResponse,
    status_code=status.HTTP_200_OK,
)
def finalize_placement_test(
    request: CompletePlacementTestRequest,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Finalize onboarding: save placement test answers, set user role_id,
    and set learning_status = 'enrolled'.
    """
    try:
        if current_user:
            user_id = current_user.id
        elif request.user_id:
            user_id = request.user_id
        else:
            fallback_user = db.query(User).first()
            if not fallback_user:
                raise ValueError(
                    "No user found in database for placement test fallback"
                )
            user_id = fallback_user.id

        complete_placement_test(
            db,
            user_id=user_id,
            role_id=request.role_id,
            placement_test_answers=request.placement_test_answers,
        )
        return CompletePlacementTestResponse(
            message="Placement test completed and onboarding saved successfully",
            learning_status="enrolled",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to finalize placement test: {e!s}",
        )


@router.get(
    "/placement-test/questions",
    response_model=list[PlacementTestQuestionResponse],
    status_code=status.HTTP_200_OK,
)
def get_placement_test_questions(
    role_id: int = Query(..., description="job_role_id to filter questions"),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Return all placement_test_question rows for the given job_role_id.
    The frontend adaptive engine picks questions from this pool.
    Returns an empty list if no questions exist for the role.

    Deactivated tracks block NEW learners (a user not already assigned to the
    role), while existing learners on the track can still load their questions.
    """
    role = db.query(JobRole).filter(JobRole.id == role_id).first()
    if (
        role is not None
        and not role.is_active
        and (current_user is None or current_user.job_role_id != role_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Career track '{role.name}' is deactivated and is not accepting "
                "new learners. Please select an active track or contact your "
                "administrator."
            ),
        )

    try:
        return fetch_questions_by_role(db, role_id=role_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch placement test questions: {e!s}",
        )


@router.get(
    "/placement-test/result",
    response_model=PlacementResultResponse,
    status_code=status.HTTP_200_OK,
)
def get_placement_test_result_endpoint(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Fetch the current user's placement test result (scores, starting level, per-question detail).
    Returns a response with learning_status='none' if no result exists.
    """
    # Resolve user_id: current_user -> fallback to first user (mirrors POST path)
    if current_user:
        user_id = current_user.id
    else:
        fallback_user = db.query(User).first()
        if not fallback_user:
            return PlacementResultResponse(
                learning_status="none",
                total_questions=0,
                total_correct=0,
                overall_percent=0,
                skill_scores={},
                starting_level="basic",
                weak_skills=[],
                answers=[],
            )
        user_id = fallback_user.id

    return get_placement_test_result(db, user_id=user_id)


# ─── Phase A: zero-AI roadmap (spec §2.C) ────────────────────────────────────


def _resolve_user_id(db: Session, current_user: User | None) -> int:
    """Resolve user_id from the session, mirroring the POST/GET fallback."""
    if current_user:
        return current_user.id
    fallback_user = db.query(User).first()
    if not fallback_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authenticated user and no fallback user in the database",
        )
    return fallback_user.id


@router.get(
    "/roadmap",
    response_model=RoadmapResponse,
    status_code=status.HTTP_200_OK,
)
def get_roadmap(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Fetch the current user's 8-topic roadmap (track + topics with lessons inline
    + assigned-lesson counts). Auto-computes the roadmap when it is empty.
    """
    user_id = _resolve_user_id(db, current_user)
    return get_user_roadmap(db, user_id)


@router.post(
    "/roadmap/select",
    response_model=RoadmapResponse,
    status_code=status.HTTP_200_OK,
)
def select_roadmap_endpoint(
    request: RoadmapSelectRequest,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Force-recompute the roadmap (idempotent delete+insert).

    - Without `skills`: recomputes from the user's stored placement answers.
    - With `skills` (dev-mode, §12.9): `fraction = value / 12` -> classify ->
      select, skipping placement answers. Returns 404 when APP_ENV=production.
    """
    user_id = _resolve_user_id(db, current_user)
    return recompute_roadmap(
        db, user_id, skills=request.skills, role_id=request.role_id
    )


@router.post(
    "/roadmap/lessons/{lesson_id}/generate",
    response_model=LessonGenerateResponse,
    status_code=status.HTTP_200_OK,
)
async def generate_roadmap_lesson(
    lesson_id: int,
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Dev-mode (synchronous) C-1 + C-2 generation for one roadmap lesson
    (§12.9). The lesson must belong to a topic in the caller's roadmap.
    Dev-gated: returns 404 in production (can graduate to the real study flow).
    """
    if app_config.APP_ENV == "production":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dev-mode lesson generation is disabled in production",
        )

    user_id = _resolve_user_id(db, current_user)

    lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if lesson is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found"
        )

    owned = (
        db.query(UserRoadmap)
        .filter(
            UserRoadmap.user_id == user_id,
            UserRoadmap.topic_id == lesson.topic_id,
        )
        .first()
    )
    if owned is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Lesson does not belong to your roadmap",
        )

    from app.core.ai.generation import generate_lesson_content

    result = await generate_lesson_content(lesson_id, force=force)
    return LessonGenerateResponse(
        lesson_id=lesson_id,
        status=result.get("status", "failed"),
        message=result.get("message") or result.get("error") or "unknown",
    )
