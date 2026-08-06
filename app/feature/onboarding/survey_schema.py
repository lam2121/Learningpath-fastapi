from pydantic import BaseModel
from typing import List, Optional, Any, Union

class SubQuestionOption(BaseModel):
    id: str
    label: str

class SubQuestion(BaseModel):
    question: str
    options: List[SubQuestionOption]

class SurveyQuestionResponse(BaseModel):
    id: str
    axis: str
    question: str
    context: str
    subQuestion: Optional[SubQuestion] = None

class SurveyAnswerItem(BaseModel):
    survey_id: int
    rating: int
    sub_answer: Optional[str] = None

class SubmitSurveyRequest(BaseModel):
    user_id: int
    answers: List[SurveyAnswerItem]

class SubmitSurveyResponse(BaseModel):
    message: str
    recorded_count: int

class OnboardingStatusResponse(BaseModel):
    user_id: int
    has_completed_survey: bool = False
    is_finished_placement_test: bool = False

class PlacementTestResultItem(BaseModel):
    question_id: int
    selected_id: str
    is_correct: bool
    axis: str
    difficulty: int

class CompletePlacementTestRequest(BaseModel):
    user_id: Optional[int] = None
    role_id: Optional[int] = None
    placement_test_answers: Optional[List[PlacementTestResultItem]] = None

class CompletePlacementTestResponse(BaseModel):
    message: str
    is_finished_placement_test: bool = True

