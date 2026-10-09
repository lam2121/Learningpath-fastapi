"""Role management — CRUD, serialization helpers, and baseline logic.

Extracted from admin_service.py for single-responsibility.
"""

"""Business logic for the admin portal (v2.1).

Role CRUD, Generator A kickoff/status, dashboard, AI costs, rejected content,
and the kill switch.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.ai.client.gemini import (
    AI_GENERATION_ENABLED_KEY,
    GeminiClientPool,
    generation_enabled,
    get_gemini_client_pool,
)
from app.core.domain.learner_reset import reset_learner, reset_learners
from app.core.infra.config import app_config

logger = logging.getLogger(__name__)
from app.feature.admin.admin_schema import (
    AdminUserListResponse,
    AdminUserResponse,
    AiUsageLogResponse,
    Baseline,
    CostAlert,
    CostBucket,
    CostDashboardData,
    CostGroup,
    CourseGenerationSummaryResponse,
    DashboardData,
    GenerationActiveJobResponse,
    GenerationBlockersResponse,
    GenerationStatusResponse,
    GenerationSummaryResponse,
    KillSwitchState,
    PlacementGenerationSummaryResponse,
    PreviewResponse,
    RejectedContentResponse,
    ResetLearnerResponse,
    RoleCreate,
    RoleResponse,
    RoleSkillDefinitions,
    RoleUpdate,
    SkillDefinition,
    UsageLogClearRequest,
    UsageLogClearResponse,
)
from app.models.ai_usage_log import AiUsageLog
from app.models.generation import RoleGeneration
from app.models.job_role import (
    DEFAULT_BASELINE,
    DEFAULT_SKILL_DESCRIPTIONS,
    JobRole,
    default_skill_definitions,
    get_job_description_dict,
    get_job_description_text,
)
from app.models.lesson import Lesson
from app.models.placement_test_question import PlacementTestQuestion
from app.models.rejected_content import RejectedContent
from app.models.system_setting import SystemSetting
from app.models.topic import Topic
from app.models.user import (
    ADMIN_ROLE_ID,
    LEARNING_ENROLLED,
    LEARNING_NONE,
    User,
)
from app.models.user_final_quiz import UserFinalQuiz
from app.models.user_flashcard import UserFlashcard
from app.models.user_lesson import UserLesson
from app.models.user_placement_test import UserPlacementTest
from app.models.user_roadmap import UserRoadmap
from app.models.user_topic_quiz import UserTopicQuiz

PLACEMENT_TARGET_COUNT = app_config.NUM_PLACEMENT_QUESTIONS_PER_SKILL * 4  # 4 skills
COURSE_TARGET_TOPICS = app_config.NUM_TOPICS_PER_ROLE
COURSE_TARGET_LESSONS = COURSE_TARGET_TOPICS * app_config.NUM_LESSONS_PER_TOPIC
STALE_GENERATION_MINUTES = app_config.STALE_GENERATION_MINUTES


def _mark_stale_generation(db: Session, role_id: int) -> None:
    """Recover jobs that were left 'in_progress' by a crashed worker."""
    stale = (
        db.query(RoleGeneration)
        .filter(
            RoleGeneration.role_id == role_id,
            RoleGeneration.status.in_(["in_progress", "pending"]),
            RoleGeneration.started_at.isnot(None),
            RoleGeneration.started_at
            < datetime.utcnow() - timedelta(minutes=STALE_GENERATION_MINUTES),
        )
        .all()
    )
    for gen in stale:
        gen.status = "failed"
        gen.error_message = "Marked failed: generation did not finish within timeout"
        gen.finished_at = datetime.utcnow()
    if stale:
        db.commit()


def mark_stale_generations_all(db: Session) -> int:
    """Recover all jobs that were left 'in_progress' or 'pending' across all roles."""
    stale = (
        db.query(RoleGeneration)
        .filter(
            RoleGeneration.status.in_(["in_progress", "pending"]),
            RoleGeneration.started_at.isnot(None),
            RoleGeneration.started_at
            < datetime.utcnow() - timedelta(minutes=STALE_GENERATION_MINUTES),
        )
        .all()
    )
    for gen in stale:
        gen.status = "failed"
        gen.error_message = "Marked failed: generation did not finish within timeout"
        gen.finished_at = datetime.utcnow()
    if stale:
        db.commit()
    return len(stale)


def has_saved_answers(db: Session, role_id: int) -> int:
    """Number of learner answers that reference this role's questions."""
    return (
        db.query(UserPlacementTest.id)
        .join(
            PlacementTestQuestion,
            UserPlacementTest.placement_test_question_id == PlacementTestQuestion.id,
        )
        .filter(PlacementTestQuestion.job_role_id == role_id)
        .count()
    )


