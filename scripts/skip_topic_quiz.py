#!/usr/bin/env python3
"""Developer & Admin utility script to skip one or all topic quizzes for a user.

Marks topic quizzes as 'passed', populates valid latest_attempt result payloads,
and automatically unlocks the Final Course Quiz once all roadmap topics are passed.

Usage:
    venv/bin/python scripts/skip_topic_quiz.py [user_id_or_email] [--topic TOPIC_ID] [--all] [--score 90]

Examples:
    venv/bin/python scripts/skip_topic_quiz.py 6 --all
    venv/bin/python scripts/skip_topic_quiz.py lam@gmail.com --topic 241
    venv/bin/python scripts/skip_topic_quiz.py 6 --topic 241 --score 95
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
from app.feature.onboarding.topic_quiz_service import (
    TOPIC_QUIZ_PASS_THRESHOLD_PERCENT,
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


def build_passed_topic_attempt(
    db,
    user_id: int,
    topic_id: int,
    topic_name: str,
    score: float,
    attempt_count: int,
) -> dict:
    """Construct a full passing latest_attempt payload for the frontend TopicQuizEngine."""
    assigned_lessons = db.query(Lesson).filter(Lesson.topic_id == topic_id).all()
    pool: list[dict] = []
    for l in assigned_lessons:
        pool.extend(_extract_lesson_quiz_questions(l))

    total_questions = min(30, max(10, len(pool))) if pool else 10
    correct_count = round((score / 100.0) * total_questions)

    question_results = []
    for idx in range(total_questions):
        if idx < len(pool):
            raw_q = pool[idx]
            is_correct = idx < correct_count
            qid = raw_q.get("question_id", f"topic-q-{topic_id}-{idx}")
            stem = raw_q.get("statement", f"Sample question {idx + 1}")
            options = raw_q.get("raw_options", ["Option A", "Option B", "Option C", "Option D"])
            correct_ans = raw_q.get("correct_answer", options[0] if options else "Option A")
            user_ans = correct_ans if is_correct else (options[1] if len(options) > 1 else "Incorrect")
            q_type = raw_q.get("question_type", "fill_blank")
            lid = raw_q.get("lesson_id", assigned_lessons[0].id if assigned_lessons else 0)
            ltitle = raw_q.get("lesson_title", assigned_lessons[0].title if assigned_lessons else "Lesson")
            q_skill = raw_q.get("skill") or (lesson_skill_map.get(lid) if lid else None) or "C_comm"
        else:
            is_correct = idx < correct_count
            qid = f"topic-q-{topic_id}-dummy-{idx}"
            stem = f"Knowledge review question {idx + 1} for {topic_name}"
            options = ["Correct concept", "Distractor A", "Distractor B", "Distractor C"]
            correct_ans = "Correct concept"
            user_ans = "Correct concept" if is_correct else "Distractor A"
            q_type = "fill_blank"
            lid = assigned_lessons[0].id if assigned_lessons else 0
            ltitle = assigned_lessons[0].title if assigned_lessons else topic_name
            q_skill = assigned_lessons[idx % len(assigned_lessons)].primary_skill if assigned_lessons else "C_comm"

        question_results.append(
            {
                "question_id": qid,
                "question_type": q_type,
                "question_text": stem,
                "options": options,
                "user_answer": user_ans,
                "correct_answer": correct_ans,
                "explanation": "Admin skipped topic quiz attempt.",
                "is_correct": is_correct,
                "lesson_id": lid,
                "lesson_title": ltitle,
                "skill": q_skill,
            }
        )

    return {
        "topic_id": topic_id,
        "topic_name": topic_name,
        "passed": True,
        "score_percent": score,
        "correct_count": correct_count,
        "total_questions": total_questions,
        "status": "passed",
        "attempt_count": attempt_count,
        "failed_attempts": 0,
        "weakest_lessons": [],
        "question_results": question_results,
    }


def skip_topic_quiz(
    target: str | None = None,
    topic_id_target: int | None = None,
    skip_all: bool = False,
    score: float = 90.0,
):
    db = SessionLocal()
    try:
        user = get_target_user(db, target)
        if not user:
            print(f"❌ Error: No user found matching target: {target}")
            return

        print(f"\n========================================================")
        print(f"  Admin Topic Quiz Skipper")
        print(f"  Target User: ID {user.id} ({user.email})")
        print(f"  Target Passing Score: {score}%")
        print(f"========================================================")

        roadmap_entries = (
            db.query(UserRoadmap)
            .filter(UserRoadmap.user_id == user.id)
            .order_by(UserRoadmap.sort_order)
            .all()
        )

        if not roadmap_entries:
            print(f"⚠️ User {user.id} has no topics in their roadmap. Nothing to skip.")
            return

        roadmap_topic_ids = [r.topic_id for r in roadmap_entries]
        topics = {
            t.id: t.name
            for t in db.query(Topic).filter(Topic.id.in_(roadmap_topic_ids)).all()
        }

        # Determine which topics to skip
        topics_to_skip: list[int] = []
        if topic_id_target is not None:
            if topic_id_target not in roadmap_topic_ids:
                print(f"⚠️ Warning: Topic {topic_id_target} is not in user's roadmap. Will mark it passed anyway.")
            topics_to_skip = [topic_id_target]
        elif skip_all:
            topics_to_skip = roadmap_topic_ids
        else:
            # Interactive / display mode: if only one topic is failed/unlocked, pick it, otherwise ask or skip all
            current_quizzes = {
                q.topic_id: q.status
                for q in db.query(UserTopicQuiz).filter(UserTopicQuiz.user_id == user.id).all()
            }
            incomplete_topics = [
                tid for tid in roadmap_topic_ids if current_quizzes.get(tid) != "passed"
            ]

            print(f"\nCurrent Roadmap Status for User {user.id}:")
            for idx, tid in enumerate(roadmap_topic_ids):
                status = current_quizzes.get(tid, "unlocked/not-started")
                tname = topics.get(tid, f"Topic {tid}")
                mark = "✓" if status == "passed" else "○"
                print(f"  [{idx + 1}] {mark} Topic ID {tid}: {tname} (status: {status})")

            if not incomplete_topics:
                print(f"\n🎉 All topics are already passed for User {user.id}!")
                topics_to_skip = []
            else:
                print(f"\nDefaulting to skip all {len(incomplete_topics)} remaining incomplete topic(s)...")
                topics_to_skip = incomplete_topics

        if not topics_to_skip:
            print("No topics selected for skip.")
            return

        now = datetime.utcnow()
        for tid in topics_to_skip:
            tname = topics.get(tid, f"Topic {tid}")
            tq = (
                db.query(UserTopicQuiz)
                .filter(UserTopicQuiz.user_id == user.id, UserTopicQuiz.topic_id == tid)
                .first()
            )
            attempt_count = 1
            if tq is None:
                tq = UserTopicQuiz(
                    user_id=user.id,
                    topic_id=tid,
                    status="passed",
                    attempt_count=1,
                    failed_attempts=0,
                    best_score_percent=score,
                    last_score_percent=score,
                    completed_at=now,
                    weakest_lesson_ids=[],
                )
                db.add(tq)
                db.flush()
            else:
                attempt_count = max(tq.attempt_count + 1, 1)
                tq.status = "passed"
                tq.attempt_count = attempt_count
                tq.best_score_percent = max(tq.best_score_percent or 0.0, score)
                tq.last_score_percent = score
                tq.completed_at = now
                tq.weakest_lesson_ids = []

            # Populate latest_attempt snapshot and clear active_questions
            attempt_payload = build_passed_topic_attempt(
                db, user.id, tid, tname, score, attempt_count
            )
            existing_answers = tq.user_answers if isinstance(tq.user_answers, dict) else {}
            first_pass = existing_answers.get("first_pass") or attempt_payload
            tq.user_answers = {
                **existing_answers,
                "latest_attempt": attempt_payload,
                "best_attempt": attempt_payload,
                "first_pass": first_pass,
                "active_questions": None,
            }
            flag_modified(tq, "user_answers")
            print(f"  ✓ Skipped & Passed: Topic {tid} ('{tname}') -> Score: {score}%")

        # Check if all roadmap topics are now passed
        all_quizzes = (
            db.query(UserTopicQuiz)
            .filter(
                UserTopicQuiz.user_id == user.id,
                UserTopicQuiz.topic_id.in_(roadmap_topic_ids),
            )
            .all()
        )
        passed_topic_ids = {q.topic_id for q in all_quizzes if q.status == "passed"}
        all_passed = set(roadmap_topic_ids).issubset(passed_topic_ids)

        if all_passed:
            # Unlock the Final Course Quiz
            course = None
            if user.job_role_id:
                course = db.query(Course).filter(Course.job_role_id == user.job_role_id).first()
            if not course:
                course = db.query(Course).first()

            if course:
                uc = (
                    db.query(UserCourse)
                    .filter(UserCourse.user_id == user.id, UserCourse.course_id == course.id)
                    .first()
                )
                if uc is None:
                    uc = UserCourse(
                        user_id=user.id,
                        course_id=course.id,
                        status="ready",
                        attempt_count=0,
                        failed_attempts=0,
                        best_score_percent=0.0,
                        last_score_percent=0.0,
                        unlocked_at=now,
                        user_answers={"active_questions": None},
                    )
                    db.add(uc)
                else:
                    if uc.status == "locked":
                        uc.status = "ready"
                    if not uc.unlocked_at:
                        uc.unlocked_at = now
                    # Clear active questions to guarantee fresh load
                    ua = uc.user_answers if isinstance(uc.user_answers, dict) else {}
                    ua["active_questions"] = None
                    uc.user_answers = ua
                    flag_modified(uc, "user_answers")

                print(f"\n🎉 ALL {len(roadmap_topic_ids)} TOPIC QUIZZES ARE NOW PASSED!")
                print(f"  ✓ Final Course Quiz unlocked and marked 'ready' for Course ID {course.id} ('{course.name}').")
                print(f"  Learner can now take the Final Course Quiz at: /quiz/final/course")

        db.commit()

        # Update learner's radar score across skills D, C, T, G based on best topic scores
        updated_radar = update_user_radar_score(db, user.id)
        if updated_radar:
            print(f"  ✓ Radar scores updated for user ID {user.id}: {updated_radar.current_vector}")

        print(f"\nDatabase updated successfully.")
        print(f"You can view the topic quiz results in the frontend at: /quiz/topic/<topic_id>")
        print(f"========================================================\n")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Admin utility to skip topic quizzes and mark them as passed."
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="User ID or email address (e.g. 6 or lam@gmail.com). Defaults to first user with roadmap.",
    )
    parser.add_argument(
        "--topic",
        type=int,
        default=None,
        help="Specific topic ID to skip (e.g. --topic 241).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Skip all topic quizzes in user's roadmap.",
    )
    parser.add_argument(
        "--score",
        type=float,
        default=90.0,
        help="Score percentage to grant for skipped quizzes (default: 90.0).",
    )
    args = parser.parse_args()

    skip_topic_quiz(
        target=args.target,
        topic_id_target=args.topic,
        skip_all=args.all,
        score=args.score,
    )
