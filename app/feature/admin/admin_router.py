from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.core.infra.config import app_config
from app.core.infra.database import get_db
from app.feature.admin import admin_service
from app.feature.admin.admin_schema import (
    AdminUserListResponse,
    AdminUserResponse,
    AiUsageLogResponse,
    CostDashboardData,
    DashboardData,
    GenerateResponse,
    GenerationStatusResponse,
    GenerationSummaryResponse,
    KillSwitchState,
    KillSwitchUpdate,
    MoreTopicsRequest,
    PreviewRequest,
    PreviewResponse,
    RejectedContentResponse,
    RejectedContentStatusUpdate,
    ResetLearnerRequest,
    ResetLearnerResponse,
    ResetLearnersResponse,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
    UsageLogClearRequest,
    UsageLogClearResponse,
    UserRoleUpdateRequest,
)
from app.feature.admin.dependencies import get_current_admin
from app.models.user import User

router = APIRouter(dependencies=[Depends(get_current_admin)])


# ─── Roles ───────────────────────────────────────────────────────────────────


@router.get("/roles", response_model=list[RoleResponse])
def list_roles(db: Session = Depends(get_db)):
    return admin_service.list_roles(db)


@router.post("/roles", response_model=RoleResponse, status_code=201)
async def create_role(
    payload: RoleCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    return await admin_service.create_role(db, payload, created_by=admin.id)


@router.get("/roles/{role_id}", response_model=RoleResponse)
def get_role(role_id: int, db: Session = Depends(get_db)):
    return admin_service.get_role(db, role_id)


@router.patch("/roles/{role_id}", response_model=RoleResponse)
async def update_role(role_id: int, payload: RoleUpdate, db: Session = Depends(get_db)):
    return await admin_service.update_role(db, role_id, payload)


@router.post("/roles/{role_id}/deactivate", response_model=RoleResponse)
def deactivate_role(role_id: int, db: Session = Depends(get_db)):
    return admin_service.deactivate_role(db, role_id)


@router.post("/roles/{role_id}/activate", response_model=RoleResponse)
def activate_role(role_id: int, db: Session = Depends(get_db)):
    return admin_service.activate_role(db, role_id)


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(role_id: int, db: Session = Depends(get_db)):
    admin_service.delete_role(db, role_id)


# ─── Generation (Generator A) ────────────────────────────────────────────────


@router.post("/roles/{role_id}/generate", response_model=GenerateResponse)
def generate_role_content(
    role_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    force: bool = Query(default=False),
):
    admin_service.kickoff_generation(db, role_id, force=force)
    from app.core.ai.dispatch.generation import generate_placement_for_role

    background_tasks.add_task(generate_placement_for_role, role_id)
    return GenerateResponse(message="Placement generation started", roleId=role_id)


@router.post("/roles/{role_id}/generate-course", response_model=GenerateResponse)
def generate_role_course(
    role_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    force: bool = Query(default=False),
    resume: bool = Query(default=False),
):
    admin_service.kickoff_course_generation(db, role_id, force=force, resume=resume)
    from app.core.ai.dispatch.generation import generate_course_for_role

    background_tasks.add_task(generate_course_for_role, role_id, resume=resume)
    return GenerateResponse(
        message="Course generation started (B1 topics -> B2 lesson shells)",
        roleId=role_id,
    )


@router.post("/roles/{role_id}/generate-topics", response_model=GenerateResponse)
def generate_role_more_topics(
    role_id: int,
    payload: MoreTopicsRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    info = admin_service.kickoff_more_topics_generation(
        db, role_id, skill=payload.skill, count=payload.count
    )
    from app.core.ai.dispatch.generation import generate_more_topics_for_role

    background_tasks.add_task(
        generate_more_topics_for_role, role_id, payload.skill, payload.count
    )
    return GenerateResponse(message=info["message"], roleId=role_id)


@router.post("/lessons/{lesson_id}/generate", response_model=GenerateResponse)
def generate_lesson_content(
    lesson_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    force: bool = Query(default=False),
):
    info = admin_service.kickoff_lesson_generation(db, lesson_id, force=force)
    from app.core.ai.dispatch.generation import (
        generate_lesson_content as _generate_lesson_content,
    )

    background_tasks.add_task(_generate_lesson_content, lesson_id, force=force)
    return GenerateResponse(message=info["message"], roleId=info["roleId"])


@router.post("/roles/{role_id}/reset-learners", response_model=ResetLearnersResponse)
def reset_role_learners(role_id: int, db: Session = Depends(get_db)):
    return admin_service.reset_role_learners(db, role_id)


@router.get(
    "/roles/{role_id}/generation-status", response_model=GenerationStatusResponse
)
def generation_status(role_id: int, db: Session = Depends(get_db)):
    return admin_service.get_generation_status(db, role_id)


@router.get(
    "/roles/{role_id}/generation-summary", response_model=GenerationSummaryResponse
)
def generation_summary(role_id: int, db: Session = Depends(get_db)):
    return admin_service.get_generation_summary(db, role_id)


@router.post("/preview", response_model=PreviewResponse)
def preview_generation(payload: PreviewRequest):
    return admin_service.preview_generation(
        payload.jobDescription, payload.skillDefinitions
    )


# ─── Users ───────────────────────────────────────────────────────────────────


@router.get("/users", response_model=AdminUserListResponse)
def list_users(
    search: str | None = Query(default=None),
    role: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return admin_service.list_users(
        db, search=search, role=role, limit=limit, offset=offset
    )


@router.patch("/users/{user_id}/role", response_model=AdminUserResponse)
def set_user_role(
    user_id: int,
    payload: UserRoleUpdateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    return admin_service.set_user_role(db, user_id, payload.roleId, admin_id=admin.id)


@router.post("/users/{user_id}/reset-learner", response_model=ResetLearnerResponse)
def reset_single_learner(
    user_id: int,
    payload: ResetLearnerRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    return admin_service.reset_single_learner(
        db, user_id, clear_flashcards=payload.clearFlashcards, admin_id=admin.id
    )


@router.delete("/users/{user_id}", status_code=204)
def delete_user_learning_data(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    admin_service.delete_user_learning_data(db, user_id, admin_id=admin.id)


# ─── Dashboard / Costs / Rejected / Kill switch ──────────────────────────────


@router.get("/dashboard", response_model=DashboardData)
def dashboard(db: Session = Depends(get_db)):
    return admin_service.get_dashboard(db)


@router.get("/costs", response_model=CostDashboardData)
def costs(
    range: str = Query(default="30d", description="7d|30d|90d|this_month|last_month|12m|all"),
    granularity: str | None = Query(default=None, description="daily|weekly|monthly"),
    generator: str | None = Query(default=None),
    model: str | None = Query(default=None),
    role_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return admin_service.get_costs(
        db,
        range_key=range,
        granularity=granularity,
        generator=generator,
        model=model,
        role_id=role_id,
        status_filter=status,
    )


@router.get("/rejected", response_model=list[RejectedContentResponse])
def rejected(
    generator: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return admin_service.list_rejected(db, generator, status)


@router.post("/rejected/{rejected_id}/status", response_model=RejectedContentResponse)
def update_rejected_status(
    rejected_id: int,
    payload: RejectedContentStatusUpdate,
    db: Session = Depends(get_db),
):
    return admin_service.update_rejected_status(db, rejected_id, payload.status)


# ─── AI usage logs ──────────────────────────────────────────────────────────


@router.get("/usage-logs", response_model=list[AiUsageLogResponse])
def usage_logs(
    generator: str | None = Query(default=None),
    status: str | None = Query(default=None),
    role_id: int | None = Query(default=None),
    limit: int = Query(
        default=app_config.USAGE_LOG_DEFAULT_LIMIT,
        ge=1,
        le=app_config.USAGE_LOG_MAX_LIMIT,
    ),
    db: Session = Depends(get_db),
):
    return admin_service.list_usage_logs(
        db, generator, status, role_id=role_id, limit=limit
    )


@router.delete("/usage-logs/{log_id}", status_code=204)
def delete_usage_log(log_id: int, db: Session = Depends(get_db)):
    admin_service.delete_usage_log(db, log_id)


@router.post("/usage-logs/clear", response_model=UsageLogClearResponse)
def clear_usage_logs(payload: UsageLogClearRequest, db: Session = Depends(get_db)):
    return admin_service.clear_usage_logs(db, payload)


@router.get("/kill-switch", response_model=KillSwitchState)
def get_kill_switch(db: Session = Depends(get_db)):
    return admin_service.get_kill_switch(db)


@router.post("/kill-switch", response_model=KillSwitchState)
def set_kill_switch(
    payload: KillSwitchUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    return admin_service.set_kill_switch(
        db, payload.enabled, payload.reason, updated_by=admin.id
    )
