from fastapi import Depends, HTTPException, status

from app.core.dependencies import get_current_user
from app.models.user import User

ADMIN_ROLE_ID = 2


def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """Require a valid JWT and role_id == 2 (admin)."""
    if current_user.role_id != ADMIN_ROLE_ID:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires admin privileges.",
        )
    return current_user
