from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

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
)
from app.models.job_role import JobRole
from app.models.user import User

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
        return OnboardingStatusResponse(user_id=0, is_finished_placement_test=False)

    return OnboardingStatusResponse(
        user_id=current_user.id,
        is_finished_placement_test=bool(
            getattr(current_user, "is_finished_placement_test", False)
        ),
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
    and set is_finished_placement_test = 1.
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
            is_finished_placement_test=True,
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
    Returns a response with is_finished_placement_test=false if no result exists.
    """
    # Resolve user_id: current_user -> fallback to first user (mirrors POST path)
    if current_user:
        user_id = current_user.id
    else:
        fallback_user = db.query(User).first()
        if not fallback_user:
            return PlacementResultResponse(
                is_finished_placement_test=False,
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
