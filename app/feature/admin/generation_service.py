"""Generation management — kickoff, status, and stale-generation handling.

Extracted from admin_service.py for single-responsibility.
"""

from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.ai.client.gemini import AI_GENERATION_ENABLED_KEY, generation_enabled
from app.core.domain.learner_reset import reset_learner, reset_learners
from app.core.infra.config import app_config
from app.feature.admin.role_service import (
    count_active_learners,
    get_role_or_404,
    _role_to_response,
    _course_counts,
    _workflow_for_step,
    _latest_generation_for_workflow,
    _latest_active_generation,
    _workflow_status,
    _mark_stale_generation,
    mark_stale_generations_all,
    has_saved_answers,
    get_placement_question_count,
    STALE_GENERATION_MINUTES,
)
from app.feature.admin.moderation_service import get_kill_switch
from app.feature.admin.admin_schema import (
    GenerationActiveJobResponse,
    GenerationBlockersResponse,
    GenerationStatusResponse,
    GenerationSummaryResponse,
    CourseGenerationSummaryResponse,
    PlacementGenerationSummaryResponse,
    PreviewResponse,
    ResetLearnerResponse,
    RoleSkillDefinitions,
)
from app.models.generation import RoleGeneration
from app.models.job_role import JobRole
from app.models.lesson import Lesson
from app.models.placement_test_question import PlacementTestQuestion
from app.models.rejected_content import RejectedContent
from app.models.topic import Topic
from app.models.user import LEARNING_ENROLLED, LEARNING_NONE, User
from app.models.user_final_quiz import UserFinalQuiz
from app.models.user_flashcard import UserFlashcard
from app.models.user_lesson import UserLesson
from app.models.user_placement_test import UserPlacementTest
from app.models.user_roadmap import UserRoadmap
from app.models.user_topic_quiz import UserTopicQuiz

PLACEMENT_TARGET_COUNT = app_config.NUM_PLACEMENT_QUESTIONS_PER_SKILL * 4  # 4 skills
COURSE_TARGET_TOPICS = app_config.NUM_TOPICS_PER_ROLE
COURSE_TARGET_LESSONS = COURSE_TARGET_TOPICS * app_config.NUM_LESSONS_PER_TOPIC

# ─── Generation (Generator A) ────────────────────────────────────────────────


def kickoff_generation(db: Session, role_id: int, force: bool = False) -> dict:
    get_role_or_404(db, role_id, for_update=True)
    if not generation_enabled(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "AI generation is disabled (kill switch ON). Enable it on the "
                "Kill Switch page before generating."
            ),
        )
    _mark_stale_generation(db, role_id)

    latest = (
        db.query(RoleGeneration)
        .filter(RoleGeneration.role_id == role_id)
        .order_by(RoleGeneration.id.desc())
        .first()
    )
    if latest and latest.status in ("in_progress", "pending"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Generation is already {latest.status} for this role.",
        )

    question_count = get_placement_question_count(db, role_id)
    if question_count > 0 and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Role already has {question_count} placement questions. "
                "Pass force=true to regenerate (replaces the existing pool)."
            ),
        )

    saved = has_saved_answers(db, role_id)
    if saved > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{saved} saved learner answer(s) reference this role's questions. "
                "Reset learners for this role before regenerating."
            ),
        )

    # Reserve the run synchronously so a second concurrent POST sees it.
    db.add(
        RoleGeneration(
            role_id=role_id,
            status="in_progress",
            step="a",
            started_at=datetime.utcnow(),
        )
    )
    db.commit()

    return {"message": "Placement generation started", "roleId": role_id}


