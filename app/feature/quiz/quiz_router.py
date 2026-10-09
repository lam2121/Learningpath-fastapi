"""FastAPI routes for Lesson Quizzes, Topic Quizzes, Final Exams, and AI evaluations."""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.infra.database import get_db
from app.core.infra.dependencies import get_current_user_optional
from app.core.infra.limiter import limiter
from app.feature.quiz.final_quiz_service import (
    get_final_quiz_state,
    get_or_create_final_quiz_questions,
    get_or_create_user_final_quiz,
    submit_final_quiz,
)
from app.feature.quiz.lesson_quiz_service import (
    evaluate_user_answer,
    get_lesson_quiz_hint,
    get_lesson_quiz_result_detail,
    get_lesson_quiz_state,
    submit_lesson_quiz,
)
from app.feature.roadmap.roadmap_router import (
    _get_owned_assigned_lesson,
    _require_unlocked_lesson,
    _resolve_user_id,
)
from app.feature.roadmap.roadmap_schema import (
    EvaluateAnswerRequest,
    EvaluateAnswerResponse,
    FinalQuizQuestionResponse,
    FinalQuizStateResponse,
    FinalQuizSubmitRequest,
    FinalQuizSubmitResponse,
    LessonQuizHintRequest,
    LessonQuizHintResponse,
    LessonQuizResultDetailResponse,
    LessonQuizStateResponse,
    LessonQuizSubmitRequest,
    LessonQuizSubmitResponse,
    TopicQuizQuestionResponse,
    TopicQuizStateResponse,
    TopicQuizSubmitRequest,
    TopicQuizSubmitResponse,
)
from app.feature.quiz.topic_quiz_service import (
    get_or_create_topic_quiz_questions,
    get_topic_quiz_state,
    submit_topic_quiz,
)
from app.models.user import User
from app.models.user_roadmap import UserRoadmap
from app.models.user_topic_quiz import UserTopicQuiz

router = APIRouter()


# ─── Lesson Quiz Endpoints ───────────────────────────────────────────────────


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
    "/roadmap/lessons/{lesson_id}/quiz/hint",
    response_model=LessonQuizHintResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("30/minute")
