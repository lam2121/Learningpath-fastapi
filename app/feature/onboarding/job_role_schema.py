import json
from typing import Any

from pydantic import BaseModel, field_validator

from app.feature.admin.admin_schema import RoleSkillDefinitions


class JobRoleResponse(BaseModel):
    id: int
    name: str
    job_description: str | dict[str, str] | None = None
    baseline: dict | None = None
    skill_definitions: RoleSkillDefinitions | None = None
    is_active: bool = True

    @field_validator("job_description", mode="before")
    @classmethod
    def parse_job_description(cls, v: Any) -> str | dict[str, str] | None:
        if isinstance(v, str):
            v_strip = v.strip()
            if v_strip.startswith("{") and v_strip.endswith("}"):
                try:
                    parsed = json.loads(v_strip)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    pass
        return v

    class Config:
        from_attributes = True
