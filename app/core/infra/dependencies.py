import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

logger = logging.getLogger(__name__)
from jose import JWTError, jwt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.infra.config import app_config
from app.core.infra.database import get_db
from app.core.ai.client.jwks import decode_auth_token
from app.models.user import ADMIN_ROLE_ID, LEARNER_ROLE_ID, User
 
# CareerPath consumes bearer tokens issued by the external auth-service.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{app_config.AUTH_SERVICE_URL}/login",
    auto_error=False,
)


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Không thể xác thực thông tin (Token không hợp lệ hoặc đã hết hạn)",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _decode_auth_service_access_token(token: str) -> dict:
    # Try JWKS-based decoder first (supports both HS256 and RS256)
    payload = decode_auth_token(token)
    if payload is None:
        # Fallback HS256: respect JWT_STRICT_CLAIMS flag (False by default for tolerant auth)
        try:
            if getattr(app_config, "JWT_STRICT_CLAIMS", False):
                payload = jwt.decode(
                    token,
                    app_config.SECRET_KEY,
                    algorithms=[app_config.ALGORITHM],
                    issuer=app_config.JWT_ISSUER,
                    audience=app_config.JWT_AUDIENCE,
                )
            else:
                payload = jwt.decode(
                    token,
                    app_config.SECRET_KEY,
                    algorithms=[app_config.ALGORITHM],
                    options={"verify_aud": False, "verify_issuer": False},
                )
        except JWTError as exc:
            raise _credentials_exception() from exc

    if payload.get("token_type") and payload.get("token_type") != "access":
        raise _credentials_exception()

    return payload


def _get_or_provision_user(payload: dict, db: Session) -> User:
    """Provision or update the local app profile from trusted auth-service claims.

    Identity (email, name) and admin status are synced from trusted auth-service claims.
    """
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

    display_name = str(
        payload.get("name") or payload.get("full_name") or email.split("@")[0]
    ).strip()
    if not display_name:
        raise _credentials_exception()

    role_name = str(payload.get("role", "employee")).lower()
    role_id_claim = payload.get("role_id")
    is_admin = (
        role_name in ("admin", "administrator")
        or role_id_claim == ADMIN_ROLE_ID
        or role_id_claim == str(ADMIN_ROLE_ID)
    )
    target_role_id = ADMIN_ROLE_ID if is_admin else LEARNER_ROLE_ID

    # ── Fast path: check in caller's session (read-only) ─────────────────
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

    if user is not None:
        needs_update = (
            user.email != email
            or (not user.name or user.name != display_name)
            or (user.role_id != target_role_id)
        )
        if not needs_update:
            return user

    # ── Provision or update directly in caller's db session ───────────────
    # Uses the single connection already checked out by caller to prevent
    # connection pool exhaustion and deadlocks under concurrent requests.
    try:
        if user is None:
            user = User(
                id=user_id_int,
                name=display_name,
                email=email,
                role_id=target_role_id,
                hashed_password="",
                learning_status="none",
                daily_study_minutes=app_config.DEFAULT_DAILY_STUDY_MINUTES,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user
        else:
            updated = False
            if user.email != email:
                user.email = email
                updated = True
            if not user.name or user.name != display_name:
                user.name = display_name
                updated = True
            if user.role_id != target_role_id:
                user.role_id = target_role_id
                updated = True
            if updated:
                db.add(user)
                db.commit()
                db.refresh(user)
            return user
    except IntegrityError:
        # A concurrent request provisioned or updated this user at the exact same instant
        db.rollback()
        user = db.query(User).filter(User.id == user_id_int).first()
        if user is None:
            user = db.query(User).filter(User.email == email).first()
        if user is None:
            raise _credentials_exception()
        return user
    except Exception:
        db.rollback()
        raise


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
        authorization = request.headers.get("Authorization") or request.headers.get("authorization")
        if authorization and authorization.startswith("Bearer "):
            token = authorization.split(" ", 1)[1]

    if token:
        return token

    if not required:
        return None

    auth_h = request.headers.get("Authorization") or request.headers.get("authorization")
    logger.debug(f"401 on {request.method} {request.url.path}! AuthHeader={auth_h!r}")
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
    user = _get_or_provision_user(payload, db)
    return user


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