def kickoff_course_generation(
    db: Session, role_id: int, force: bool = False, resume: bool = False
) -> dict:
    """Start a B1+B2 course-outline generation (20 topics + 120 lesson shells).

    Guard rails mirror Generator A, including a **reset-learners gate** (docs/07
    deviation #23): the course outline feeds each enrolled learner's `user_roadmap`
    (FK CASCADE), so regenerating it would silently replace their roadmap rows and
    destroy any lazily-generated lesson content. The admin must reset learners
    (clears placement answers + roadmap + enrollment) before regenerating.

    `resume=true` picks up a failed/partial run (docs/07 deviation #28): existing
    topics are kept, B-1 is skipped, and the background job regenerates only the
    lesson shells still missing. It is the non-destructive complement to `force`
    (which wipes and regenerates the whole outline) — the two are mutually exclusive.
    """
    if force and resume:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="force and resume are mutually exclusive; pass only one.",
        )
    get_role_or_404(db, role_id, for_update=True)
    if not generation_enabled(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "AI generation is disabled (kill switch ON). Enable it on the "
                "Kill Switch page before generating."
            ),
        )
    _mark_stale_generation(db, role_id)

    latest = (
        db.query(RoleGeneration)
        .filter(RoleGeneration.role_id == role_id)
        .order_by(RoleGeneration.id.desc())
        .first()
    )
    if latest and latest.status in ("in_progress", "pending"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Generation is already {latest.status} for this role.",
        )

    active_learners = count_active_learners(db, role_id)
    if active_learners > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{active_learners} active learner(s) are enrolled on this role. "
                "Reset learners for this role before regenerating the course outline."
            ),
        )

    topic_count = db.query(Topic).filter(Topic.role_id == role_id).count()
    if topic_count > 0 and not force and not resume:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Role already has {topic_count} topics. Pass force=true to "
                "regenerate (replaces the existing course outline), or resume=true "
                "to finish a partial run (keeps existing topics)."
            ),
        )

    # Reserve the run synchronously so a second concurrent POST sees it.
    db.add(
        RoleGeneration(
            role_id=role_id,
            status="in_progress",
            step="b2" if resume else "b1",
            started_at=datetime.utcnow(),
        )
    )
    db.commit()

    return {"message": "Course generation started", "roleId": role_id}


def kickoff_more_topics_generation(
    db: Session, role_id: int, skill: str, count: int
) -> dict:
    """Start an additive run: `count` extra topics of one skill + their lesson shells.

    Unlike `kickoff_course_generation` there is **no reset-learners gate**: the
    run only inserts rows, so enrolled learners keep their existing
    `user_roadmap` untouched. It does require a complete outline to extend —
    a half-built one must be finished with resume first, otherwise this run's
    "completed" status would hide the missing lesson shells.
    """
    get_role_or_404(db, role_id, for_update=True)
    if not generation_enabled(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "AI generation is disabled (kill switch ON). Enable it on the "
                "Kill Switch page before generating."
            ),
        )
    _mark_stale_generation(db, role_id)

    latest = (
        db.query(RoleGeneration)
        .filter(RoleGeneration.role_id == role_id)
        .order_by(RoleGeneration.id.desc())
        .first()
    )
    if latest and latest.status in ("in_progress", "pending"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Generation is already {latest.status} for this role.",
        )

    topics_count, lessons_count = _course_counts(db, role_id)
    if topics_count == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This role has no course outline yet. Generate the course "
                "outline before adding more topics."
            ),
        )
    if lessons_count < topics_count * app_config.NUM_LESSONS_PER_TOPIC:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The course outline is incomplete (some topics are missing "
                "lesson shells). Resume or regenerate it before adding more topics."
            ),
        )

    # Reserve the run synchronously so a second concurrent POST sees it.
    db.add(
        RoleGeneration(
            role_id=role_id,
            status="in_progress",
            step="b1",
            started_at=datetime.utcnow(),
        )
    )
    db.commit()

    return {
        "message": f"Generating {count} more topic(s) for {skill}",
        "roleId": role_id,
    }


def kickoff_lesson_generation(
    db: Session, lesson_id: int, force: bool = False, resume: bool = False
) -> dict:
    """Validate a lazy C-1 (theory) + C-2 (quiz) generation for one lesson.

    Supports `resume=True` to continue from failed attempts, keeping already generated
    theory content intact to minimize token usage.
    """
    lesson = db.query(Lesson).filter(Lesson.id == lesson_id).first()
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found.")

    topic = db.query(Topic).filter(Topic.id == lesson.topic_id).first()
    if topic is None or not topic.role_id:
        raise HTTPException(
            status_code=404,
            detail="Lesson has no parent topic/role; cannot generate content.",
        )
    role_id = topic.role_id

    if not generation_enabled(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "AI generation is disabled (kill switch ON). Enable it on the "
                "Kill Switch page before generating."
            ),
        )

    from app.core.ai.dispatch.validators import validate_theory_content

    has_valid_theory = False
    if isinstance(lesson.theory_content, dict):
        val_res = validate_theory_content(lesson.theory_content)
        if val_res.get("ok"):
            has_valid_theory = True

    if lesson.is_generated == 1 and has_valid_theory and lesson.quiz_content and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This lesson is already generated (shared — reused by all "
                "learners of the role). Pass force=true to regenerate "
                "(~$0.05, replaces theory + quiz)."
            ),
        )

    if force and not resume:
        lesson.theory_content = None
        lesson.quiz_content = None
        lesson.estimated_minutes = None
        lesson.is_generated = 0
        db.commit()

    msg = (
        "Resuming lesson generation (reusing theory, generating quiz only to save tokens)"
        if (resume and has_valid_theory)
        else "Lesson content generation started (C1 theory -> C2 quiz)"
    )

    return {
        "message": msg,
        "roleId": role_id,
        "hasTheory": has_valid_theory,
    }


