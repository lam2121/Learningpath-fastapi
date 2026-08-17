from pydantic import BaseModel

from app.feature.admin.admin_schema import RoleSkillDefinitions


class JobRoleResponse(BaseModel):
    id: int
    name: str
    job_description: str | None = None
    baseline: dict | None = None
    skill_definitions: RoleSkillDefinitions | None = None
    is_active: bool = True

    class Config:
        from_attributes = True
