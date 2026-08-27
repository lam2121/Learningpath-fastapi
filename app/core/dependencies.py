from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session
 
from app.core.config import app_config
from app.core.database import get_db
from app.models.user import User
 
# Khai báo cấu hình OAuth2
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def _get_or_provision_user(payload: dict, db: Session) -> User:
    """
    Tìm user trong toeic_learningpath hoặc tự động tạo mới (Auto-Provisioning)
    ngay khi người dùng từ Auth Service đăng nhập/truy cập CareerPath lần đầu.
    """
    user_id = payload.get("user_id") or payload.get("sub") or payload.get("id")
    email = payload.get("email")
 
    if not user_id and not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không chứa định danh người dùng.",
            headers={"WWW-Authenticate": "Bearer"},
        )
 
    try:
        user_id_int = int(user_id) if user_id else None
    except (ValueError, TypeError):
        user_id_int = None
 
    # 1. Tìm theo Email (chuẩn xác nhất)
    user = None
    if email:
        user = db.query(User).filter(User.email == email.strip().lower()).first()
 
    # 2. Tìm theo ID nếu chưa tìm thấy bằng email
    if user is None and user_id_int is not None:
        user = db.query(User).filter(User.id == user_id_int).first()
 
    # 3. TỰ ĐỘNG TẠO PROFILE trong toeic_learningpath.user nếu chưa có
    if user is None:
        role_name = str(payload.get("role", "employee")).lower()
        role_id = 2 if role_name in ("admin", "administrator") else 1
        name = payload.get("name") or payload.get("full_name") or payload.get("sub") or (email.split("@")[0] if email else f"User {user_id}")
        user_email = email.strip().lower() if email else f"user_{user_id}@example.com"
 
        insert_id = None
        if user_id_int is not None:
            existing = db.query(User).filter(User.id == user_id_int).first()
            if not existing:
                insert_id = user_id_int
 
        user = User(
            id=insert_id,
            name=name,
            email=user_email,
            role_id=role_id,
            hashed_password="",
            learning_status="none",
            daily_study_minutes=120,
        )
        try:
            db.add(user)
            db.commit()
            db.refresh(user)
        except Exception:
            db.rollback()
            user = User(
                name=name,
                email=user_email,
                role_id=role_id,
                hashed_password="",
                learning_status="none",
                daily_study_minutes=120,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
 
    return user


def get_user_from_access_token(token: Optional[str], db: Session) -> Optional[User]:
    """Validate a raw access token and return the matching user (or None).

    Used by the SSE notification stream endpoint which receives the token
    as a query parameter rather than through the OAuth2 bearer header.
    """
    if not token:
        return None
    try:
        payload = jwt.decode(
            token, app_config.SECRET_KEY,
            algorithms=["HS256"], options={"verify_aud": False},
        )
    except JWTError:
        return None
    return _get_or_provision_user(payload, db)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Không thể xác thực thông tin (Token không hợp lệ hoặc đã hết hạn)",
        headers={"WWW-Authenticate": "Bearer"},
    )
 
    if not token:
        raise credentials_exception
 
    try:
        # Giải mã Token bằng SECRET_KEY dùng chung (HS256)
        payload = jwt.decode(
            token,
            app_config.SECRET_KEY,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except JWTError:
        raise credentials_exception
 
    return _get_or_provision_user(payload, db)
 
 
def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> Optional[User]:
    if not token:
        return None
    try:
        payload = jwt.decode(
            token,
            app_config.SECRET_KEY,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        return _get_or_provision_user(payload, db)
    except Exception:
        return None