def list_failed_lessons(db: Session) -> list[dict]:
    """Retrieve all lessons where generation failed (is_generated == -1)."""
    rows = (
        db.query(Lesson, Topic, JobRole)
        .join(Topic, Lesson.topic_id == Topic.id)
        .join(JobRole, Topic.role_id == JobRole.id)
        .filter(Lesson.is_generated == -1)
        .order_by(Lesson.id.desc())
        .all()
    )
    from app.core.ai.dispatch.validators import validate_theory_content

    result = []
    for lesson, topic, role in rows:
        has_partial = False
        if isinstance(lesson.theory_content, dict):
            val = validate_theory_content(lesson.theory_content)
            has_partial = bool(val.get("ok"))

        rej = (
            db.query(RejectedContent)
            .filter(
                RejectedContent.role_id == role.id,
                RejectedContent.input_preview.like(f"%lesson_id={lesson.id}%"),
            )
            .order_by(RejectedContent.id.desc())
            .first()
        )
        err_msg = rej.error if rej else ("Quiz generation failed" if has_partial else "Theory generation failed")

        result.append(
            {
                "id": lesson.id,
                "title": lesson.title,
                "primary_skill": lesson.primary_skill,
                "difficulty_tier": lesson.difficulty_tier,
                "topic_id": topic.id,
                "topic_name": topic.name,
                "role_id": role.id,
                "role_name": role.name,
                "has_partial_theory": has_partial,
                "failed_step": "C2" if has_partial else "C1",
                "error_message": err_msg,
                "created_at": rej.created_at if rej else None,
            }
        )
    return result


def reset_role_learners(db: Session, role_id: int) -> dict:
    """De-enroll every learner touched by a role (docs/07 deviation #23).

    Wipes all learner-owned rows via `reset_learner` and resets
    `learning_status`/`job_role_id` so the admin can regenerate the placement
    questions or the course outline. Topics/lessons — the role-level curriculum
    — are left untouched; only learner-owned rows are removed.

    The affected set is the union of learners enrolled in the role, learners
    holding answers to the role's placement questions, and learners with a
    roadmap on the role's topics. Answers and roadmaps are exactly what block
    regeneration, and they can outlive an enrollment (a learner who took the
    test but never enrolled), so an enrolled-only sweep would leave the gate
    stuck.
    """
    get_role_or_404(db, role_id)

    enrolled_ids = {
        uid
        for (uid,) in db.query(User.id).filter(
            User.job_role_id == role_id,
            User.learning_status == LEARNING_ENROLLED,
        )
    }
    answered_ids = {
        uid
        for (uid,) in db.query(UserPlacementTest.user_id)
        .join(
            PlacementTestQuestion,
            PlacementTestQuestion.id == UserPlacementTest.placement_test_question_id,
        )
        .filter(PlacementTestQuestion.job_role_id == role_id)
        .distinct()
    }
    roadmapped_ids = {
        uid
        for (uid,) in db.query(UserRoadmap.user_id)
        .join(Topic, Topic.id == UserRoadmap.topic_id)
        .filter(Topic.role_id == role_id)
        .distinct()
    }

    user_ids = sorted(enrolled_ids | answered_ids | roadmapped_ids)
    counts = reset_learners(db, user_ids, clear_flashcards=False)
    db.commit()

    return {"resetLearners": len(user_ids), **counts}


def get_generation_status(db: Session, role_id: int) -> GenerationStatusResponse:
    get_role_or_404(db, role_id)
    _mark_stale_generation(db, role_id)
    gen = (
        db.query(RoleGeneration)
        .filter(RoleGeneration.role_id == role_id)
        .order_by(RoleGeneration.id.desc())
        .first()
    )
    if gen is None:
        return GenerationStatusResponse(
            roleId=role_id,
            status="pending",
            step="a",
            stepACount=0,
            stepAErrors=0,
        )
    return GenerationStatusResponse(
        roleId=role_id,
        status=gen.status,
        step=gen.step,
        stepACount=gen.step_a_count,
        stepAErrors=gen.step_a_errors,
        stepB1Count=gen.step_b1_count,
        stepB1Errors=gen.step_b1_errors,
        stepB2Count=gen.step_b2_count,
        stepB2Errors=gen.step_b2_errors,
        startedAt=gen.started_at,
        finishedAt=gen.finished_at,
        errorMessage=gen.error_message,
    )


