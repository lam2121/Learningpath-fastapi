"""Business logic for the admin portal (v2.1).

Role CRUD, Generator A kickoff/status, dashboard, AI costs, rejected content,
and the kill switch.
"""

from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.ai.gemini import AI_GENERATION_ENABLED_KEY, generation_enabled
from app.feature.admin.admin_schema import (
    Baseline,
    CostAlert,
    CostDashboardData,
    CostDay,
    DashboardData,
    GenerationStatusResponse,
    GeneratorBreakdown,
    KillSwitchState,
    PreviewResponse,
    RejectedContentResponse,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
)
from app.models.ai_usage_log import AiUsageLog
from app.models.generation import RoleGeneration
from app.models.job_role import DEFAULT_BASELINE, JobRole
from app.models.placement_test_question import PlacementTestQuestion
from app.models.rejected_content import RejectedContent
from app.models.system_setting import SystemSetting
from app.models.user import User

# ─── Serialization helpers ───────────────────────────────────────────────────


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


def _role_to_response(db: Session, role: JobRole) -> RoleResponse:
    active_learners = (
        db.query(User)
        .filter(
            User.job_role_id == role.id,
            User.is_finished_placement_test.is_(True),
        )
        .count()
    )
    gen = (
        db.query(RoleGeneration)
        .filter(RoleGeneration.role_id == role.id)
        .order_by(RoleGeneration.id.desc())
        .first()
    )
    return RoleResponse(
        id=role.id,
        name=role.name,
        jobDescription=role.job_description or "",
        baseline=_baseline(role),
        gSkillDefinition=role.g_skill_description or "",
        seedTier1=role.seed_tier_1 or "",
        seedTier2=role.seed_tier_2 or "",
        exampleQuestion=role.example_question or None,
        isActive=role.is_active,
        createdBy=role.created_by,
        activeLearnerCount=active_learners,
        topicsCount=0,
        lessonsCount=0,
        generationStatus=gen.status if gen else None,
    )


def _apply_role_payload(role: JobRole, payload: RoleCreate | RoleUpdate) -> None:
    role.name = payload.name if payload.name is not None else role.name
    role.job_description = (
        payload.job_description
        if payload.job_description is not None
        else role.job_description
    )
    if payload.baseline is not None:
        role.baseline = _baseline_blob(payload.baseline)
    role.g_skill_description = (
        payload.g_skill_description
        if payload.g_skill_description is not None
        else role.g_skill_description
    )
    role.seed_tier_1 = (
        payload.seed_tier_1 if payload.seed_tier_1 is not None else role.seed_tier_1
    )
    role.seed_tier_2 = (
        payload.seed_tier_2 if payload.seed_tier_2 is not None else role.seed_tier_2
    )
    if payload.example_question is not None:
        role.example_question = payload.example_question or None
    if isinstance(payload, RoleUpdate) and payload.is_active is not None:
        role.is_active = payload.is_active


# ─── Roles ───────────────────────────────────────────────────────────────────


def get_role_or_404(db: Session, role_id: int) -> JobRole:
    role = db.query(JobRole).filter(JobRole.id == role_id).first()
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


def create_role(db: Session, payload: RoleCreate, created_by: int) -> RoleResponse:
    role = JobRole(
        name=payload.name,
        job_description=payload.job_description,
        baseline=_baseline_blob(payload.baseline),
        g_skill_description=payload.g_skill_description,
        seed_tier_1=payload.seed_tier_1,
        seed_tier_2=payload.seed_tier_2,
        example_question=payload.example_question or None,
        is_active=True,
        created_by=created_by,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return _role_to_response(db, role)


def update_role(db: Session, role_id: int, payload: RoleUpdate) -> RoleResponse:
    role = get_role_or_404(db, role_id)
    _apply_role_payload(role, payload)
    db.commit()
    db.refresh(role)
    return _role_to_response(db, role)


def deactivate_role(db: Session, role_id: int) -> RoleResponse:
    role = get_role_or_404(db, role_id)
    role.is_active = False
    db.commit()
    db.refresh(role)
    return _role_to_response(db, role)


# ─── Generation (Generator A) ────────────────────────────────────────────────


def kickoff_generation(db: Session, role_id: int) -> dict:
    get_role_or_404(db, role_id)
    return {"message": "Placement generation started", "roleId": role_id}


def get_generation_status(db: Session, role_id: int) -> GenerationStatusResponse:
    get_role_or_404(db, role_id)
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
        startedAt=gen.started_at,
        finishedAt=gen.finished_at,
        errorMessage=gen.error_message,
    )


