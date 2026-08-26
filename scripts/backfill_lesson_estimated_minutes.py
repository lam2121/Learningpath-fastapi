"""Backfill lesson.estimated_minutes from saved theory/quiz content."""
#python3 scripts/backfill_lesson_estimated_minutes.py
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
