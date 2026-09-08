#!/usr/bin/env python3
"""Developer & Admin utility script to complete and pass the Final Course Quiz for a user.

Marks user_course as 'passed', sets graduation progress to 100%, populates full
passing latest_attempt results (including 4-axis skill breakdown), and generates
a complete completion certificate state in the database.

Usage:
    venv/bin/python scripts/complete_final_quiz.py [user_id_or_email] [--score 92]

Examples:
    venv/bin/python scripts/complete_final_quiz.py 6
    venv/bin/python scripts/complete_final_quiz.py lam@gmail.com --score 95
"""
import argparse
import os
import sys
from datetime import datetime

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from sqlalchemy.orm.attributes import flag_modified
from app.core.database import SessionLocal
from app.models.course import Course
from app.models.lesson import Lesson
from app.models.topic import Topic
from app.models.user import User
from app.models.user_course import UserCourse
from app.models.user_roadmap import UserRoadmap
from app.models.user_topic_quiz import UserTopicQuiz
from app.feature.onboarding.final_quiz_service import (
    SKILLS,
    SKILL_LABELS,
    _extract_lesson_quiz_questions,
)
from app.feature.onboarding.radar_service import update_user_radar_score


def get_target_user(db, target: str | None) -> User | None:
    query = db.query(User)
    if target:
        if target.isdigit():
            user = query.filter(User.id == int(target)).first()
        else:
            user = query.filter(User.email == target).first()
        return user

    # Default to first user with a roadmap
    user_ids_with_roadmap = [
        r[0] for r in db.query(UserRoadmap.user_id).distinct().all()
    ]
    if user_ids_with_roadmap:
        return db.query(User).filter(User.id.in_(user_ids_with_roadmap)).first()

    return db.query(User).first()


def build_final_quiz_attempt(
    db,
    user_id: int,
    course_name: str,
    score: float,
    attempt_count: int,
) -> dict:
    """Build a complete passing FinalQuizSubmitResponse payload."""
    # Try to extract actual questions from roadmap lessons
    roadmap_entries = (
        db.query(UserRoadmap)
        .filter(UserRoadmap.user_id == user_id)
        .order_by(UserRoadmap.sort_order)
        .all()
    )
    topic_ids = [r.topic_id for r in roadmap_entries]
    lessons = db.query(Lesson).filter(Lesson.topic_id.in_(topic_ids)).all() if topic_ids else []

    raw_pool: list[dict] = []
    for l in lessons:
        raw_pool.extend(_extract_lesson_quiz_questions(l))

    total_questions = 50
    correct_count = round((score / 100.0) * total_questions)

    # Distribute questions across the 4 skills: D_doc, C_comm, T_trouble, G_custom
    skill_counts = {"D_doc": 12, "C_comm": 13, "T_trouble": 12, "G_custom": 13}
    skill_correct = {
        sk: round((score / 100.0) * count) for sk, count in skill_counts.items()
    }

    question_results = []
    current_q_idx = 0

    for sk, count in skill_counts.items():
        sk_label = SKILL_LABELS.get(sk, sk)
        num_correct_for_skill = skill_correct[sk]

        for i in range(count):
            current_q_idx += 1
            is_correct = i < num_correct_for_skill

            if current_q_idx - 1 < len(raw_pool):
                rq = raw_pool[current_q_idx - 1]
                qid = rq.get("question_id", f"final-q-{current_q_idx}")
                stem = rq.get("statement", f"Comprehensive graduation question {current_q_idx} on {sk_label}")
                options = rq.get("raw_options", ["Correct standard", "Alternate option", "Distractor 1", "Distractor 2"])
                correct_ans = rq.get("correct_answer", options[0] if options else "Correct standard")
                user_ans = correct_ans if is_correct else (options[1] if len(options) > 1 else "Incorrect")
                q_type = rq.get("question_type", "fill_blank")
                lid = rq.get("lesson_id", lessons[0].id if lessons else 0)
                ltitle = rq.get("lesson_title", lessons[0].title if lessons else "Graduation Module")
            else:
                qid = f"final-q-{current_q_idx}"
                stem = f"Comprehensive graduation evaluation {current_q_idx}: Applied proficiency in {sk_label}."
                options = ["Professional application", "Incomplete procedure", "Suboptimal choice", "Incorrect practice"]
                correct_ans = "Professional application"
                user_ans = "Professional application" if is_correct else "Suboptimal choice"
                q_type = "fill_blank"
                lid = lessons[0].id if lessons else 0
                ltitle = lessons[0].title if lessons else "Course Graduation"

            question_results.append(
                {
                    "question_id": qid,
                    "question_type": q_type,
                    "question_text": stem,
                    "options": options,
                    "user_answer": user_ans,
                    "correct_answer": correct_ans,
                    "explanation": f"Graduation evaluation standard for {sk_label}.",
                    "is_correct": is_correct,
                    "lesson_id": lid,
                    "lesson_title": ltitle,
                    "skill": sk,
                }
            )

    # Skill breakdown cards
    skill_breakdown = []
    skill_scores_dict = {}
    for sk in SKILLS:
        total = skill_counts[sk]
        corr = skill_correct[sk]
        acc = round((corr / total) * 100.0, 2)
        skill_breakdown.append(
            {
                "skill": sk,
                "label": SKILL_LABELS.get(sk, sk),
                "correct_count": corr,
                "total_count": total,
                "accuracy_percent": acc,
                "passed": acc >= 60.0,
            }
        )
        skill_scores_dict[sk] = acc

    return {
        "passed": True,
        "score_percent": score,
        "correct_count": correct_count,
        "total_questions": total_questions,
        "status": "passed",
        "attempt_count": attempt_count,
        "failed_attempts": 0,
        "skill_scores": skill_scores_dict,
        "skill_breakdown": skill_breakdown,
        "weakest_lessons": [],
        "question_results": question_results,
    }


