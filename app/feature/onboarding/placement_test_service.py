import json

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.feature.onboarding.placement_evaluator import classify_user
from app.feature.onboarding.placement_test_schema import (
    PlacementAnswerDetail,
    PlacementResultResponse,
    PlacementTestQuestionResponse,
)
from app.models.job_role import DEFAULT_BASELINE, JobRole
from app.models.placement_test_question import PlacementTestQuestion
from app.models.user_placement_test import UserPlacementTest

# Map v2.1 full tag -> short letter used by the existing frontend response
SKILL_TAG_TO_SHORT = {
    "D_doc": "D",
    "C_comm": "C",
    "T_trouble": "T",
    "G_custom": "G",
}


def fetch_questions_by_role(
    db: Session, role_id: int
) -> list[PlacementTestQuestionResponse]:
    """
    Fetch all placement_test_question rows for a given job_role_id.
    Parses the JSON `question` column and returns structured response objects.
    """
    records = (
        db.query(PlacementTestQuestion)
        .filter(PlacementTestQuestion.job_role_id == role_id)
        .order_by(PlacementTestQuestion.id.asc())
        .all()
    )

    results: list[PlacementTestQuestionResponse] = []

    for record in records:
        # Parse the JSON `question` column (stored as TEXT or JSON in MySQL)
        raw = record.question
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
        elif isinstance(raw, dict):
            data = raw
        else:
            continue

        statement = data.get("statement", "")
        options = data.get("options", [])
        correct_answer = data.get("correct_answer", "")

        # Validate that options is a non-empty list and correct_answer exists
        if (
            not statement
            or not isinstance(options, list)
            or not options
            or not correct_answer
        ):
            continue

        # Ensure all options are strings
        options = [str(o) for o in options]

        results.append(
            PlacementTestQuestionResponse(
                id=record.id,
                skill=SKILL_TAG_TO_SHORT.get(
                    record.skill, record.skill
                ),  # 'D' | 'C' | 'T' | 'G'
                level=record.level,  # 1 | 2 | 3
                statement=statement,
                options=options,
                correct_answer=correct_answer,
            )
        )

    return results


def save_user_placement_test_answers(db: Session, user_id: int, answers: list) -> int:
    """Persist a user's placement-test answers (one row per question) into
    user_placement_test. Re-runs replace the user's previous attempt."""
    db.execute(
        text("DELETE FROM user_placement_test WHERE user_id = :user_id"),
        {"user_id": user_id},
    )

    count = 0
    for item in answers:
        question_id = getattr(
            item,
            "question_id",
            item.get("question_id") if isinstance(item, dict) else None,
        )
        selected_id = getattr(
            item,
            "selected_id",
            item.get("selected_id") if isinstance(item, dict) else None,
        )
        selected_text = getattr(
            item,
            "selected_text",
            item.get("selected_text") if isinstance(item, dict) else None,
        )
        is_correct = getattr(
            item,
            "is_correct",
            item.get("is_correct") if isinstance(item, dict) else None,
        )
        axis = getattr(
            item, "axis", item.get("axis") if isinstance(item, dict) else None
        )
        difficulty = getattr(
            item,
            "difficulty",
            item.get("difficulty") if isinstance(item, dict) else None,
        )

        if question_id is None:
            continue

        db.execute(
            text(
                """
                INSERT INTO user_placement_test (
                    placement_test_question_id,
                    user_id,
                    user_answer
                ) VALUES (
                    :placement_test_question_id,
                    :user_id,
                    :user_answer
                )
                """
            ),
            {
                "placement_test_question_id": int(question_id),
                "user_id": user_id,
                "user_answer": json.dumps(
                    {
                        "selected_id": selected_id,
                        "selected_text": selected_text,
                        "is_correct": is_correct,
                        "axis": axis,
                        "difficulty": difficulty,
                    }
                ),
            },
        )
        count += 1

    db.flush()
    return count


def complete_placement_test(
    db: Session,
    user_id: int,
    role_id: int | None = None,
    placement_test_answers: list | None = None,
) -> bool:
    """Finalize onboarding: record placement answers, assign the selected role,
    and mark the user's placement test as finished."""
    from app.models.user import User

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError(f"User {user_id} not found")

    if role_id:
        role = db.query(JobRole).filter(JobRole.id == role_id).first()
        if role is not None and not role.is_active and user.job_role_id != role_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Career track '{role.name}' is deactivated and is not accepting "
                    "new learners. Please select an active track or contact your "
                    "administrator."
                ),
            )
        user.job_role_id = role_id  # Store selected job role (FK to job_role table)

    if placement_test_answers:
        save_user_placement_test_answers(
            db, user_id=user_id, answers=placement_test_answers
        )

    user.is_finished_placement_test = True
    db.commit()
    return True


