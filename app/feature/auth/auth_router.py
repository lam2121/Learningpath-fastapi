from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.feature.auth.auth_schema import UserCreate, UserResponse
from app.models.user import User
from app.core.security import get_password_hash, verify_password, create_access_token
from app.core.dependencies import get_current_user

router = APIRouter()

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    # 1. Kiểm tra xem email đã tồn tại trong Database chưa
    user_exists = db.query(User).filter(User.email == user_in.email).first()
    if user_exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Email đã được đăng ký."
        )
    
    # 2. Băm mật khẩu và tạo bản ghi mới
    hashed_pwd = get_password_hash(user_in.password)
    new_user = User(
        email=user_in.email, 
        name=user_in.name, 
        hashed_password=hashed_pwd
    )
    
    # 3. Lưu xuống Database
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return new_user

# Đã thay đổi UserLogin thành OAuth2PasswordRequestForm
@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # 1. Tìm user theo email    
    # Swagger sẽ gửi email vào trường form_data.username
    user = db.query(User).filter(User.email == form_data.username).first()
    
    # 2. Kiểm tra user có tồn tại và mật khẩu có khớp không
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Email hoặc mật khẩu không chính xác."
        )
    
    # 3. Nếu đúng, tạo JWT Token chứa user_id (sub)
    access_token = create_access_token(data={"sub": str(user.id)})
    
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=UserResponse)
def get_user_profile(current_user: User = Depends(get_current_user)):
    """
    API này yêu cầu phải có Token hợp lệ. 
    Nếu Token đúng, nó sẽ trả về thông tin của chính user đó.
    """
    return current_user