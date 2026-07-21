from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import app_config
from app.models.user import User

# Khai báo cấu hình OAuth2. 
# tokenUrl chỉ ra API nào được dùng để lấy token (dành cho Swagger UI)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Không thể xác thực thông tin (Token không hợp lệ hoặc đã hết hạn)",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Giải mã Token bằng SECRET_KEY và ALGORITHM
        payload = jwt.decode(token, app_config.SECRET_KEY, algorithms=[app_config.ALGORITHM])
        
        # Lấy user_id (sub) từ payload
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
            
    except JWTError:
        raise credentials_exception
        
    # Truy vấn User từ Database
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise credentials_exception
        
    return user