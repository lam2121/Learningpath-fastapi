
from pydantic import BaseModel


class PlacementTestQuestionResponse(BaseModel):
    id: int
    skill: str          # 'D' | 'C' | 'T' | 'G'
    level: int          # 1–10  (5 questions per level per skill = 50/skill = 200/role)
    statement: str
    options: list[str]  # 4 plain-text options
    correct_answer: str # exact text of the correct option

    class Config:
        from_attributes = True


class OnboardingStatusResponse(BaseModel):
    user_id: int
    is_finished_placement_test: bool = False


class PlacementTestResultItem(BaseModel):
    question_id: int
    selected_id: str
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
