from pydantic import BaseModel
from typing import Any


class JobRoleResponse(BaseModel):
    id: int
    name: str
    JD: str
    seed_tier: Any
    init_weights: Any
    example_question: Any
    weight_descriptions: Any = None

    class Config:
        from_attributes = True
