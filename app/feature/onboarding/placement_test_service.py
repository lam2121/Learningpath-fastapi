import json
from typing import List
from sqlalchemy.orm import Session

from app.models.placement_test_question import PlacementTestQuestion
from app.feature.onboarding.placement_test_schema import PlacementTestQuestionResponse

# Map v2.1 full tag -> short letter used by the existing frontend response
SKILL_TAG_TO_SHORT = {
    "D_doc": "D",
    "C_comm": "C",
    "T_trouble": "T",
    "G_custom": "G",
}


def fetch_questions_by_role(
    db: Session, role_id: int
) -> List[PlacementTestQuestionResponse]:
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

    results: List[PlacementTestQuestionResponse] = []

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
