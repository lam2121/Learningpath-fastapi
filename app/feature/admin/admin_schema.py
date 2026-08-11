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


# ─── Roles ───────────────────────────────────────────────────────────────────


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    job_description: str = Field(min_length=1)
    baseline: Baseline
    g_skill_description: str = Field(min_length=1)
    seed_tier_1: str = Field(min_length=1)
    seed_tier_2: str = Field(min_length=1)
    example_question: list[str] | None = None

    @field_validator("baseline")
    @classmethod
    def baseline_sums_to_100(cls, v: Baseline) -> Baseline:
        return v.validate_sum()

    @field_validator("example_question")
    @classmethod
    def normalize_example_question(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        cleaned = [q.strip() for q in v if q and q.strip()]
        # [] signals "clear" on PATCH; null signals "no change"
        return cleaned[:2]


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    job_description: str | None = Field(default=None, min_length=1)
    baseline: Baseline | None = None
    g_skill_description: str | None = Field(default=None, min_length=1)
    seed_tier_1: str | None = Field(default=None, min_length=1)
    seed_tier_2: str | None = Field(default=None, min_length=1)
    example_question: list[str] | None = None
    is_active: bool | None = None

    @field_validator("baseline")
    @classmethod
    def baseline_sums_to_100(cls, v: Baseline | None) -> Baseline | None:
        if v is not None:
            return v.validate_sum()
        return v

    @field_validator("example_question")
    @classmethod
    def normalize_example_question(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        cleaned = [q.strip() for q in v if q and q.strip()]
        # [] signals "clear" on PATCH; null signals "no change"
        return cleaned[:2]


class RoleResponse(BaseModel):
    id: int
    name: str
    jobDescription: str
    baseline: Baseline
    gSkillDefinition: str
    seedTier1: str
    seedTier2: str
    exampleQuestion: list[str] | None = None
    isActive: bool
    createdBy: int | None = None
    activeLearnerCount: int = 0
    topicsCount: int = 0
    lessonsCount: int = 0
    generationStatus: str | None = None


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
    gSkillDefinition: str


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


# ─── Kill switch ────────────────────────────────────────────────────────────


class KillSwitchState(BaseModel):
    enabled: bool
    enabledAt: datetime | None = None
    enabledBy: int | None = None
    reason: str | None = None


class KillSwitchUpdate(BaseModel):
    enabled: bool
    reason: str | None = None