def get_placement_test_result(db: Session, user_id: int) -> PlacementResultResponse:
    """
    Fetch a user's placement test result from user_placement_test + placement_test_question.
    Returns computed scores, starting level, and per-question detail.
    """
    from app.models.job_role import JobRole
    from app.models.user import User

    # Load user and check if placement is finished
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
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

    # Load user's placement test answers joined with questions
    rows = (
        db.query(UserPlacementTest, PlacementTestQuestion)
        .join(
            PlacementTestQuestion,
            UserPlacementTest.placement_test_question_id == PlacementTestQuestion.id,
        )
        .filter(UserPlacementTest.user_id == user_id)
        .all()
    )

    if not rows:
        return PlacementResultResponse(
            is_finished_placement_test=user.is_finished_placement_test,
            total_questions=0,
            total_correct=0,
            overall_percent=0,
            skill_scores={},
            starting_level="basic",
            weak_skills=[],
            answers=[],
        )

    # Parse user_answer JSON and build per-question detail
    answers: list[PlacementAnswerDetail] = []
    skill_correct: dict[str, int] = {
        "D_doc": 0,
        "C_comm": 0,
        "T_trouble": 0,
        "G_custom": 0,
    }
    skill_total: dict[str, int] = {
        "D_doc": 0,
        "C_comm": 0,
        "T_trouble": 0,
        "G_custom": 0,
    }

    for user_test, question in rows:
        # Parse user_answer JSON
        user_answer = {}
        if isinstance(user_test.user_answer, str):
            try:
                user_answer = json.loads(user_test.user_answer)
            except (json.JSONDecodeError, TypeError):
                continue
        elif isinstance(user_test.user_answer, dict):
            user_answer = user_test.user_answer
        else:
            continue

        # Parse question.question JSON
        question_data = {}
        if isinstance(question.question, str):
            try:
                question_data = json.loads(question.question)
            except (json.JSONDecodeError, TypeError):
                continue
        elif isinstance(question.question, dict):
            question_data = question.question
        else:
            continue

        statement = question_data.get("statement", "")
        options = question_data.get("options", [])
        correct_answer = question_data.get("correct_answer", "")

        # Validate question data
        if (
            not statement
            or not isinstance(options, list)
            or not options
            or not correct_answer
        ):
            continue

        # Ensure options are strings
        options = [str(o) for o in options]

        # Build answer detail
        answer = PlacementAnswerDetail(
            question_id=question.id,
            axis=question.skill,  # authoritative skill tag (D_doc, C_comm, T_trouble, G_custom)
            level=question.level,
            statement=statement,
            options=options,
            correct_answer=correct_answer,
            selected_id=user_answer.get("selected_id", ""),
            selected_text=user_answer.get("selected_text"),
            is_correct=user_answer.get("is_correct", False),
        )
        answers.append(answer)

        # Group by authoritative skill tag (ignore stored axis)
        skill = question.skill
        if skill not in skill_correct:
            continue

        skill_total[skill] += 1
        if answer.is_correct:
            skill_correct[skill] += 1

    # Compute per-skill scores (fraction correct)
    skill_scores_fraction: dict[str, float] = {}
    for skill, correct in skill_correct.items():
        total = max(1, skill_total[skill])  # avoid division by zero
        skill_scores_fraction[skill] = correct / total

    # Overall score
    total_questions = sum(skill_total.values())
    total_correct = sum(skill_correct.values())
    overall_fraction = total_correct / max(1, total_questions)
    overall_percent = round(overall_fraction * 100)

    # Classify starting level and weak skills
    starting_level, weak_skills = classify_user(skill_scores_fraction)

    # Load role and baseline for target bars
    role_id: int | None = None
    role_name: str | None = None
    baseline: dict[str, int] | None = None
    if user.job_role_id:
        role = db.query(JobRole).filter(JobRole.id == user.job_role_id).first()
        if role:
            role_id = role.id
            role_name = role.name
            baseline = role.baseline or DEFAULT_BASELINE

    # Convert skill_scores to percent integers
    skill_scores_percent = {
        skill: round(score * 100) for skill, score in skill_scores_fraction.items()
    }

    return PlacementResultResponse(
        is_finished_placement_test=user.is_finished_placement_test,
        total_questions=total_questions,
        total_correct=total_correct,
        overall_percent=overall_percent,
        skill_scores=skill_scores_percent,
        starting_level=starting_level,
        weak_skills=weak_skills,
        role_id=role_id,
        role_name=role_name,
        baseline=baseline,
        answers=answers,
    )
