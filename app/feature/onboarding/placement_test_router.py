import asyncio
import json

from fastapi import Cookie, APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.dependencies import get_current_user_optional, get_user_from_access_token
from app.core.notification_stream import notification_stream_broker
from app.core.roadmap import lesson_is_assigned
from app.feature.onboarding.lesson_quiz_service import (
    evaluate_user_answer,
    get_lesson_quiz_result_detail,
    get_lesson_quiz_state,
    submit_lesson_quiz,
)
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
    get_first_assigned_lesson_ids,
    get_placement_test_result,
    get_user_roadmap,
    lesson_is_unlocked_for_user,
    recompute_roadmap,
)
from app.feature.onboarding.roadmap_schema import (
    EvaluateAnswerRequest,
    EvaluateAnswerResponse,
    LessonGenerateResponse,
    LessonQuizResultDetailResponse,
    LessonQuizStateResponse,
    LessonQuizSubmitRequest,
    LessonQuizSubmitResponse,
    RoadmapResponse,
    RoadmapSelectRequest,
)
from app.models.job_role import JobRole
from app.models.lesson import Lesson
from app.models.user import User
from app.models.user_roadmap import UserRoadmap

router = APIRouter()


def _format_sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _schedule_first_topic_lessons(
    background_tasks: BackgroundTasks,
    db: Session,
    user_id: int,
) -> None:
    from app.core.ai.generation import generate_lesson_content

    for lesson_id in get_first_assigned_lesson_ids(db, user_id):
        background_tasks.add_task(generate_lesson_content, lesson_id, force=False)


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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Finalize onboarding: save placement test answers, set user role_id,
    and set learning_status = 'enrolled'.
    """
    try:
        if not current_user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sign in is required before saving a placement test result.",
            )

        user_id = current_user.id

        complete_placement_test(
            db,
            user_id=user_id,
            role_id=request.role_id,
            placement_test_answers=request.placement_test_answers,
        )
        _schedule_first_topic_lessons(background_tasks, db, user_id)
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
    if not current_user:
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

    user_id = current_user.id

    return get_placement_test_result(db, user_id=user_id)


# ─── Phase A: zero-AI roadmap (spec §2.C) ────────────────────────────────────


def _resolve_user_id(db: Session, current_user: User | None) -> int:
    """Resolve user_id from current_user, strictly requiring authentication."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user.id


def _get_owned_assigned_lesson(db: Session, user_id: int, lesson_id: int) -> Lesson:
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
    if not lesson_is_assigned(owned.track, lesson.difficulty_tier):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Lesson is not assigned for your track",
        )
    return lesson


def _get_owned_assigned_track(db: Session, user_id: int, lesson: Lesson) -> str:
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
    return str(owned.track)


def _require_unlocked_lesson(
    db: Session,
    user_id: int,
    lesson: Lesson,
) -> None:
    track = _get_owned_assigned_track(db, user_id, lesson)
    if lesson_is_unlocked_for_user(db, user_id, lesson, track):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Pass the previous lesson in this topic to unlock this lesson.",
    )