def get_placement_question_count(db: Session, role_id: int) -> int:
    return (
        db.query(PlacementTestQuestion)
        .filter(PlacementTestQuestion.job_role_id == role_id)
        .count()
    )


# ─── Serialization helpers ───────────────────────────────────────────────────


def count_active_learners(db: Session, role_id: int) -> int:
    """Number of learners actively enrolled on a role.

    `learning_status == 'enrolled'` is set only when a learner completes the
    placement test (or the dev-mode skills override) together with
    `job_role_id` — it is the single source of truth for "active learner",
    replacing the old `is_finished_placement_test` proxy (docs/07 deviation #23).
    """
    return (
        db.query(User)
        .filter(
            User.job_role_id == role_id,
            User.learning_status == LEARNING_ENROLLED,
        )
        .count()
    )


def _baseline(role: JobRole) -> Baseline:
    blob = role.baseline or DEFAULT_BASELINE
    return Baseline(
        D_doc=int(blob.get("D_doc", DEFAULT_BASELINE["D_doc"])),
        C_comm=int(blob.get("C_comm", DEFAULT_BASELINE["C_comm"])),
        T_trouble=int(blob.get("T_trouble", DEFAULT_BASELINE["T_trouble"])),
        G_custom=int(blob.get("G_custom", DEFAULT_BASELINE["G_custom"])),
    )


def _baseline_blob(baseline: Baseline) -> dict:
    return {
        "D_doc": baseline.D_doc,
        "C_comm": baseline.C_comm,
        "T_trouble": baseline.T_trouble,
        "G_custom": baseline.G_custom,
    }


def _skill_definitions(role: JobRole) -> RoleSkillDefinitions:
    blob = role.skill_definitions or default_skill_definitions()

    def _definition(skill: str) -> SkillDefinition:
        item = blob.get(skill) or {}
        raw_desc = item.get("description", "")
        if isinstance(raw_desc, dict):
            description = {k: str(v).strip() for k, v in raw_desc.items() if str(v).strip()}
            if not description:
                description = DEFAULT_SKILL_DESCRIPTIONS[skill]
        else:
            description = str(raw_desc).strip()
            if not description:
                description = DEFAULT_SKILL_DESCRIPTIONS[skill]
        examples = item.get("example_questions") or []
        if not isinstance(examples, list):
            examples = []
        return SkillDefinition(
            description=description,
            example_questions=[q.strip() for q in examples if q and q.strip()],
        )

    return RoleSkillDefinitions(
        D_doc=_definition("D_doc"),
        C_comm=_definition("C_comm"),
        T_trouble=_definition("T_trouble"),
        G_custom=_definition("G_custom"),
    )


def _skill_definitions_blob(
    skill_definitions: RoleSkillDefinitions,
) -> dict[str, dict[str, Any]]:
    return {
        skill: {
            "description": getattr(skill_definitions, skill).description,
            "example_questions": list(
                getattr(skill_definitions, skill).example_questions
            ),
        }
        for skill in DEFAULT_SKILL_DESCRIPTIONS
    }


def _workflow_for_step(step: str | None) -> str | None:
    if step == "a":
        return "placement"
    if step in {"b1", "b2"}:
        return "course"
    return None


