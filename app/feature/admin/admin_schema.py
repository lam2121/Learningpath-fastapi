from datetime import datetime

from pydantic import BaseModel, Field, field_validator

SKILL_KEYS = ("D_doc", "C_comm", "T_trouble", "G_custom")


# ─── Baseline ────────────────────────────────────────────────────────────────


class Baseline(BaseModel):
    D_doc: int
    C_comm: int
    T_trouble: int
    G_custom: int

    @field_validator("D_doc", "C_comm", "T_trouble", "G_custom")
    @classmethod
    def check_step_and_floor(cls, v: int) -> int:
        if v % 5 != 0:
            raise ValueError("baseline values must be multiples of 5")
        if v < 10:
            raise ValueError("baseline values must be >= 10")
        return v

    @field_validator("D_doc", "C_comm", "T_trouble", "G_custom")
    @classmethod
    def check_upper(cls, v: int) -> int:
        if v > 100:
            raise ValueError("baseline values cannot exceed 100")
        return v

    @property
    def total(self) -> int:
        return self.D_doc + self.C_comm + self.T_trouble + self.G_custom

    def validate_sum(self) -> "Baseline":
        if self.total != 100:
            raise ValueError(f"baseline must sum to 100, got {self.total}")
        return self


class SkillDefinition(BaseModel):
    description: str = Field(min_length=1)
    example_questions: list[str] = Field(default_factory=list)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("skill description is required")
        return cleaned

    @field_validator("example_questions")
    @classmethod
    def normalize_example_questions(cls, v: list[str]) -> list[str]:
        cleaned = [q.strip() for q in v if q and q.strip()]
        return cleaned[:2]


class RoleSkillDefinitions(BaseModel):
    D_doc: SkillDefinition
    C_comm: SkillDefinition
    T_trouble: SkillDefinition
    G_custom: SkillDefinition


# ─── Roles ───────────────────────────────────────────────────────────────────


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    job_description: str = Field(min_length=1)
    baseline: Baseline
    skill_definitions: RoleSkillDefinitions
    seed_tier_1: str = Field(min_length=1)
    seed_tier_2: str = Field(min_length=1)

    @field_validator("baseline")
    @classmethod
    def baseline_sums_to_100(cls, v: Baseline) -> Baseline:
        return v.validate_sum()


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    job_description: str | None = Field(default=None, min_length=1)
    baseline: Baseline | None = None
    skill_definitions: RoleSkillDefinitions | None = None
    seed_tier_1: str | None = Field(default=None, min_length=1)
    seed_tier_2: str | None = Field(default=None, min_length=1)
    is_active: bool | None = None

    @field_validator("baseline")
    @classmethod
    def baseline_sums_to_100(cls, v: Baseline | None) -> Baseline | None:
        if v is not None:
            return v.validate_sum()
        return v


class RoleResponse(BaseModel):
    id: int
    name: str
    jobDescription: str
    baseline: Baseline
    skillDefinitions: RoleSkillDefinitions
    seedTier1: str
    seedTier2: str
    isActive: bool
    createdBy: int | None = None
    activeLearnerCount: int = 0
    placementQuestionsCount: int = 0
    topicsCount: int = 0
    lessonsCount: int = 0
    generationStatus: str | None = None
    placementGenerationStatus: str | None = None
    courseGenerationStatus: str | None = None


# ─── Generation ─────────────────────────────────────────────────────────────


class GenerationStatusResponse(BaseModel):
    roleId: int
    status: str
    step: str
    stepACount: int
    stepAErrors: int
    stepB1Count: int = 0
    stepB1Errors: int = 0
    stepB2Count: int = 0
    stepB2Errors: int = 0
    startedAt: datetime | None = None
    finishedAt: datetime | None = None
    errorMessage: str | None = None


class GenerationActiveJobResponse(BaseModel):
    workflow: str | None = None
    status: str | None = None
    step: str | None = None
    startedAt: datetime | None = None
    finishedAt: datetime | None = None


class PlacementGenerationSummaryResponse(BaseModel):
    questionCount: int
    targetCount: int
    lastStatus: str
    lastStartedAt: datetime | None = None
    lastFinishedAt: datetime | None = None
    lastErrorMessage: str | None = None


class CourseGenerationSummaryResponse(BaseModel):
    topicsCount: int
    targetTopics: int
    lessonsCount: int
    targetLessons: int
    currentStep: str | None = None
    lastStatus: str
    lastStartedAt: datetime | None = None
    lastFinishedAt: datetime | None = None
    lastErrorMessage: str | None = None
    stepB1Count: int = 0
    stepB1Errors: int = 0
    stepB2Count: int = 0
    stepB2Errors: int = 0


class GenerationBlockersResponse(BaseModel):
    killSwitchOn: bool
    killSwitchReason: str | None = None
    activeLearnerCount: int
    requiresLearnerResetForPlacement: bool = False
    requiresLearnerResetForCourse: bool = False


class GenerationSummaryResponse(BaseModel):
    roleId: int
    activeJob: GenerationActiveJobResponse
    placement: PlacementGenerationSummaryResponse
    course: CourseGenerationSummaryResponse
    blockers: GenerationBlockersResponse


class GenerateResponse(BaseModel):
    message: str
    roleId: int


class ResetLearnersResponse(BaseModel):
    resetLearners: int
    clearedAnswers: int
    clearedRoadmaps: int


# ─── Preview (stubbed) ───────────────────────────────────────────────────────


class PreviewRequest(BaseModel):
    jobDescription: str
    skillDefinitions: RoleSkillDefinitions


class PreviewResponse(BaseModel):
    examples: list[str]
    warning: str | None = None


# ─── Dashboard / Costs ───────────────────────────────────────────────────────


class DashboardData(BaseModel):
    totalTracks: int
    activeTracks: int
    activeLearners: int
    aiCalls30d: int
    aiCost30d: float
    pendingRejected: int


class CostDay(BaseModel):
    date: str
    total: float
    byGenerator: dict


class GeneratorBreakdown(BaseModel):
    generator: str
    count: int
    totalTokens: int
    totalCost: float
    avgCost: float


class CostAlert(BaseModel):
    date: str
    type: str
    message: str


class CostDashboardData(BaseModel):
    totalCost30d: float
    dailyAverage: float
    dailyCosts: list[CostDay]
    generatorBreakdown: list[GeneratorBreakdown]
    alerts: list[CostAlert]


# ─── Rejected content ───────────────────────────────────────────────────────


class RejectedContentResponse(BaseModel):
    id: int
    generator: str
    roleId: int | None = None
    roleName: str | None = None
    inputPreview: str | None = None
    error: str
    rawResponse: str | None = None
    validatorChecks: dict | None = None
    status: str
    createdAt: datetime


class RejectedContentStatusUpdate(BaseModel):
    status: str


# ─── AI usage logs ──────────────────────────────────────────────────────────


class AiUsageLogResponse(BaseModel):
    id: int
    generator: str
    model: str
    promptTokens: int
    completionTokens: int
    costUsd: float
    status: str
    roleId: int | None = None
    roleName: str | None = None
    createdAt: datetime


class UsageLogClearRequest(BaseModel):
    generator: str | None = None
    status: str | None = None
    roleId: int | None = None


class UsageLogClearResponse(BaseModel):
    deletedCount: int


# ─── Kill switch ────────────────────────────────────────────────────────────


class KillSwitchState(BaseModel):
    enabled: bool
    enabledAt: datetime | None = None
    enabledBy: int | None = None
    reason: str | None = None


class KillSwitchUpdate(BaseModel):
    enabled: bool
    reason: str | None = None
