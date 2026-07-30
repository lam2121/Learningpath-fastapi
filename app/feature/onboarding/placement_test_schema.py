from pydantic import BaseModel
from typing import List


class PlacementTestQuestionResponse(BaseModel):
    id: int
    skill: str          # 'D' | 'C' | 'T' | 'G'
    level: int          # 1–10  (5 questions per level per skill = 50/skill = 200/role)
    statement: str
    options: List[str]  # 4 plain-text options
    correct_answer: str # exact text of the correct option

    class Config:
        from_attributes = True