def _latest_generation_for_workflow(
    db: Session, role_id: int, workflow: str
) -> RoleGeneration | None:
    query = db.query(RoleGeneration).filter(RoleGeneration.role_id == role_id)
    if workflow == "placement":
        query = query.filter(RoleGeneration.step == "a")
    else:
        query = query.filter(RoleGeneration.step.in_(["b1", "b2"]))
    return query.order_by(RoleGeneration.id.desc()).first()


def _latest_active_generation(db: Session, role_id: int) -> RoleGeneration | None:
    return (
        db.query(RoleGeneration)
        .filter(
            RoleGeneration.role_id == role_id,
            RoleGeneration.status.in_(["in_progress", "pending"]),
        )
        .order_by(RoleGeneration.id.desc())
        .first()
    )


def _workflow_status(
    latest: RoleGeneration | None, *, has_assets: bool, target_met: bool
) -> str:
    if latest is not None:
        if latest.status in {"in_progress", "pending", "failed"}:
            return latest.status
        if latest.status == "completed":
            return "completed" if (target_met or has_assets) else "empty"
    return "completed" if has_assets else "empty"


def _course_counts(db: Session, role_id: int) -> tuple[int, int]:
    topics_count = db.query(Topic).filter(Topic.role_id == role_id).count()
    lessons_count = (
        db.query(Lesson)
        .join(Topic, Lesson.topic_id == Topic.id)
        .filter(Topic.role_id == role_id)
        .count()
    )
    return topics_count, lessons_count


def _role_to_response(db: Session, role: JobRole) -> RoleResponse:
    active_learners = count_active_learners(db, role.id)
    _mark_stale_generation(db, role.id)
    gen = (
        db.query(RoleGeneration)
        .filter(RoleGeneration.role_id == role.id)
        .order_by(RoleGeneration.id.desc())
        .first()
    )
    placement_questions_count = get_placement_question_count(db, role.id)
    topics_count, lessons_count = _course_counts(db, role.id)
    placement_gen = _latest_generation_for_workflow(db, role.id, "placement")
    course_gen = _latest_generation_for_workflow(db, role.id, "course")
    return RoleResponse(
        id=role.id,
        name=role.name,
        jobDescription=get_job_description_text(role.job_description, "en"),
        baseline=_baseline(role),
        skillDefinitions=_skill_definitions(role),
        seedTier1=role.seed_tier_1 or "",
        seedTier2=role.seed_tier_2 or "",
        isActive=role.is_active,
        createdBy=role.created_by,
        activeLearnerCount=active_learners,
        placementQuestionsCount=placement_questions_count,
        topicsCount=topics_count,
        lessonsCount=lessons_count,
        generationStatus=gen.status if gen else None,
        placementGenerationStatus=_workflow_status(
            placement_gen,
            has_assets=placement_questions_count > 0,
            target_met=placement_questions_count >= PLACEMENT_TARGET_COUNT,
        ),
        courseGenerationStatus=_workflow_status(
            course_gen,
            has_assets=topics_count > 0 or lessons_count > 0,
            target_met=(
                topics_count >= COURSE_TARGET_TOPICS
                and lessons_count >= COURSE_TARGET_LESSONS
            ),
        ),
    )


def _apply_role_payload(role: JobRole, payload: RoleCreate | RoleUpdate) -> None:
    role.name = payload.name if payload.name is not None else role.name
    if payload.baseline is not None:
        role.baseline = _baseline_blob(payload.baseline)
    if payload.skill_definitions is not None:
        role.skill_definitions = _skill_definitions_blob(payload.skill_definitions)
    role.seed_tier_1 = (
        payload.seed_tier_1 if payload.seed_tier_1 is not None else role.seed_tier_1
    )
    role.seed_tier_2 = (
        payload.seed_tier_2 if payload.seed_tier_2 is not None else role.seed_tier_2
    )
    if isinstance(payload, RoleUpdate) and payload.is_active is not None:
        role.is_active = payload.is_active