@router.get(
    "/roadmap",
    response_model=RoadmapResponse,
    status_code=status.HTTP_200_OK,
)
def get_roadmap(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Fetch the current user's 8-topic roadmap (track + topics with lessons inline
    + assigned-lesson counts). Auto-computes the roadmap when it is empty.
    """
    user_id = _resolve_user_id(db, current_user)
    roadmap = get_user_roadmap(db, user_id)
    _schedule_first_topic_lessons(background_tasks, db, user_id)
    return roadmap


@router.get("/roadmap/notifications/stream", status_code=status.HTTP_200_OK)
async def stream_roadmap_notifications(
    access_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required for the notification stream.",
        )
    
    # Clean up token format if it includes the "Bearer " prefix
    token = access_token.replace("Bearer ", "") if access_token.startswith("Bearer ") else access_token

    user = get_user_from_access_token(token, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required for the notification stream.",
        )
        
    user_id = int(user.id)
    db.close()

    async def event_stream():
        queue = await notification_stream_broker.subscribe(user_id)
        try:
            yield _format_sse(
                "connected",
                {
                    "type": "connected",
                    "user_id": user_id,
                },
            )
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25)
                    yield _format_sse("roadmap_updated", payload)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            notification_stream_broker.unsubscribe(user_id, queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/roadmap/select",
    response_model=RoadmapResponse,
    status_code=status.HTTP_200_OK,
)
def select_roadmap_endpoint(
    request: RoadmapSelectRequest,
    background_tasks: BackgroundTasks,
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
    roadmap = recompute_roadmap(
        db, user_id, skills=request.skills, role_id=request.role_id
    )
    _schedule_first_topic_lessons(background_tasks, db, user_id)
    return roadmap


@router.post(
    "/roadmap/lessons/{lesson_id}/generate",
    response_model=LessonGenerateResponse,
    status_code=status.HTTP_200_OK,
)
async def generate_roadmap_lesson(
    lesson_id: int,
    background_tasks: BackgroundTasks,
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Kick off background C-1 + C-2 generation for one roadmap lesson that belongs
    to the caller's roadmap.
    """
    user_id = _resolve_user_id(db, current_user)

    lesson = _get_owned_assigned_lesson(db, user_id, lesson_id)

    if lesson.is_generated and not force:
        return LessonGenerateResponse(
            lesson_id=lesson_id,
            status="completed",
            message="Lesson already generated and ready to study",
        )

    from app.core.ai.generation import generate_lesson_content
    from app.feature.admin import admin_service

    info = admin_service.kickoff_lesson_generation(db, lesson_id, force=force)
    background_tasks.add_task(generate_lesson_content, lesson_id, force=force)
    return LessonGenerateResponse(
        lesson_id=lesson_id,
        status="started",
        message=info["message"],
    )


@router.get(
    "/roadmap/lessons/{lesson_id}/quiz",
    response_model=LessonQuizStateResponse,
    status_code=status.HTTP_200_OK,
)
def get_lesson_quiz_state_endpoint(
    lesson_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    user_id = _resolve_user_id(db, current_user)
    lesson = _get_owned_assigned_lesson(db, user_id, lesson_id)
    _require_unlocked_lesson(db, user_id, lesson)
    return get_lesson_quiz_state(db, user_id, lesson)


@router.post(
    "/roadmap/lessons/{lesson_id}/quiz/submit",
    response_model=LessonQuizSubmitResponse,
    status_code=status.HTTP_200_OK,
)
def submit_lesson_quiz_endpoint(
    lesson_id: int,
    request: LessonQuizSubmitRequest,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    user_id = _resolve_user_id(db, current_user)
    lesson = _get_owned_assigned_lesson(db, user_id, lesson_id)
    _require_unlocked_lesson(db, user_id, lesson)
    return submit_lesson_quiz(
        db,
        user_id,
        lesson,
        question_order=request.question_order,
        submitted_answers=[answer.model_dump() for answer in request.answers],
    )


@router.get(
    "/roadmap/lessons/{lesson_id}/quiz/result",
    response_model=LessonQuizResultDetailResponse,
    status_code=status.HTTP_200_OK,
)
def get_lesson_quiz_result_detail_endpoint(
    lesson_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    user_id = _resolve_user_id(db, current_user)
    lesson = _get_owned_assigned_lesson(db, user_id, lesson_id)
    _require_unlocked_lesson(db, user_id, lesson)
    return get_lesson_quiz_result_detail(db, user_id, lesson)


@router.post(
    "/roadmap/evaluate-answer",
    response_model=EvaluateAnswerResponse,
    status_code=status.HTTP_200_OK,
)
async def evaluate_answer_endpoint(
    request: EvaluateAnswerRequest,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Evaluate a user's free-text answer (for Reading, Dialogue, or Listening) using the AI.
    """
    try:
        feedback = await evaluate_user_answer(
            section_type=request.section_type,
            context=request.context,
            question=request.question,
            reference_answer=request.reference_answer,
            user_answer=request.user_answer,
        )
        return EvaluateAnswerResponse(feedback_summary=feedback)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Evaluation failed: {e}")