def get_lesson_quiz_hint_endpoint(
    request: Request,
    lesson_id: int,
    payload: LessonQuizHintRequest,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    user_id = _resolve_user_id(db, current_user)
    lesson = _get_owned_assigned_lesson(db, user_id, lesson_id)
    _require_unlocked_lesson(db, user_id, lesson)
    return get_lesson_quiz_hint(db, user_id, lesson, payload.question_id)


@router.post(
    "/roadmap/evaluate-answer",
    response_model=EvaluateAnswerResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("20/minute")
async def evaluate_answer_endpoint(
    request: Request,
    payload: EvaluateAnswerRequest,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    Evaluate a user's free-text answer (for Reading, Dialogue, or Listening) using the AI.
    """
    _resolve_user_id(db, current_user)
    # Release DB connection back to the pool before awaiting long-running LLM evaluation
    db.close()
    try:
        result = await evaluate_user_answer(
            section_type=payload.section_type,
            context=payload.context,
            question=payload.question,
            reference_answer=payload.reference_answer,
            user_answer=payload.user_answer,
        )
        if isinstance(result, dict):
            return EvaluateAnswerResponse(
                feedback_summary=result.get("feedback_summary", ""),
                score=result.get("score"),
            )
        return EvaluateAnswerResponse(feedback_summary=result)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Evaluation failed due to an internal error.")


# ─── Topic Quiz Endpoints (Spec §4.2, §4.4) ──────────────────────────────────


@router.get(
    "/topics/{topic_id}/quiz/state",
    response_model=TopicQuizStateResponse,
    status_code=status.HTTP_200_OK,
)
def get_topic_quiz_state_endpoint(
    topic_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    user_id = _resolve_user_id(db, current_user)
    return get_topic_quiz_state(db, user_id, topic_id)


@router.get(
    "/topics/{topic_id}/quiz/questions",
    response_model=list[TopicQuizQuestionResponse],
    status_code=status.HTTP_200_OK,
)
def get_topic_quiz_questions_endpoint(
    topic_id: int,
    new_attempt: bool = False,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    user_id = _resolve_user_id(db, current_user)
    return get_or_create_topic_quiz_questions(db, user_id, topic_id, force_new=new_attempt)


@router.post(
    "/topics/{topic_id}/quiz/submit",
    response_model=TopicQuizSubmitResponse,
    status_code=status.HTTP_200_OK,
)
def submit_topic_quiz_endpoint(
    topic_id: int,
    request: TopicQuizSubmitRequest,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    user_id = _resolve_user_id(db, current_user)
    return submit_topic_quiz(
        db,
        user_id,
        topic_id,
        submitted_answers=[ans.model_dump() for ans in request.answers],
    )


# ─── Final Quiz Endpoints ────────────────────────────────────────────────────


@router.get(
    "/final-quiz/state",
    response_model=FinalQuizStateResponse,
    status_code=status.HTTP_200_OK,
)
def get_final_quiz_state_endpoint(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    user_id = _resolve_user_id(db, current_user)
    return get_final_quiz_state(db, user_id)


@router.get(
    "/final-quiz/questions",
    response_model=list[FinalQuizQuestionResponse],
    status_code=status.HTTP_200_OK,
)
def get_final_quiz_questions_endpoint(
    new_attempt: bool = False,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    user_id = _resolve_user_id(db, current_user)
    return get_or_create_final_quiz_questions(db, user_id, force_new=new_attempt)


@router.post(
    "/final-quiz/submit",
    response_model=FinalQuizSubmitResponse,
    status_code=status.HTTP_200_OK,
)
def submit_final_quiz_endpoint(
    request: FinalQuizSubmitRequest,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    user_id = _resolve_user_id(db, current_user)
    return submit_final_quiz(
        db,
        user_id,
        submitted_answers=request.answers,
    )


@router.post(
    "/dev/unlock-final-quiz",
    status_code=status.HTTP_200_OK,
)
def dev_unlock_final_quiz_endpoint(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Dev helper to instantly mark all roadmap topic quizzes as passed."""
    user_id = _resolve_user_id(db, current_user)
    roadmap_topics = (
        db.query(UserRoadmap)
        .filter(UserRoadmap.user_id == user_id)
        .all()
    )
    for entry in roadmap_topics:
        tq = (
            db.query(UserTopicQuiz)
            .filter(
                UserTopicQuiz.user_id == user_id,
                UserTopicQuiz.topic_id == entry.topic_id,
            )
            .first()
        )
        if tq is None:
            tq = UserTopicQuiz(
                user_id=user_id,
                topic_id=entry.topic_id,
                status="passed",
                attempt_count=1,
                failed_attempts=0,
                best_score_percent=85.0,
                last_score_percent=85.0,
                completed_at=datetime.utcnow(),
            )
            db.add(tq)
        else:
            tq.status = "passed"
            tq.attempt_count = max(tq.attempt_count, 1)
            tq.best_score_percent = max(tq.best_score_percent or 0.0, 85.0)
            tq.last_score_percent = 85.0
            tq.completed_at = datetime.utcnow()

    user_course = get_or_create_user_final_quiz(db, user_id, create_if_missing=True)
    if user_course:
        user_course.status = "ready"
        if not user_course.unlocked_at:
            user_course.unlocked_at = datetime.utcnow()
        existing = user_course.user_answers if isinstance(user_course.user_answers, dict) else {}
        existing["active_questions"] = None
        user_course.user_answers = existing

    db.commit()
    return {
        "message": "Final Course Quiz successfully unlocked!",
        "passed_topics_count": len(roadmap_topics),
    }
