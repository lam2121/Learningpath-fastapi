from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.feature.admin import admin_service
from app.feature.admin.admin_schema import (
    CostDashboardData,
    DashboardData,
    GenerateResponse,
    GenerationSummaryResponse,
    GenerationStatusResponse,
    KillSwitchState,
    KillSwitchUpdate,
    PreviewRequest,
    PreviewResponse,
    RejectedContentResponse,
    RejectedContentStatusUpdate,
    ResetLearnersResponse,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
)
from app.feature.admin.dependencies import get_current_admin
from app.models.user import User

router = APIRouter(dependencies=[Depends(get_current_admin)])


# ─── Roles ───────────────────────────────────────────────────────────────────


@router.get("/roles", response_model=list[RoleResponse])
def list_roles(db: Session = Depends(get_db)):
    return admin_service.list_roles(db)


@router.post("/roles", response_model=RoleResponse, status_code=201)
def create_role(
    payload: RoleCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    return admin_service.create_role(db, payload, created_by=admin.id)


@router.get("/roles/{role_id}", response_model=RoleResponse)
def get_role(role_id: int, db: Session = Depends(get_db)):
    return admin_service.get_role(db, role_id)


@router.patch("/roles/{role_id}", response_model=RoleResponse)
def update_role(role_id: int, payload: RoleUpdate, db: Session = Depends(get_db)):
    return admin_service.update_role(db, role_id, payload)


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
    from app.core.ai.generation import generate_placement_for_role

    background_tasks.add_task(generate_placement_for_role, role_id)
    return GenerateResponse(message="Placement generation started", roleId=role_id)


@router.post("/roles/{role_id}/generate-course", response_model=GenerateResponse)
def generate_role_course(
    role_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    force: bool = Query(default=False),
):
    admin_service.kickoff_course_generation(db, role_id, force=force)
    from app.core.ai.generation import generate_course_for_role

    background_tasks.add_task(generate_course_for_role, role_id)
    return GenerateResponse(
        message="Course generation started (B1 topics -> B2 lesson shells)",
        roleId=role_id,
    )


@router.post("/lessons/{lesson_id}/generate", response_model=GenerateResponse)
def generate_lesson_content(
    lesson_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    force: bool = Query(default=False),
):
    info = admin_service.kickoff_lesson_generation(db, lesson_id, force=force)
    from app.core.ai.generation import (
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


# ─── Dashboard / Costs / Rejected / Kill switch ──────────────────────────────


@router.get("/dashboard", response_model=DashboardData)
def dashboard(db: Session = Depends(get_db)):
    return admin_service.get_dashboard(db)


@router.get("/costs", response_model=CostDashboardData)
def costs(db: Session = Depends(get_db)):
    return admin_service.get_costs(db)


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
