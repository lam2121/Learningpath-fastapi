from typing import Any

from pydantic import BaseModel


class JobRoleResponse(BaseModel):
    id: int
    name: str
    job_description: str | None = None
    baseline: dict | None = None
    g_skill_description: str | None = None
    example_question: Any | None = None
    is_active: bool = True

    class Config:
        from_attributes = True
