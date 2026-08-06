from typing import Any

from pydantic import BaseModel


class JobRoleResponse(BaseModel):
    id: int
    name: str
    job_description: str | None = None
    baseline: dict | None = None
    example_question: Any | None = None

    class Config:
        from_attributes = True
