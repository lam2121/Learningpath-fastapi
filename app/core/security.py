from datetime import datetime, timedelta, timezone
from jose import jwt
from passlib.context import CryptContext
from app.core.config import app_config

# Thiết lập CryptContext sử dụng thuật toán bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Kiểm tra mật khẩu người dùng nhập vào có khớp với mã băm trong DB hay không.
    """
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """
    Băm mật khẩu trước khi lưu xuống Database.
    """
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """
    Tạo JWT Token khi người dùng đăng nhập thành công.
    """
    to_encode = data.copy()
    
    # Thiết lập thời gian hết hạn cho Token
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=app_config.ACCESS_TOKEN_EXPIRE_MINUTES)
        
    to_encode.update({"exp": expire})
    
    # Ký và mã hóa Token
    encoded_jwt = jwt.encode(
        to_encode, 
        app_config.SECRET_KEY, 
        algorithm=app_config.ALGORITHM
    )
    
    return encoded_jwt