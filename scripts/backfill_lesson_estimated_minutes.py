#!/usr/bin/env python3
"""Backfill lesson.estimated_minutes from saved theory/quiz content."""

from pathlib import Path
import sys


# Allow running this script directly from the repo without installing the app package.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import SessionLocal
from app.core.lesson_duration import estimate_lesson_duration
from app.models.lesson import Lesson


def main() -> None:
    db = SessionLocal()
    try:
        lessons = (
            db.query(Lesson)
            .filter(Lesson.estimated_minutes.is_(None))
            .filter(Lesson.theory_content.is_not(None))
            .filter(Lesson.quiz_content.is_not(None))
            .all()
        )

        updated = 0
        for lesson in lessons:
            lesson.estimated_minutes = estimate_lesson_duration(
                lesson.theory_content, lesson.quiz_content
            )
            updated += 1

        db.commit()
        print(f"Backfilled estimated_minutes for {updated} lesson(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
