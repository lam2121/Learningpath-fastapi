"""Business logic for the admin portal (v2.1).

The actual service logic has been extracted to focused sub-modules:

  - role_service.py              — Role CRUD, serialization helpers
  - generation_service.py        — Generation kickoff, status, stale handling
  - user_management_service.py   — User listing, role assignment, reset, deletion
  - cost_service.py              — Dashboard stats, AI cost analytics
  - moderation_service.py        — Rejected content, usage logs, kill switch

All public names are re-exported here for backward compatibility.
"""

# ─── Re-exports for backward compatibility ───────────────────────────────────

from app.feature.admin.role_service import (  # noqa: F401
    count_active_learners,
    get_role_or_404,
    list_roles,
    get_role,
    create_role,
    update_role,
    deactivate_role,
    activate_role,
    delete_role,
    _baseline,
    _baseline_blob,
    _skill_definitions,
    _skill_definitions_blob,
    _role_to_response,
    _apply_role_payload,
)

from app.feature.admin.generation_service import (  # noqa: F401
    _mark_stale_generation,
    mark_stale_generations_all,
    has_saved_answers,
    kickoff_generation,
    kickoff_course_generation,
    kickoff_more_topics_generation,
    kickoff_lesson_generation,
    reset_role_learners,
    get_generation_status,
    get_generation_summary,
    get_placement_question_count,
    preview_generation,
    PLACEMENT_TARGET_COUNT,
    COURSE_TARGET_TOPICS,
    COURSE_TARGET_LESSONS,
)

from app.feature.admin.user_management_service import (  # noqa: F401
    get_user_or_404,
    list_users,
    set_user_role,
    reset_single_learner,
    delete_user_learning_data,
)

from app.feature.admin.cost_service import (  # noqa: F401
    get_dashboard,
    get_costs,
)

from app.feature.admin.moderation_service import (  # noqa: F401
    list_rejected,
    update_rejected_status,
    list_usage_logs,
    delete_usage_log,
    clear_usage_logs,
    get_kill_switch,
    set_kill_switch,
)
"""
from app.feature.admin.admin_schema import (  # noqa: F401
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
"""
