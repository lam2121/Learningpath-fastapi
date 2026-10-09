"""Shared learner-reset routine used by every reset path.

One place that knows the full set of learner-owned tables, so a new
`user_*` table only has to be added here. `user_placement_test` and
`user_flashcard` carry no `ON DELETE CASCADE`, so every table is deleted
explicitly rather than relying on FK cascades.

Callers are responsible for the commit.
"""

from sqlalchemy.orm import Session

from app.models.queue import Queue
from app.models.user import LEARNING_NONE, User
from app.models.user_final_quiz import UserFinalQuiz
from app.models.user_flashcard import UserFlashcard
from app.models.user_lesson import UserLesson
from app.models.user_placement_test import UserPlacementTest
from app.models.user_radar_score import UserRadarScore
from app.models.user_roadmap import UserRoadmap
from app.models.user_topic_quiz import UserTopicQuiz

# (result key, model) in FK-safe delete order — children before parents.
_LEARNER_TABLES = (
    ("clearedQueueEntries", Queue),
    ("clearedLessons", UserLesson),
    ("clearedTopicQuizzes", UserTopicQuiz),
    ("clearedFinalQuizzes", UserFinalQuiz),
    ("clearedRoadmaps", UserRoadmap),
    ("clearedRadarScores", UserRadarScore),
    ("clearedAnswers", UserPlacementTest),
)

_EMPTY_COUNTS = {key: 0 for key, _ in _LEARNER_TABLES}
_EMPTY_COUNTS["clearedFlashcards"] = 0


def empty_counts() -> dict:
    """A zeroed counts dict, for callers that reset nobody."""
    return dict(_EMPTY_COUNTS)


def reset_learners(
    db: Session, user_ids: list[int], *, clear_flashcards: bool = True
) -> dict:
    """Wipe every learner-owned row for `user_ids` and unenrol them.

    One bulk DELETE per table rather than per user. Returns per-table
    deleted counts. Does not commit.
    """
    counts = empty_counts()
    if not user_ids:
        return counts

    for key, model in _LEARNER_TABLES:
        counts[key] = (
            db.query(model)
            .filter(model.user_id.in_(user_ids))
            .delete(synchronize_session=False)
        )

    if clear_flashcards:
        counts["clearedFlashcards"] = (
            db.query(UserFlashcard)
            .filter(UserFlashcard.user_id.in_(user_ids))
            .delete(synchronize_session=False)
        )

    db.query(User).filter(User.id.in_(user_ids)).update(
        {User.job_role_id: None, User.learning_status: LEARNING_NONE},
        synchronize_session=False,
    )
    return counts


def reset_learner(db: Session, user: User, *, clear_flashcards: bool = True) -> dict:
    """Wipe every learner-owned row for one user and unenrol them.

    Returns per-table deleted counts. Does not commit.
    """
    counts = reset_learners(db, [user.id], clear_flashcards=clear_flashcards)
    # Keep the caller's in-session instance consistent with the bulk UPDATE.
    user.job_role_id = None
    user.learning_status = LEARNING_NONE
    return counts
