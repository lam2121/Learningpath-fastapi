import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.feature.onboarding.placement_test_schema import PlacementTestQuestionResponse
from app.models.placement_test_question import PlacementTestQuestion

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


def save_user_placement_test_answers(
    db: Session, user_id: int, answers: list
) -> int:
    """Persist a user's placement-test answers (one row per question) into
    user_placement_test. Re-runs replace the user's previous attempt."""
    db.execute(
        text("DELETE FROM user_placement_test WHERE user_id = :user_id"),
        {"user_id": user_id},
    )

    count = 0
    for item in answers:
        question_id = getattr(
            item, "question_id", item.get("question_id") if isinstance(item, dict) else None
        )
        selected_id = getattr(
            item, "selected_id", item.get("selected_id") if isinstance(item, dict) else None
        )
        is_correct = getattr(
            item, "is_correct", item.get("is_correct") if isinstance(item, dict) else None
        )
        axis = getattr(item, "axis", item.get("axis") if isinstance(item, dict) else None)
        difficulty = getattr(
            item, "difficulty", item.get("difficulty") if isinstance(item, dict) else None
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

    if placement_test_answers:
        save_user_placement_test_answers(
            db, user_id=user_id, answers=placement_test_answers
        )

    if role_id:
        user.job_role_id = role_id  # Store selected job role (FK to job_role table)
    user.is_finished_placement_test = True
    db.commit()
    return True
