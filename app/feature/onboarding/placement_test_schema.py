from pydantic import BaseModel


class PlacementTestQuestionResponse(BaseModel):
    id: int
    skill: str  # 'D' | 'C' | 'T' | 'G'
    level: int  # 1–10  (5 questions per level per skill = 50/skill = 200/role)
    statement: str
    options: list[str]  # 4 plain-text options
    correct_answer: str  # exact text of the correct option

    class Config:
        from_attributes = True


class OnboardingStatusResponse(BaseModel):
    user_id: int
    is_finished_placement_test: bool = False


class PlacementTestResultItem(BaseModel):
    question_id: int
    selected_id: str
    selected_text: str | None = None
    is_correct: bool
    axis: str
    difficulty: int


class CompletePlacementTestRequest(BaseModel):
    user_id: int | None = None
    role_id: int | None = None
    placement_test_answers: list[PlacementTestResultItem] | None = None


class CompletePlacementTestResponse(BaseModel):
    message: str
    is_finished_placement_test: bool = True


class PlacementAnswerDetail(BaseModel):
    question_id: int
    axis: str  # v2.1 tag: D_doc | C_comm | T_trouble | G_custom
    level: int  # 1–8
    statement: str
    options: list[str]  # 4 plain-text options
    correct_answer: str  # exact text of the correct option
    selected_id: str  # letter: 'a' | 'b' | 'c' | 'd'
    selected_text: str | None = None  # exact text of the option the user picked
    is_correct: bool


class PlacementResultResponse(BaseModel):
    is_finished_placement_test: bool
    total_questions: int
    total_correct: int
    overall_percent: int
    skill_scores: dict[str, int]  # {D_doc: 75, C_comm: 80, T_trouble: 60, G_custom: 50}
    starting_level: str  # 'basic' | 'intermediate' | 'advanced'
    weak_skills: list[str]  # list of skill tags where score < 0.5, weakest first
    role_id: int | None = None
    role_name: str | None = None
    baseline: dict[str, int] | None = (
        None  # {D_doc: 20, C_comm: 20, T_trouble: 50, G_custom: 10}
    )
    answers: list[PlacementAnswerDetail]