# ─── Roles ───────────────────────────────────────────────────────────────────


def get_role_or_404(db: Session, role_id: int, for_update: bool = False) -> JobRole:
    query = db.query(JobRole).filter(JobRole.id == role_id)
    if for_update:
        query = query.with_for_update()
    role = query.first()
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Role not found"
        )
    return role


def list_roles(db: Session) -> list[RoleResponse]:
    roles = db.query(JobRole).order_by(JobRole.name.asc()).all()
    return [_role_to_response(db, r) for r in roles]


def get_role(db: Session, role_id: int) -> RoleResponse:
    return _role_to_response(db, get_role_or_404(db, role_id))


async def auto_translate_skill_definitions(
    role_name: str,
    new_defs_blob: dict[str, Any],
    existing_defs_blob: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ensure every skill in new_defs_blob has localized description {'en': ..., 'vi': ..., 'jp': ...}.

    If description is a string (e.g. from the admin UI), or if the English text
    has changed compared to existing_defs_blob, automatically calls Gemini to translate
    into natural IT Vietnamese and Japanese.
    """
    skills_to_translate: dict[str, str] = {}
    updated_defs: dict[str, Any] = {}

    for skill in ("D_doc", "C_comm", "T_trouble", "G_custom"):
        item = dict(new_defs_blob.get(skill) or {})
        existing_item = dict((existing_defs_blob or {}).get(skill) or {})
        raw_desc = item.get("description", "")

        # Extract new English text
        if isinstance(raw_desc, dict):
            new_en = str(raw_desc.get("en", "")).strip()
            new_vi = str(raw_desc.get("vi", "")).strip()
            new_jp = str(raw_desc.get("jp", "")).strip()
        else:
            new_en = str(raw_desc).strip()
            new_vi = ""
            new_jp = ""

        if not new_en:
            default_val = DEFAULT_SKILL_DESCRIPTIONS.get(skill, "")
            new_en = default_val.get("en", "") if isinstance(default_val, dict) else str(default_val)

        # Extract existing translations if available
        existing_desc = existing_item.get("description")
        old_en, old_vi, old_jp = "", "", ""
        if isinstance(existing_desc, dict):
            old_en = str(existing_desc.get("en", "")).strip()
            old_vi = str(existing_desc.get("vi", "")).strip()
            old_jp = str(existing_desc.get("jp", "")).strip()
        elif isinstance(existing_desc, str):
            old_en = existing_desc.strip()

        # Check if translations already provided or reusable
        if new_vi and new_jp:
            vi_text, jp_text = new_vi, new_jp
        elif new_en == old_en and old_vi and old_jp:
            vi_text, jp_text = old_vi, old_jp
        else:
            skills_to_translate[skill] = new_en
            vi_text, jp_text = (old_vi or new_en), (old_jp or new_en)

        item["description"] = {
            "en": new_en,
            "vi": vi_text,
            "jp": jp_text,
        }
        if "example_questions" not in item:
            item["example_questions"] = []
        updated_defs[skill] = item

    if skills_to_translate:
        logger.info(
            "Auto-translating skills for role '%s': %s",
            role_name,
            list(skills_to_translate.keys()),
        )
        pool = get_gemini_client_pool()
        try:
            prompt = (
                f"You are a professional IT translator.\n"
                f"Translate the following English skill descriptions for the IT job role '{role_name}' into natural, professional Vietnamese (vi) and Japanese (jp).\n"
                f"Keep translations concise, natural, and standard for tech companies in Vietnam and Japan.\n\n"
                f"Input skills:\n{json.dumps(skills_to_translate, indent=2, ensure_ascii=False)}\n\n"
                f"Respond ONLY with a JSON object matching this schema exactly:\n"
                "{\n"
                + ",\n".join(
                    [
                        f'  "{k}": {{"vi": "Vietnamese", "jp": "Japanese"}}'
                        for k in skills_to_translate
                    ]
                )
                + "\n}"
            )
            res = await pool.generate_json(prompt, allowed_providers=["google", "mistral"])
            raw_text = res.text.strip()
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_text = "\n".join(lines).strip()

            translations = json.loads(raw_text)
            for skill, trans in translations.items():
                if skill in updated_defs and isinstance(trans, dict):
                    if trans.get("vi"):
                        updated_defs[skill]["description"]["vi"] = str(trans["vi"]).strip()
                    if trans.get("jp"):
                        updated_defs[skill]["description"]["jp"] = str(trans["jp"]).strip()
            logger.info("Auto-translation succeeded for role '%s'", role_name)
        except Exception as exc:
            logger.warning(
                "Auto-translation failed for role '%s' (%s). Kept fallback.",
                role_name,
                exc,
            )

    return updated_defs


async def auto_translate_job_description(
    role_name: str,
    new_desc: str | dict[str, Any],
    existing_desc: str | dict[str, Any] | None = None,
) -> dict[str, str]:
    """Ensure job description has localized text {'en': ..., 'vi': ..., 'jp': ...}.

    If new_desc is a string or English text has changed, calls Gemini to translate
    into natural IT Vietnamese and Japanese.
    """
    if isinstance(new_desc, dict):
        new_en = str(new_desc.get("en", "")).strip()
        new_vi = str(new_desc.get("vi", "")).strip()
        new_jp = str(new_desc.get("jp", "")).strip()
    else:
        new_str = str(new_desc).strip()
        if new_str.startswith("{") and new_str.endswith("}"):
            try:
                parsed = json.loads(new_str)
                if isinstance(parsed, dict):
                    new_en = str(parsed.get("en", "")).strip()
                    new_vi = str(parsed.get("vi", "")).strip()
                    new_jp = str(parsed.get("jp", "")).strip()
                else:
                    new_en, new_vi, new_jp = new_str, "", ""
            except Exception:
                new_en, new_vi, new_jp = new_str, "", ""
        else:
            new_en, new_vi, new_jp = new_str, "", ""

    old_dict = get_job_description_dict(existing_desc, fallback=False) if existing_desc else {}
    old_en = old_dict.get("en", "").strip()
    old_vi = old_dict.get("vi", "").strip()
    old_jp = old_dict.get("jp", "").strip()
    if old_vi == old_en:
        old_vi = ""
    if old_jp == old_en:
        old_jp = ""

    if new_vi and new_jp and new_vi != new_en and new_jp != new_en:
        return {"en": new_en, "vi": new_vi, "jp": new_jp}
    if new_en == old_en and old_vi and old_jp:
        return {"en": new_en, "vi": old_vi, "jp": old_jp}

    logger.info("Auto-translating job description for role '%s': '%s'", role_name, new_en)
    vi_text = old_vi or new_en
    jp_text = old_jp or new_en
    pool = get_gemini_client_pool()
    try:
        prompt = (
            f"You are a professional IT translator.\n"
            f"Translate the following English job description for the IT role '{role_name}' into natural, professional Vietnamese (vi) and Japanese (jp).\n"
            f"Keep translations concise, natural, and standard for tech companies in Vietnam and Japan.\n\n"
            f"English Job Description:\n\"{new_en}\"\n\n"
            f"Respond ONLY with a JSON object matching this schema exactly:\n"
            f"{{\n  \"vi\": \"Vietnamese translation\",\n  \"jp\": \"Japanese translation\"\n}}"
        )
        res = await pool.generate_json(prompt, allowed_providers=["google", "mistral"])
        raw_text = res.text.strip()
        if raw_text.startswith("```"):
            lines = raw_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw_text = "\n".join(lines).strip()
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            vi_text = str(parsed.get("vi", vi_text)).strip() or vi_text
            jp_text = str(parsed.get("jp", jp_text)).strip() or jp_text
            logger.info("Successfully translated job description for '%s'", role_name)
    except Exception as exc:
        logger.warning("Failed to auto-translate job description for '%s': %s", role_name, exc)

    return {"en": new_en, "vi": vi_text, "jp": jp_text}


async def create_role(db: Session, payload: RoleCreate, created_by: int) -> RoleResponse:
    raw_defs = _skill_definitions_blob(payload.skill_definitions)
    translated_defs = await auto_translate_skill_definitions(payload.name, raw_defs)
    translated_jd = await auto_translate_job_description(payload.name, payload.job_description)
    role = JobRole(
        name=payload.name,
        job_description=json.dumps(translated_jd, ensure_ascii=False),
        baseline=_baseline_blob(payload.baseline),
        skill_definitions=translated_defs,
        seed_tier_1=payload.seed_tier_1,
        seed_tier_2=payload.seed_tier_2,
        is_active=True,
        created_by=created_by,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return _role_to_response(db, role)


async def update_role(db: Session, role_id: int, payload: RoleUpdate) -> RoleResponse:
    role = get_role_or_404(db, role_id)
    previous_defs = dict(role.skill_definitions or {})
    previous_jd = role.job_description
    _apply_role_payload(role, payload)

    if payload.job_description is not None:
        translated_jd = await auto_translate_job_description(
            payload.name or role.name,
            payload.job_description,
            existing_desc=previous_jd,
        )
        role.job_description = json.dumps(translated_jd, ensure_ascii=False)

    if payload.skill_definitions is not None:
        raw_defs = _skill_definitions_blob(payload.skill_definitions)
        translated_defs = await auto_translate_skill_definitions(
            role.name, raw_defs, existing_defs_blob=previous_defs
        )
        role.skill_definitions = translated_defs
        flag_modified(role, "skill_definitions")

    db.commit()
    db.refresh(role)
    return _role_to_response(db, role)


def deactivate_role(db: Session, role_id: int) -> RoleResponse:
    role = get_role_or_404(db, role_id)
    role.is_active = False
    db.commit()
    db.refresh(role)
    return _role_to_response(db, role)


def activate_role(db: Session, role_id: int) -> RoleResponse:
    role = get_role_or_404(db, role_id)
    role.is_active = True
    db.commit()
    db.refresh(role)
    return _role_to_response(db, role)


def delete_role(db: Session, role_id: int) -> None:
    """Permanently delete a role and its generated content.

    Guarded like regeneration: refuses while a run is active and while
    learner answers reference the role's questions (admin must reset
    learners first). ai_usage_log / rejected_content / user.job_role_id
    are handled by SET NULL FKs; role_generation is deleted explicitly.
    """
    role = get_role_or_404(db, role_id)
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

    saved = has_saved_answers(db, role_id)
    if saved > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{saved} saved learner answer(s) reference this role's questions. "
                "Reset learners for this role before deleting."
            ),
        )

    try:
        question_ids = [
            qid
            for (qid,) in db.query(PlacementTestQuestion.id)
            .filter(PlacementTestQuestion.job_role_id == role_id)
            .all()
        ]
        if question_ids:
            db.query(PlacementTestQuestion).filter(
                PlacementTestQuestion.id.in_(question_ids)
            ).delete(synchronize_session=False)
        # Course outline (lessons cascade via FK).
        db.query(Topic).filter(Topic.role_id == role_id).delete(
            synchronize_session=False
        )
        db.query(RoleGeneration).filter(RoleGeneration.role_id == role_id).delete(
            synchronize_session=False
        )
        # Learners of the deleted role: job_role_id is SET NULL by the FK, so
        # clear their enrollment status too — 'enrolled' must not outlive its track.
        (
            db.query(User)
            .filter(
                User.job_role_id == role_id,
                User.learning_status == LEARNING_ENROLLED,
            )
            .update(
                {"job_role_id": None, "learning_status": LEARNING_NONE},
                synchronize_session=False,
            )
        )
        db.delete(role)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete this role because other records still reference it.",
        )


