from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    from datetime import UTC
except ImportError:
    UTC = timezone.utc

from sqlalchemy.orm import Session

from app.feature.onboarding.lesson_quiz_scoring import normalize_index_answer
from app.feature.onboarding.lesson_quiz_service import (
    _build_question_bank,
    _normalize_quiz_content,
    _split_question_options,
)
from app.models.lesson import Lesson
from app.models.queue import Queue
from app.models.user_lesson import UserLesson


def _check_review_answer_correct(
    question_type: str | None,
    user_answer: str,
    correct_answer: str | None,
) -> bool:
    if not correct_answer:
        return False
    clean_user = (user_answer or "").strip()
    clean_correct = correct_answer.strip()
    if not clean_user:
        return False

    if question_type == "multi_select":
        return normalize_index_answer(clean_user) == normalize_index_answer(clean_correct)

    if question_type == "fill_blank":
        return clean_user.lower() == clean_correct.lower()

    return clean_user == clean_correct


def sync_past_wrong_answers_if_empty(db: Session, user_id: int) -> None:
    """If the user's review queue is empty, backfill historical wrong answers

    from UserLesson records so they immediately have review content.
    """
    existing_count = (
        db.query(Queue)
        .filter(Queue.user_id == user_id, Queue.lesson_id.isnot(None))
        .count()
    )
    if existing_count > 0:
        return

    user_lessons = (
        db.query(UserLesson)
        .filter(UserLesson.user_id == user_id)
        .all()
    )
    if not user_lessons:
        return

    added = False
    for ul in user_lessons:
        if not isinstance(ul.user_answers, dict):
            continue
        question_results = ul.user_answers.get("question_results", [])
        if not isinstance(question_results, list):
            continue

        lesson = db.query(Lesson).filter(Lesson.id == ul.lesson_id).first()
        if not lesson or not lesson.quiz_content:
            continue

        try:
            questions = _build_question_bank(_normalize_quiz_content(lesson.quiz_content))
            question_lookup = {q["question_id"]: q for q in questions}
        except Exception:
            continue

        for res in question_results:
            if not isinstance(res, dict):
                continue
            if not bool(res.get("is_correct")):
                qid = str(res.get("question_id", ""))
                q_data = question_lookup.get(qid)
                if not q_data:
                    continue

                existing = (
                    db.query(Queue)
                    .filter(
                        Queue.user_id == user_id,
                        Queue.lesson_id == ul.lesson_id,
                        Queue.question_id == qid,
                    )
                    .first()
                )
                if not existing:
                    queue_item = Queue(
                        user_id=user_id,
                        lesson_id=ul.lesson_id,
                        question_id=qid,
                        question_type=q_data.get("question_type", "fill_blank"),
                        stem=q_data.get("stem", ""),
                        options=_split_question_options(q_data.get("options", "")),
                        correct_answer=q_data.get("correct_answer", ""),
                        explanation=q_data.get("explanation", ""),
                        last_wrong_answer=str(res.get("user_answer", "") or ""),
                        status="pending",
                        count=1,
                    )
                    db.add(queue_item)
                    added = True

    if added:
        db.commit()


def get_user_quiz_review_items(
    db: Session,
    user_id: int,
    limit: int = 5,
) -> dict[str, Any]:
    """Retrieve up to `limit` pending review questions for the given user,

    along with the total count of wrong questions waiting for review.
    """
    sync_past_wrong_answers_if_empty(db, user_id)

    total_count = (
        db.query(Queue)
        .filter(
            Queue.user_id == user_id,
            Queue.lesson_id.isnot(None),
            Queue.status == "pending",
        )
        .count()
    )

    rows = (
        db.query(Queue, Lesson.title)
        .join(Lesson, Queue.lesson_id == Lesson.id)
        .filter(
            Queue.user_id == user_id,
            Queue.lesson_id.isnot(None),
            Queue.status == "pending",
        )
        .order_by(Queue.count.desc(), Queue.created_at.asc())
        .limit(max(1, min(limit, 50)))
        .all()
    )

    questions = []
    for queue_item, lesson_title in rows:
        options = queue_item.options
        if isinstance(options, str):
            options = _split_question_options(options)
        elif not isinstance(options, list):
            options = []

        questions.append(
            {
                "review_id": queue_item.id,
                "lesson_id": queue_item.lesson_id,
                "lesson_title": lesson_title or "Lesson",
                "question_id": queue_item.question_id,
                "question_type": queue_item.question_type or "fill_blank",
                "stem": queue_item.stem or "",
                "options": options,
                "explanation": queue_item.explanation or "",
                "wrong_count": queue_item.count,
            }
        )

    return {
        "total_count": total_count,
        "review_questions": questions,
    }


def submit_user_quiz_review(
    db: Session,
    user_id: int,
    submitted_answers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Grade submitted review answers.

    - If answer is correct: remove the question from the Queue.
    - If answer is incorrect: retain in Queue, update count and last_reviewed_at.
    """
    results: list[dict[str, Any]] = []
    cleared_count = 0
    failed_count = 0

    for item in submitted_answers:
        review_id = item.get("review_id")
        user_answer = str(item.get("answer", "") or "")
        if review_id is None:
            continue

        queue_item = (
            db.query(Queue)
            .filter(
                Queue.id == review_id,
                Queue.user_id == user_id,
            )
            .first()
        )
        if not queue_item:
            continue

        is_correct = _check_review_answer_correct(
            queue_item.question_type,
            user_answer,
            queue_item.correct_answer,
        )

        stem = queue_item.stem or ""
        correct_ans = queue_item.correct_answer or ""
        explanation = queue_item.explanation or ""
        question_id = queue_item.question_id or ""
        question_type = queue_item.question_type or "fill_blank"

        raw_options = queue_item.options
        if isinstance(raw_options, str):
            options = _split_question_options(raw_options)
        elif isinstance(raw_options, list):
            options = [str(opt) for opt in raw_options]
        else:
            options = []

        if is_correct:
            # Correct answer -> Remove from queue!
            db.delete(queue_item)
            cleared_count += 1
            removed = True
        else:
            # Incorrect answer -> Keep in queue and update review stats!
            queue_item.count += 1
            queue_item.last_wrong_answer = user_answer
            queue_item.last_reviewed_at = datetime.now(UTC).replace(tzinfo=None)
            failed_count += 1
            removed = False

        results.append(
            {
                "review_id": review_id,
                "question_id": question_id,
                "question_type": question_type,
                "stem": stem,
                "options": options,
                "user_answer": user_answer,
                "correct_answer": correct_ans,
                "explanation": explanation,
                "is_correct": is_correct,
                "removed": removed,
            }
        )

    db.commit()

    remaining_count = (
        db.query(Queue)
        .filter(
            Queue.user_id == user_id,
            Queue.lesson_id.isnot(None),
            Queue.status == "pending",
        )
        .count()
    )

    return {
        "results": results,
        "cleared_count": cleared_count,
        "failed_count": failed_count,
        "total_reviewed": len(results),
        "remaining_count": remaining_count,
    }