def get_generation_summary(db: Session, role_id: int) -> GenerationSummaryResponse:
    get_role_or_404(db, role_id)
    _mark_stale_generation(db, role_id)

    placement_questions_count = get_placement_question_count(db, role_id)
    topics_count, lessons_count = _course_counts(db, role_id)
    placement_gen = _latest_generation_for_workflow(db, role_id, "placement")
    course_gen = _latest_generation_for_workflow(db, role_id, "course")
    active_gen = _latest_active_generation(db, role_id)
    kill_switch = get_kill_switch(db)
    active_learners = count_active_learners(db, role_id)
    saved_answers = has_saved_answers(db, role_id)

    placement_status = _workflow_status(
        placement_gen,
        has_assets=placement_questions_count > 0,
        target_met=placement_questions_count >= PLACEMENT_TARGET_COUNT,
    )
    course_status = _workflow_status(
        course_gen,
        has_assets=topics_count > 0 or lessons_count > 0,
        target_met=(
            topics_count >= COURSE_TARGET_TOPICS
            and lessons_count >= COURSE_TARGET_LESSONS
        ),
    )

    return GenerationSummaryResponse(
        roleId=role_id,
        activeJob=GenerationActiveJobResponse(
            workflow=_workflow_for_step(active_gen.step) if active_gen else None,
            status=active_gen.status if active_gen else None,
            step=active_gen.step if active_gen else None,
            startedAt=active_gen.started_at if active_gen else None,
            finishedAt=active_gen.finished_at if active_gen else None,
        ),
        placement=PlacementGenerationSummaryResponse(
            questionCount=placement_questions_count,
            targetCount=PLACEMENT_TARGET_COUNT,
            lastStatus=placement_status,
            lastStartedAt=placement_gen.started_at if placement_gen else None,
            lastFinishedAt=placement_gen.finished_at if placement_gen else None,
            lastErrorMessage=placement_gen.error_message if placement_gen else None,
        ),
        course=CourseGenerationSummaryResponse(
            topicsCount=topics_count,
            targetTopics=COURSE_TARGET_TOPICS,
            lessonsCount=lessons_count,
            targetLessons=COURSE_TARGET_LESSONS,
            currentStep=course_gen.step if course_gen else None,
            lastStatus=course_status,
            lastStartedAt=course_gen.started_at if course_gen else None,
            lastFinishedAt=course_gen.finished_at if course_gen else None,
            lastErrorMessage=course_gen.error_message if course_gen else None,
            stepB1Count=course_gen.step_b1_count if course_gen else 0,
            stepB1Errors=course_gen.step_b1_errors if course_gen else 0,
            stepB2Count=course_gen.step_b2_count if course_gen else 0,
            stepB2Errors=course_gen.step_b2_errors if course_gen else 0,
        ),
        blockers=GenerationBlockersResponse(
            killSwitchOn=kill_switch.enabled,
            killSwitchReason=kill_switch.reason,
            activeLearnerCount=active_learners,
            requiresLearnerResetForPlacement=saved_answers > 0,
            requiresLearnerResetForCourse=active_learners > 0,
        ),
    )


def preview_generation(
    job_description: str, skill_definitions: RoleSkillDefinitions
) -> PreviewResponse:
    raw_descriptions = [
        skill_definitions.D_doc.description,
        skill_definitions.C_comm.description,
        skill_definitions.T_trouble.description,
        skill_definitions.G_custom.description,
    ]
    descriptions = [
        d if isinstance(d, str) else (d.get("en") or next(iter(d.values()), ""))
        for d in raw_descriptions
    ]
    is_vague = any(
        len(description) < 50
        or "work with" in description.lower()
        or " job" in description.lower()
        for description in descriptions
    )
    if is_vague:
        return PreviewResponse(
            examples=[
                "Work with data to analyze trends.",
                "Communicate with team to understand requirements.",
                "Write periodic reports for management.",
            ],
            warning=(
                "One or more skill definitions are too generic. AI may generate "
                "non-specialized examples. Please add specific technical keywords."
            ),
        )
    return PreviewResponse(
        examples=[
            f"Based on JD: {job_description[:80]}...",
            "Example 1: Scope creep appears mid-sprint -> clarify impact before committing.",
            "Example 2: Stakeholder gives vague requirement -> elicit details with targeted questions.",
            "Example 3: Production incident -> write a clear, blameless status update.",
        ]
    )