def complete_final_quiz(
    target: str | None = None,
    score: float = 92.0,
    ensure_topics_passed: bool = True,
):
    db = SessionLocal()
    try:
        user = get_target_user(db, target)
        if not user:
            print(f"❌ Error: No user found matching target: {target}")
            return

        print(f"\n========================================================")
        print(f"  Admin Final Course Quiz Completer")
        print(f"  Target User: ID {user.id} ({user.email})")
        print(f"  Graduation Score: {score}%")
        print(f"========================================================")

        # 1. Ensure all topic quizzes in the roadmap are passed (required for graduation)
        roadmap_entries = (
            db.query(UserRoadmap)
            .filter(UserRoadmap.user_id == user.id)
            .order_by(UserRoadmap.sort_order)
            .all()
        )

        now = datetime.utcnow()
        if roadmap_entries and ensure_topics_passed:
            print(f"\nVerifying {len(roadmap_entries)} roadmap topic quizzes...")
            for r in roadmap_entries:
                tq = (
                    db.query(UserTopicQuiz)
                    .filter(
                        UserTopicQuiz.user_id == user.id,
                        UserTopicQuiz.topic_id == r.topic_id,
                    )
                    .first()
                )
                if tq is None:
                    tq = UserTopicQuiz(
                        user_id=user.id,
                        topic_id=r.topic_id,
                        status="passed",
                        attempt_count=1,
                        failed_attempts=0,
                        best_score_percent=90.0,
                        last_score_percent=90.0,
                        completed_at=now,
                        weakest_lesson_ids=[],
                    )
                    db.add(tq)
                elif tq.status != "passed":
                    tq.status = "passed"
                    tq.attempt_count = max(tq.attempt_count + 1, 1)
                    tq.best_score_percent = max(tq.best_score_percent or 0.0, 90.0)
                    tq.last_score_percent = 90.0
                    tq.completed_at = now
                    tq.weakest_lesson_ids = []
            print(f"  ✓ All topic quizzes confirmed as 'passed'.")

        # 2. Locate or create user_course
        course = None
        if user.job_role_id:
            course = db.query(Course).filter(Course.job_role_id == user.job_role_id).first()
        if not course:
            course = db.query(Course).first()

        if not course:
            print(f"❌ Error: No course found in database.")
            return

        user_course = (
            db.query(UserCourse)
            .filter(UserCourse.user_id == user.id, UserCourse.course_id == course.id)
            .first()
        )

        attempt_count = 1
        if user_course is None:
            user_course = UserCourse(
                user_id=user.id,
                course_id=course.id,
                status="passed",
                attempt_count=1,
                failed_attempts=0,
                best_score_percent=score,
                last_score_percent=score,
                progress=100.0,
                unlocked_at=now,
                completed_at=now,
            )
            db.add(user_course)
            db.flush()
        else:
            attempt_count = max(user_course.attempt_count + 1, 1)
            user_course.status = "passed"
            user_course.attempt_count = attempt_count
            user_course.failed_attempts = 0
            user_course.best_score_percent = max(user_course.best_score_percent or 0.0, score)
            user_course.last_score_percent = score
            user_course.progress = 100.0
            user_course.completed_at = now
            if not user_course.unlocked_at:
                user_course.unlocked_at = now

        user_course.weakest_lesson_ids = []
        user_course.skill_scores = {
            sk: score for sk in SKILLS
        }

        # 3. Build passing latest_attempt payload for the frontend FinalQuizEngine
        attempt_payload = build_final_quiz_attempt(
            db, user.id, course.name, score, attempt_count
        )

        existing_answers = user_course.user_answers if isinstance(user_course.user_answers, dict) else {}
        first_pass = existing_answers.get("first_pass") or attempt_payload
        user_course.user_answers = {
            **existing_answers,
            "latest_attempt": attempt_payload,
            "best_attempt": attempt_payload,
            "first_pass": first_pass,
            "active_questions": None,
        }
        flag_modified(user_course, "user_answers")

        db.commit()

        # Update learner's radar scores across skills D, C, T, G based on best scores
        updated_radar = update_user_radar_score(db, user.id)
        if updated_radar:
            print(f"  ✓ Radar scores updated for user ID {user.id}: {updated_radar.current_vector}")

        print(f"\n🎓 GRADUATION QUIZ SUCCESSFULLY COMPLETED & PASSED!")
        print(f"  Course: ID {course.id} - '{course.name}'")
        print(f"  Overall Score: {score}% (Passing Threshold: 80%)")
        print(f"  Skill Breakdown (all >= 60% requirement met):")
        for sk in SKILLS:
            print(f"    - {SKILL_LABELS.get(sk, sk)}: {score}% (Passed)")
        print(f"  Status: PASSED")
        print(f"  Course Progress: 100.0%")
        print(f"\nYou can immediately view the Graduation Certificate & Result page in the browser at:")
        print(f"  👉 http://localhost:3000/quiz/final/course")
        print(f"  👉 http://localhost:3000/lessons/learning-path")
        print(f"========================================================\n")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Admin utility to complete and pass the Final Course Quiz."
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="User ID or email address (e.g. 6 or lam@gmail.com). Defaults to first user with roadmap.",
    )
    parser.add_argument(
        "--score",
        type=float,
        default=92.0,
        help="Graduation score percentage (default: 92.0, threshold is 80.0).",
    )
    parser.add_argument(
        "--no-topics",
        action="store_true",
        help="Do not automatically ensure roadmap topic quizzes are passed.",
    )
    args = parser.parse_args()

    complete_final_quiz(
        target=args.target,
        score=args.score,
        ensure_topics_passed=not args.no_topics,
    )
