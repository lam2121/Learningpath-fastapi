"""User management — list, role assignment, reset, and deletion.

Extracted from admin_service.py for single-responsibility.
"""

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.domain.learner_reset import reset_learner
from app.feature.admin.admin_schema import (
    AdminUserListResponse,
    AdminUserResponse,
    ResetLearnerResponse,
)
from app.models.generation import RoleGeneration
from app.models.job_role import JobRole
from app.models.lesson import Lesson
from app.models.placement_test_question import PlacementTestQuestion
from app.models.topic import Topic
from app.models.user import ADMIN_ROLE_ID, LEARNING_ENROLLED, LEARNING_NONE, User
from app.models.user_final_quiz import UserFinalQuiz
from app.models.user_flashcard import UserFlashcard
from app.models.user_lesson import UserLesson
from app.models.user_placement_test import UserPlacementTest
from app.models.user_roadmap import UserRoadmap
from app.models.user_topic_quiz import UserTopicQuiz

# ─── Users ───────────────────────────────────────────────────────────────────


def get_user_or_404(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user


def _guard_not_self(user_id: int, admin_id: int, action: str) -> None:
    if user_id == admin_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You cannot {action} your own account.",
        )


def _learning_state_for(db: Session, users: list[User]) -> dict[int, dict]:
    """Per-user learning metrics for a page of users.

    One grouped query per metric over the whole page rather than a query per
    user, then assembled in Python.
    """
    user_ids = [u.id for u in users]
    if not user_ids:
        return {}

    role_names = dict(db.query(JobRole.id, JobRole.name).all())

    def _counts(model, *extra_filters) -> dict[int, int]:
        query = db.query(model.user_id, func.count(model.id)).filter(
            model.user_id.in_(user_ids), *extra_filters
        )
        return dict(query.group_by(model.user_id).all())

    lessons_completed = _counts(UserLesson, UserLesson.status == "completed")
    lessons_total = _counts(UserLesson)
    topic_quizzes_passed = _counts(UserTopicQuiz, UserTopicQuiz.status == "passed")
    flashcard_counts = _counts(UserFlashcard)
    final_quiz_status = dict(
        db.query(UserFinalQuiz.user_id, UserFinalQuiz.status)
        .filter(UserFinalQuiz.user_id.in_(user_ids))
        .all()
    )
    answered_ids = {
        uid
        for (uid,) in db.query(UserPlacementTest.user_id)
        .filter(UserPlacementTest.user_id.in_(user_ids))
        .distinct()
    }

    return {
        u.id: {
            "jobRoleId": u.job_role_id,
            "jobRoleName": role_names.get(u.job_role_id),
            "learningStatus": u.learning_status,
            "lessonsCompleted": lessons_completed.get(u.id, 0),
            "lessonsTotal": lessons_total.get(u.id, 0),
            "topicQuizzesPassed": topic_quizzes_passed.get(u.id, 0),
            "finalQuizStatus": final_quiz_status.get(u.id),
            "flashcardCount": flashcard_counts.get(u.id, 0),
            "hasPlacementAnswers": u.id in answered_ids,
        }
        for u in users
    }


def list_users(
    db: Session,
    *,
    search: str | None = None,
    role: str | None = None,
    limit: int,
    offset: int,
) -> AdminUserListResponse:
    """Paginated CareerPath roster.

    Lists `toeic_learningpath.user` only — the shared `auth_db` is never read
    here, so this shows exactly the people who have signed into CareerPath.
    """
    query = db.query(User)

    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(or_(User.name.like(pattern), User.email.like(pattern)))
    if role:
        normalized = role.strip().lower()
        if normalized == "admin":
            query = query.filter(User.role_id == ADMIN_ROLE_ID)
        elif normalized == "employee":
            query = query.filter(
                or_(User.role_id != ADMIN_ROLE_ID, User.role_id.is_(None))
            )

    total = query.count()
    users = (
        query.order_by(User.created_at.desc(), User.id.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    states = _learning_state_for(db, users)

    return AdminUserListResponse(
        items=[
            AdminUserResponse(
                id=u.id,
                name=u.name,
                email=u.email,
                roleId=u.role_id,
                createdAt=u.created_at,
                **states[u.id],
            )
            for u in users
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def set_user_role(
    db: Session, user_id: int, role_id: int, *, admin_id: int
) -> AdminUserResponse:
    """Grant or revoke CareerPath admin.

    Roles are managed centrally by the Auth Service (Single Source of Truth).
    Changing role locally would be overwritten on the target user's next request.
    """
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Quyền người dùng được quản lý tập trung bởi Auth Service. Vui lòng thay đổi vai trò của người dùng tại hệ thống quản trị Auth Service.",
    )


def reset_single_learner(
    db: Session, user_id: int, *, clear_flashcards: bool, admin_id: int
) -> ResetLearnerResponse:
    _guard_not_self(user_id, admin_id, "reset")
    user = get_user_or_404(db, user_id)

    counts = reset_learner(db, user, clear_flashcards=clear_flashcards)
    db.commit()
    return ResetLearnerResponse(userId=user_id, **counts)


def delete_user_learning_data(db: Session, user_id: int, *, admin_id: int) -> None:
    """Remove a user from CareerPath: all learner rows plus the local profile.

    The shared `auth_db` account is deliberately untouched — it belongs to other
    platform apps too. The person can still sign in, and is re-provisioned as a fresh
    learner (`role_id = LEARNER_ROLE_ID`, no progress) if they do.

    Idempotent: a user id with no CareerPath row is a no-op.
    `job_role.created_by` is ON DELETE SET NULL, so tracks they authored survive.
    """
    _guard_not_self(user_id, admin_id, "delete")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return

    if user.role_id == ADMIN_ROLE_ID:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Demote this admin to learner before removing them.",
        )

    reset_learner(db, user, clear_flashcards=True)
    db.delete(user)
    db.commit()





