from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import app_config
from app.core.database import get_db
from app.models.user import User

# Khai báo cấu hình OAuth2. 
# tokenUrl chỉ ra API nào được dùng để lấy token (dành cho Swagger UI)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def get_user_from_access_token(token: Optional[str], db: Session) -> Optional[User]:
    if token is None:
        return None

    try:
        payload = jwt.decode(
            token, app_config.SECRET_KEY, algorithms=[app_config.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
    except JWTError:
        return None

    user = db.query(User).filter(User.id == int(user_id)).first()
    return user


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Không thể xác thực thông tin (Token không hợp lệ hoặc đã hết hạn)",
        headers={"WWW-Authenticate": "Bearer"},
    )

    user = get_user_from_access_token(token, db)
    if user is None:
        raise credentials_exception

    return user


def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> Optional[User]:
    return get_user_from_access_token(token, db)
