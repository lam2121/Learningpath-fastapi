"""FastAPI routes for curriculum roadmap, lesson generation kickoff, and SSE notification streaming."""

import asyncio
import json

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.infra.config import app_config
from app.core.infra.database import get_db
from app.core.infra.dependencies import (
    get_current_user,
    get_current_user_optional,
    get_user_from_access_token,
)
from app.core.infra.limiter import limiter
from app.core.infra.notification_stream import notification_stream_broker
from app.core.domain.roadmap import lesson_is_assigned
from app.feature.roadmap.roadmap_schema import (
    LessonGenerateResponse,
    RoadmapLessonResponse,
    RoadmapResponse,
    RoadmapSelectRequest,
)
from app.feature.roadmap.roadmap_service import (
    get_user_roadmap,
    lesson_is_unlocked_for_user,
    recompute_roadmap,
    sanitize_quiz_content_for_client,
)
from app.models.lesson import Lesson
from app.models.user import ADMIN_ROLE_ID, User
from app.models.user_roadmap import UserRoadmap

from app.models.user_lesson import UserLesson

router = APIRouter()


def _format_sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"

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
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Fetch the current user's 8-topic roadmap (track + topics with lessons inline
    + assigned-lesson counts). Auto-computes the roadmap when it is empty.
    """
    user_id = _resolve_user_id(db, current_user)
    roadmap = get_user_roadmap(db, user_id)
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
                    payload = await asyncio.wait_for(
                        queue.get(),
                        timeout=app_config.SSE_NOTIFICATION_TIMEOUT_SECONDS,
                    )
                    event_type = payload.get("type", "roadmap_updated") if isinstance(payload, dict) else "roadmap_updated"
                    yield _format_sse(event_type, payload)
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


@router.post("/roadmap/notifications/clear", status_code=status.HTTP_200_OK)
def clear_user_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Purge all pending live notification messages for the user."""
    cleared_count = notification_stream_broker.drain_user_queues(current_user.id)
    return {"message": "Notifications cleared", "cleared_count": cleared_count}


@router.post(
    "/roadmap/select",
    response_model=RoadmapResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("10/minute")
def select_roadmap_endpoint(
    request: Request,                # Cho SlowAPI rate limit
    payload: RoadmapSelectRequest,   # Cho FastAPI parse body JSON
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    user_id = _resolve_user_id(db, current_user)
    roadmap = recompute_roadmap(
        db, user_id, skills=payload.skills, role_id=payload.role_id
    )
    return roadmap

@router.get(
    "/roadmap/lessons/{lesson_id}",
    response_model=RoadmapLessonResponse,
    status_code=status.HTTP_200_OK,
)
def get_roadmap_lesson(
    lesson_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Load the content of one roadmap lesson on demand.
    The roadmap list endpoint intentionally does not include theory/quiz content.
    """
    user_id = _resolve_user_id(db, current_user)

    lesson = _get_owned_assigned_lesson(db, user_id, lesson_id)
    _require_unlocked_lesson(db, user_id, lesson)

    return RoadmapLessonResponse(
        id=lesson.id,
        title=lesson.title,
        primary_skill=lesson.primary_skill,
        difficulty_tier=lesson.difficulty_tier,
        estimated_minutes=lesson.estimated_minutes,
        is_generated=lesson.is_generated,
        is_unlocked=True,
        is_completed=(
            db.query(UserLesson)
            .filter(
                UserLesson.user_id == user_id,
                UserLesson.lesson_id == lesson.id,
                UserLesson.completed_at.isnot(None),
            )
            .first()
            is not None
        ),
        theory_content=lesson.theory_content if lesson.is_generated == 1 else None,
        quiz_content=(
            sanitize_quiz_content_for_client(lesson.quiz_content)
            if lesson.is_generated == 1
            else None
        ),
    )

@router.post(
    "/roadmap/lessons/{lesson_id}/generate",
    response_model=LessonGenerateResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("10/minute")
async def generate_roadmap_lesson(
    request: Request,
    lesson_id: int,
    background_tasks: BackgroundTasks,
    force: bool = Query(default=False),
    sync: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Kick off C-1 + C-2 generation for one roadmap lesson that belongs
    to the caller's roadmap. If sync=True, awaits generation and returns completed/failed.
    """
    user_id = _resolve_user_id(db, current_user)
    is_admin = bool(current_user and current_user.role_id == ADMIN_ROLE_ID)

    if force and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can force regenerate lesson content.",
        )

    if sync and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Synchronous lesson generation is reserved for administrators.",
        )

    if is_admin:
        lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
        if lesson is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Lesson not found"
            )
    else:
        lesson = _get_owned_assigned_lesson(db, user_id, lesson_id)

    from app.core.ai.dispatch.validators import validate_theory_content

    is_valid_structure = False
    if lesson.is_generated == 1 and isinstance(lesson.theory_content, dict):
        val_res = validate_theory_content(lesson.theory_content)
        if val_res.get("ok"):
            is_valid_structure = True

    if lesson.is_generated == 1 and is_valid_structure and lesson.quiz_content and not force:
        return LessonGenerateResponse(
            lesson_id=lesson_id,
            status="completed",
            message="Lesson already generated and ready to study",
        )

    from app.core.ai.dispatch.generation import generate_lesson_content
    from app.feature.admin import admin_service

    if sync:
        # Release the request's DB session connection back to the pool
        # before awaiting the long-running LLM generation call.
        db.close()
        res = await generate_lesson_content(lesson_id, force=force)
        res_status = res.get("status", "completed")
        if res_status == "failed":
            res_msg = "Lesson generation failed. Please try again later."
        else:
            res_msg = res.get("message") or "Lesson generation finished"
        return LessonGenerateResponse(
            lesson_id=lesson_id,
            status=res_status,
            message=res_msg,
        )

    info = admin_service.kickoff_lesson_generation(db, lesson_id, force=force)
    background_tasks.add_task(generate_lesson_content, lesson_id, force=force)
    return LessonGenerateResponse(
        lesson_id=lesson_id,
        status="started",
        message=info["message"],
    )
