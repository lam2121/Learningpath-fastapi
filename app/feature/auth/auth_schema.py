from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# 1. Base Schema: Chứa các trường chung nhất
class UserBase(BaseModel):
    email: EmailStr
    name: str


# 2. Schema cho Đăng ký (Kế thừa từ Base và thêm password)
class UserCreate(UserBase):
    password: str = Field(
        ..., min_length=6, description="Mật khẩu phải có ít nhất 6 ký tự"
    )


# 3. Schema cho Đăng nhập
class UserLogin(BaseModel):
    email: EmailStr
    password: str


# 4. Schema trả về cho Client (Giấu hoàn toàn hashed_password)
class UserResponse(UserBase):
    id: int
    role_id: Optional[int] = None
    created_at: datetime

    # Cấu hình này giúp Pydantic đọc được dữ liệu từ SQLAlchemy Model
    class Config:
        from_attributes = True


class UserProfileResponse(UserResponse):
    started_at: datetime | None = None
    estimated_finish: date | None = None
    total_estimated_minutes: int = 0
    daily_study_minutes: int = 120


class StudySettingsUpdateRequest(BaseModel):
    daily_study_minutes: int = Field(ge=60, le=360, multiple_of=60)


# 5. Schema trả về từ login (token + user info)
class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    name: str
    role_id: Optional[int] = None
