from pydantic import BaseModel
from typing import Dict, List

class SeedTier(BaseModel):
    tier: int
    name: str
class JobRoleUI(BaseModel):
    subtitle: str
    toeicTarget: str
    icon: str
    color: str
    gradient: str
    accentColor: str
class JobRoleBase(BaseModel):
    name: str
    JD: str
    UI: JobRoleUI
class JobRoleCreate(JobRoleBase):
    seed_tier: List[SeedTier]
    init_weights: Dict[str, int]
    example_question: List[str]
class JobRoleResponse(BaseModel):
    id: int
    name: str
    JD: str
    UI: JobRoleUI
    seed_tier: list[SeedTier]
    init_weights: dict[str, int]
    example_question: list[str]

    class Config:
        from_attributes = True
class JobRoleDetailResponse(JobRoleResponse):
    seed_tier: List[SeedTier]
    init_weights: Dict[str, int]
    example_question: List[str]

    class Config:
        from_attributes = True