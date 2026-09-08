from sqlalchemy import inspect, text
from app.core.database import engine


def ensure_queue_schema() -> None:
    """Ensure the queue table has the necessary columns and constraints for wrong-answer review."""
    insp = inspect(engine)
    if not insp.has_table("queue"):
        return

    existing_columns = {col["name"] for col in insp.get_columns("queue")}

    with engine.connect() as conn:
        # Check and drop old foreign key fk_queue_quiz if it exists
        fk_names = [
            fk["name"]
            for fk in insp.get_foreign_keys("queue")
            if fk.get("name") == "fk_queue_quiz"
        ]
        if fk_names:
            try:
                conn.execute(text("ALTER TABLE `queue` DROP FOREIGN KEY `fk_queue_quiz`"))
            except Exception as e:
                print(f"[queue_schema] Notice dropping fk_queue_quiz: {e}")

        # Modify quiz_id to be NULL
        try:
            conn.execute(text("ALTER TABLE `queue` MODIFY COLUMN `quiz_id` BIGINT NULL"))
        except Exception as e:
            print(f"[queue_schema] Notice modifying quiz_id: {e}")

        # Modify next_review_date and last_reviewed_at to allow NULL
        try:
            conn.execute(text("ALTER TABLE `queue` MODIFY COLUMN `next_review_date` DATE NULL"))
        except Exception as e:
            print(f"[queue_schema] Notice modifying next_review_date: {e}")

        try:
            conn.execute(text("ALTER TABLE `queue` MODIFY COLUMN `last_reviewed_at` DATETIME NULL"))
        except Exception as e:
            print(f"[queue_schema] Notice modifying last_reviewed_at: {e}")

        # Modify status default
        try:
            conn.execute(text("ALTER TABLE `queue` MODIFY COLUMN `status` VARCHAR(20) NOT NULL DEFAULT 'pending'"))
        except Exception as e:
            print(f"[queue_schema] Notice modifying status: {e}")

        # Modify count default
        try:
            conn.execute(text("ALTER TABLE `queue` MODIFY COLUMN `count` INT NOT NULL DEFAULT 1"))
        except Exception as e:
            print(f"[queue_schema] Notice modifying count: {e}")

        # Add new columns if missing
        new_columns = [
            ("lesson_id", "BIGINT NULL"),
            ("question_id", "VARCHAR(50) NULL"),
            ("question_type", "VARCHAR(50) NULL"),
            ("stem", "TEXT NULL"),
            ("options", "JSON NULL"),
            ("correct_answer", "TEXT NULL"),
            ("explanation", "TEXT NULL"),
            ("last_wrong_answer", "TEXT NULL"),
        ]

        for col_name, col_def in new_columns:
            if col_name not in existing_columns:
                try:
                    conn.execute(text(f"ALTER TABLE `queue` ADD COLUMN `{col_name}` {col_def}"))
                    print(f"[queue_schema] Added column {col_name} to queue table.")
                except Exception as e:
                    print(f"[queue_schema] Notice adding {col_name}: {e}")

        # Add fk_queue_lesson if missing
        current_fks = {fk["name"] for fk in inspect(engine).get_foreign_keys("queue")}
        if "fk_queue_lesson" not in current_fks and "lesson" in insp.get_table_names():
            try:
                conn.execute(text(
                    "ALTER TABLE `queue` ADD CONSTRAINT `fk_queue_lesson` "
                    "FOREIGN KEY (`lesson_id`) REFERENCES `lesson`(`id`) "
                    "ON DELETE CASCADE ON UPDATE CASCADE"
                ))
                print("[queue_schema] Added fk_queue_lesson foreign key.")
            except Exception as e:
                print(f"[queue_schema] Notice adding fk_queue_lesson: {e}")

        # Add unique constraint uq_queue_user_lesson_question if missing
        unique_constraints = {
            uc["name"] for uc in inspect(engine).get_unique_constraints("queue")
        }
        if "uq_queue_user_lesson_question" not in unique_constraints:
            try:
                conn.execute(text(
                    "ALTER TABLE `queue` ADD CONSTRAINT `uq_queue_user_lesson_question` "
                    "UNIQUE (`user_id`, `lesson_id`, `question_id`)"
                ))
                print("[queue_schema] Added uq_queue_user_lesson_question unique constraint.")
            except Exception as e:
                print(f"[queue_schema] Notice adding uq_queue_user_lesson_question: {e}")

        conn.commit()


if __name__ == "__main__":
    ensure_queue_schema()
    print("Queue schema migration completed successfully.")
