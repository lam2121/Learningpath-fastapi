from typing import Any
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.infra.config import app_config
from app.models.user_radar_score import UserRadarScore
from app.models.user_lesson import UserLesson
from app.models.lesson import Lesson
from app.models.user_topic_quiz import UserTopicQuiz
from app.models.topic import Topic
from app.models.user_final_quiz import UserFinalQuiz
from app.feature.quiz.lesson_quiz_scoring import (
    compute_radar_score_for_skill,
    PLACEMENT_EVIDENCE_WEIGHT,
)

SKILLS = ("D_doc", "C_comm", "T_trouble", "G_custom")


def _coerce_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        import json
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _normalize_radar_vector(raw: Any) -> dict[str, float]:
    obj = _coerce_json_object(raw)
    normalized: dict[str, float] = {}
    default_score = app_config.DEFAULT_INITIAL_RADAR_SCORE
    for sk in SKILLS:
        val = obj.get(sk, default_score)
        try:
            normalized[sk] = float(val) if val is not None else default_score
        except (ValueError, TypeError):
            normalized[sk] = default_score
    return normalized


def update_user_radar_score(db: Session, user_id: int) -> UserRadarScore | None:
    """
    Recalculates the learner's radar score (current_vector and prev_stack)
    based on:
    1. All passed lesson quizzes (each lesson contributes its score to its primary_skill).
    2. The BEST attempt of each passed/completed topic quiz, broken down by question skills (D, C, T, G).
    3. The BEST attempt of the final course quiz, broken down by question skills (D, C, T, G).

    Uses the weighted moving average formula:
    (start_vector * 3.2 + sum(performances)) / (3.2 + len(performances))
    """
    radar = db.query(UserRadarScore).filter(UserRadarScore.user_id == user_id).first()
    if radar is None:
        # Initialize UserRadarScore if missing
        start_vector = {sk: app_config.DEFAULT_INITIAL_RADAR_SCORE for sk in SKILLS}
        radar = UserRadarScore(
            user_id=user_id,
            start_vector=start_vector,
            current_vector=start_vector,
            prev_stack={sk: [] for sk in SKILLS},
        )
        db.add(radar)
        db.flush()

    start_vector = _normalize_radar_vector(radar.start_vector)

    # 1. Lesson quiz performances (from completed lessons)
    lesson_performances: dict[str, list[float]] = {sk: [] for sk in SKILLS}
    completed_lessons = (
        db.query(UserLesson, Lesson)
        .join(Lesson, Lesson.id == UserLesson.lesson_id)
        .filter(
            UserLesson.user_id == user_id,
            (UserLesson.completed_at.isnot(None)) | (UserLesson.status == "completed"),
        )
        .all()
    )

    for user_lesson, lesson in completed_lessons:
        skill = lesson.primary_skill
        if skill not in SKILLS:
            continue

        user_answers = _coerce_json_object(user_lesson.user_answers)
        first_pass = user_answers.get("first_pass")
        score = None
        if isinstance(first_pass, dict) and "weighted_score_percent" in first_pass:
            score = float(first_pass["weighted_score_percent"])
        elif user_lesson.progress is not None and user_lesson.progress > 0:
            score = float(user_lesson.progress)

        if score is not None and score > 0:
            lesson_performances[skill].append(round(score, 2))

    # Pre-cache lesson -> primary_skill mapping for question skill resolution
    lesson_skills = dict(
        db.query(Lesson.id, Lesson.primary_skill).all()
    )

    # 2. Topic quiz performances (first passing attempt of each topic)
    topic_performances: dict[str, list[float]] = {sk: [] for sk in SKILLS}
    user_topic_quizzes = (
        db.query(UserTopicQuiz, Topic)
        .join(Topic, Topic.id == UserTopicQuiz.topic_id)
        .filter(
            UserTopicQuiz.user_id == user_id,
            (UserTopicQuiz.status == "passed") | (UserTopicQuiz.best_score_percent > 0),
        )
        .all()
    )

    for utq, topic in user_topic_quizzes:
        user_answers = _coerce_json_object(utq.user_answers)
        first_pass = (
            user_answers.get("first_pass")
            or user_answers.get("best_attempt")
            or user_answers.get("latest_attempt")
        )
        if not isinstance(first_pass, dict):
            if topic.primary_skill in SKILLS and utq.best_score_percent:
                topic_performances[topic.primary_skill].append(round(float(utq.best_score_percent), 2))
            continue

        question_results = first_pass.get("question_results", [])
        if isinstance(question_results, list) and len(question_results) > 0:
            skill_counts: dict[str, dict[str, int]] = {
                sk: {"correct": 0, "total": 0} for sk in SKILLS
            }
            for q in question_results:
                if not isinstance(q, dict):
                    continue
                q_skill = q.get("skill")
                if not q_skill or q_skill not in SKILLS:
                    lid = q.get("lesson_id")
                    q_skill = lesson_skills.get(lid) or topic.primary_skill
                if q_skill in SKILLS:
                    skill_counts[q_skill]["total"] += 1
                    if q.get("is_correct"):
                        skill_counts[q_skill]["correct"] += 1

            has_questions = False
            for sk, cnt in skill_counts.items():
                if cnt["total"] > 0:
                    has_questions = True
                    acc = round((cnt["correct"] / cnt["total"]) * 100.0, 2)
                    topic_performances[sk].append(acc)

            if not has_questions and topic.primary_skill in SKILLS and utq.best_score_percent:
                topic_performances[topic.primary_skill].append(round(float(utq.best_score_percent), 2))
        elif topic.primary_skill in SKILLS and utq.best_score_percent:
            topic_performances[topic.primary_skill].append(round(float(utq.best_score_percent), 2))

    # 3. Final course quiz performances (first passing attempt)
    final_performances: dict[str, list[float]] = {sk: [] for sk in SKILLS}
    user_course = (
        db.query(UserFinalQuiz)
        .filter(
            UserFinalQuiz.user_id == user_id,
            (UserFinalQuiz.status == "passed") | (UserFinalQuiz.best_score_percent > 0),
        )
        .first()
    )

    if user_course:
        user_answers = _coerce_json_object(user_course.user_answers)
        first_pass = (
            user_answers.get("first_pass")
            or user_answers.get("best_attempt")
            or user_answers.get("latest_attempt")
        )
        skill_scores = None
        if isinstance(first_pass, dict):
            skill_scores = first_pass.get("skill_scores")
        if not skill_scores and isinstance(user_course.skill_scores, dict):
            skill_scores = user_course.skill_scores

        if isinstance(skill_scores, dict):
            for sk in SKILLS:
                val = skill_scores.get(sk)
                if isinstance(val, (int, float)):
                    final_performances[sk].append(round(float(val), 2))
                elif isinstance(val, dict) and "accuracy_percent" in val:
                    final_performances[sk].append(round(float(val["accuracy_percent"]), 2))
                elif isinstance(val, dict) and "percent" in val:
                    final_performances[sk].append(round(float(val["percent"]), 2))
        elif isinstance(first_pass, dict):
            # Fallback to question_results in final quiz attempt
            q_results = first_pass.get("question_results", [])
            if isinstance(q_results, list) and len(q_results) > 0:
                skill_counts = {sk: {"correct": 0, "total": 0} for sk in SKILLS}
                for q in q_results:
                    if not isinstance(q, dict):
                        continue
                    q_skill = q.get("skill")
                    if q_skill in SKILLS:
                        skill_counts[q_skill]["total"] += 1
                        if q.get("is_correct"):
                            skill_counts[q_skill]["correct"] += 1
                for sk, cnt in skill_counts.items():
                    if cnt["total"] > 0:
                        final_performances[sk].append(
                            round((cnt["correct"] / cnt["total"]) * 100.0, 2)
                        )

    # 4. Calculate final moving average current_vector and prev_stack
    current_vector: dict[str, float] = {}
    prev_stack: dict[str, list[float]] = {}

    for sk in SKILLS:
        all_scores = (
            lesson_performances[sk]
            + topic_performances[sk]
            + final_performances[sk]
        )
        prev_stack[sk] = all_scores
        current_vector[sk] = round(
            compute_radar_score_for_skill(
                start_vector.get(sk, app_config.DEFAULT_INITIAL_RADAR_SCORE),
                all_scores,
            ),
            2,
        )

    radar.current_vector = current_vector
    radar.prev_stack = prev_stack
    try:
        flag_modified(radar, "current_vector")
        flag_modified(radar, "prev_stack")
    except Exception:
        pass
    db.commit()
    db.refresh(radar)
    return radar