def get_placement_question_count(db: Session, role_id: int) -> int:
    return (
        db.query(PlacementTestQuestion)
        .filter(PlacementTestQuestion.job_role_id == role_id)
        .count()
    )


# ─── Preview (stubbed for now) ───────────────────────────────────────────────


def preview_generation(
    job_description: str, g_skill_description: str
) -> PreviewResponse:
    is_vague = (
        len(g_skill_description) < 50
        or "work with" in g_skill_description.lower()
        or " job" in g_skill_description.lower()
    )
    if is_vague:
        return PreviewResponse(
            examples=[
                "Work with data to analyze trends.",
                "Communicate with team to understand requirements.",
                "Write periodic reports for management.",
            ],
            warning=(
                "G-skill definition is too generic. AI generates non-specialized examples. "
                "Please add specific technical keywords."
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


# ─── Dashboard ───────────────────────────────────────────────────────────────


def get_dashboard(db: Session) -> DashboardData:
    now = datetime.now()
    since = now - timedelta(days=30)

    total_tracks = db.query(JobRole).count()
    active_tracks = db.query(JobRole).filter(JobRole.is_active.is_(True)).count()
    active_learners = (
        db.query(User)
        .filter(
            User.job_role_id.isnot(None),
            User.is_finished_placement_test.is_(True),
        )
        .count()
    )
    ai_calls_30d = db.query(AiUsageLog).filter(AiUsageLog.created_at >= since).count()
    ai_cost_30d = (
        db.query(AiUsageLog)
        .filter(AiUsageLog.created_at >= since)
        .with_entities(AiUsageLog.cost_usd)
        .all()
    )
    pending_rejected = (
        db.query(RejectedContent).filter(RejectedContent.status == "pending").count()
    )

    return DashboardData(
        totalTracks=total_tracks,
        activeTracks=active_tracks,
        activeLearners=active_learners,
        aiCalls30d=ai_calls_30d,
        aiCost30d=round(sum(c[0] for c in ai_cost_30d), 6),
        pendingRejected=pending_rejected,
    )


# ─── AI Costs ────────────────────────────────────────────────────────────────


def get_costs(db: Session) -> CostDashboardData:
    now = datetime.now()
    since = now - timedelta(days=30)
    rows = (
        db.query(AiUsageLog)
        .filter(AiUsageLog.created_at >= since)
        .order_by(AiUsageLog.created_at.asc())
        .all()
    )

    days: dict[str, CostDay] = {}
    for offset in range(30):
        day = (since + timedelta(days=offset)).strftime("%Y-%m-%d")
        days[day] = CostDay(date=day, total=0.0, byGenerator={})

    gen_stats: dict[str, dict] = {}
    for row in rows:
        day = row.created_at.strftime("%Y-%m-%d")
        day_obj = days.setdefault(day, CostDay(date=day, total=0.0, byGenerator={}))
        day_obj.total += row.cost_usd
        day_obj.byGenerator[row.generator] = (
            day_obj.byGenerator.get(row.generator, 0.0) + row.cost_usd
        )

        stats = gen_stats.setdefault(
            row.generator, {"count": 0, "total_tokens": 0, "total_cost": 0.0}
        )
        stats["count"] += 1
        stats["total_tokens"] += row.prompt_tokens + row.completion_tokens
        stats["total_cost"] += row.cost_usd

    daily_costs = [days[key] for key in sorted(days)]
    total_cost = sum(d.total for d in daily_costs)

    breakdown = []
    for gen, stats in sorted(gen_stats.items()):
        count = stats["count"]
        breakdown.append(
            GeneratorBreakdown(
                generator=gen,
                count=count,
                totalTokens=stats["total_tokens"],
                totalCost=round(stats["total_cost"], 6),
                avgCost=round(stats["total_cost"] / count, 6) if count else 0.0,
            )
        )

    alerts = _detect_cost_alerts(daily_costs)
    return CostDashboardData(
        totalCost30d=round(total_cost, 6),
        dailyAverage=round(total_cost / 30, 6),
        dailyCosts=daily_costs,
        generatorBreakdown=breakdown,
        alerts=alerts,
    )


def _detect_cost_alerts(daily_costs: list[CostDay]) -> list[CostAlert]:
    alerts: list[CostAlert] = []
    if len(daily_costs) < 8:
        return alerts
    last7 = [d.total for d in daily_costs[-7:]]
    avg7 = sum(last7[:-1]) / 6 if len(last7) > 1 else 0.0
    yesterday = last7[-1]
    if avg7 > 0 and yesterday > avg7 * 1.5:
        alerts.append(
            CostAlert(
                date=daily_costs[-1].date,
                type="spike",
                message=(
                    f"Yesterday's cost (${yesterday:.4f}) exceeded "
                    f"{((yesterday / avg7 - 1) * 100):.0f}% vs 7-day average (${avg7:.4f})"
                ),
            )
        )
    return alerts


# ─── Rejected content ────────────────────────────────────────────────────────


def _rejected_to_response(db: Session, row: RejectedContent) -> RejectedContentResponse:
    role_name = None
    if row.role_id is not None:
        role = db.query(JobRole).filter(JobRole.id == row.role_id).first()
        role_name = role.name if role else None
    return RejectedContentResponse(
        id=row.id,
        generator=row.generator,
        roleId=row.role_id,
        roleName=role_name,
        inputPreview=row.input_preview,
        error=row.error,
        rawResponse=row.raw_response,
        validatorChecks=row.validator_checks,
        status=row.status,
        createdAt=row.created_at,
    )


def list_rejected(
    db: Session, generator: str | None = None, status_filter: str | None = None
) -> list[RejectedContentResponse]:
    query = db.query(RejectedContent).order_by(RejectedContent.created_at.desc())
    if generator and generator != "all":
        query = query.filter(RejectedContent.generator == generator)
    if status_filter and status_filter != "all":
        query = query.filter(RejectedContent.status == status_filter)
    rows = query.all()
    return [_rejected_to_response(db, r) for r in rows]


def update_rejected_status(
    db: Session, rejected_id: int, new_status: str
) -> RejectedContentResponse:
    if new_status not in ("pending", "fixed", "ignored"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status must be one of pending/fixed/ignored",
        )
    row = db.query(RejectedContent).filter(RejectedContent.id == rejected_id).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rejected content not found"
        )
    row.status = new_status
    db.commit()
    db.refresh(row)
    return _rejected_to_response(db, row)


# ─── Kill switch ─────────────────────────────────────────────────────────────


def get_kill_switch(db: Session) -> KillSwitchState:
    row = (
        db.query(SystemSetting)
        .filter(SystemSetting.key == AI_GENERATION_ENABLED_KEY)
        .first()
    )
    if row is None:
        return KillSwitchState(enabled=False)
    enabled = row.value.strip().lower() == "true"
    # Frontend semantics: `enabled` = kill switch ON (AI blocked) = NOT ai_generation_enabled
    return KillSwitchState(
        enabled=not enabled,
        enabledAt=row.updated_at if not enabled else None,
        enabledBy=row.updated_by,
        reason=row.reason,
    )


def set_kill_switch(
    db: Session, enabled: bool, reason: str | None, updated_by: int | None = None
) -> KillSwitchState:
    # enabled=True (kill switch ON) -> block generation
    new_value = "false" if enabled else "true"
    row = (
        db.query(SystemSetting)
        .filter(SystemSetting.key == AI_GENERATION_ENABLED_KEY)
        .first()
    )
    if row is None:
        row = SystemSetting(key=AI_GENERATION_ENABLED_KEY, value=new_value)
        db.add(row)
    else:
        row.value = new_value
    row.updated_by = updated_by
    row.reason = reason
    db.commit()
    db.refresh(row)
    return KillSwitchState(
        enabled=not generation_enabled(db),
        enabledAt=row.updated_at if enabled else None,
        enabledBy=row.updated_by,
        reason=row.reason,
    )
