from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import app_config
from app.core.database import get_db
from app.models.user import User
 
# CareerPath consumes bearer tokens issued by the external auth-service.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=app_config.AUTH_TOKEN_URL,
    auto_error=False,
)


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Không thể xác thực thông tin (Token không hợp lệ hoặc đã hết hạn)",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _normalize_role_id(role_name: object) -> int:
    normalized = str(role_name or "employee").strip().lower()
    if normalized == "admin":
        return 2
    if normalized in {"employee", "guest"}:
        return 1
    raise _credentials_exception()


def _decode_auth_service_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            app_config.SECRET_KEY,
            algorithms=[app_config.ALGORITHM],
            issuer=app_config.AUTH_TOKEN_ISSUER,
            audience=app_config.AUTH_TOKEN_AUDIENCE,
        )
    except JWTError as exc:
        raise _credentials_exception() from exc

    if payload.get("token_type") != "access":
        raise _credentials_exception()

    return payload


def _get_or_provision_user(payload: dict, db: Session) -> User:
    """Provision or update the local app profile from trusted auth-service claims."""
    user_id = payload.get("user_id") or payload.get("sub")
    email = str(payload.get("email") or "").strip().lower()

    if not user_id or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không chứa đầy đủ định danh người dùng.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError) as exc:
        raise _credentials_exception() from exc

    role_id = _normalize_role_id(payload.get("role"))
    display_name = str(
        payload.get("name") or payload.get("full_name") or email.split("@")[0]
    ).strip()
    if not display_name:
        raise _credentials_exception()

    user_by_id = db.query(User).filter(User.id == user_id_int).first()
    user_by_email = db.query(User).filter(User.email == email).first()

    if (
        user_by_id is not None
        and user_by_email is not None
        and user_by_id.id != user_by_email.id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="CareerPath user mapping conflict for authenticated identity.",
        )

    user = user_by_id or user_by_email

    if user is None:
        user = User(
            id=user_id_int,
            name=display_name,
            email=email,
            role_id=role_id,
            hashed_password="",
            learning_status="none",
            daily_study_minutes=120,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    needs_update = False
    if user.email != email:
        user.email = email
        needs_update = True
    if user.role_id != role_id:
        user.role_id = role_id
        needs_update = True
    if not user.name or user.name != display_name:
        user.name = display_name
        needs_update = True
    if needs_update:
        db.add(user)
        db.commit()
        db.refresh(user)

    return user


def get_user_from_access_token(token: str | None, db: Session) -> User | None:
    """Validate a raw access token and return the matching user (or None).

    Used by the SSE notification stream endpoint which receives the token
    as a query parameter rather than through the OAuth2 bearer header.
    """
    if not token:
        return None
    try:
        payload = _decode_auth_service_access_token(token)
        return _get_or_provision_user(payload, db)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            return None
        raise

def get_token_from_request(request: Request, *, required: bool = True) -> str | None:
    token = request.cookies.get("access_token")

    if not token:
        authorization = request.headers.get("Authorization")
        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ", 1)[1]

    if token or not required:
        return token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Không tìm thấy token xác thực",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = get_token_from_request(request)
    if not token:
        raise _credentials_exception()

    payload = _decode_auth_service_access_token(token)
    return _get_or_provision_user(payload, db)


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    token = get_token_from_request(request, required=False)
    if not token:
        return None
    try:
        payload = _decode_auth_service_access_token(token)
        return _get_or_provision_user(payload, db)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            return None
        raise
