import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from jose import jwt
from fastapi.testclient import TestClient

from app.main import app
from app.core.infra.config import app_config
from app.core.infra.database import get_db
from app.models.user import User, LEARNER_ROLE_ID, ADMIN_ROLE_ID

@pytest.fixture
def mock_db_session():
    """Create a mock SQLAlchemy session that returns a mock learner user."""
    mock_session = MagicMock()
    
    # Return a learner User when queried
    learner_user = User(
        id=999,
        email="learner@test.com",
        name="Test Learner",
        role_id=LEARNER_ROLE_ID,  # 1
        learning_status="none",
    )
    
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = learner_user
    mock_query.filter.return_value = mock_filter
    mock_session.query.return_value = mock_query

    return mock_session

@pytest.fixture
def client(mock_db_session):
    """FastAPI TestClient with overridden get_db dependency."""
    def _override_get_db():
        yield mock_db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

@pytest.fixture
def non_admin_token():
    """Generate a valid cryptographically signed JWT token for a non-admin learner."""
    payload = {
        "user_id": 999,
        "email": "learner@test.com",
        "name": "Test Learner",
        "role": "learner",
        "role_id": LEARNER_ROLE_ID,
        "token_type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, app_config.SECRET_KEY, algorithm=app_config.ALGORITHM)

TARGET_ENDPOINTS = [
    ("PATCH", "/api/admin/users/123/role", {"role_id": 2}),
    ("DELETE", "/api/admin/users/123", None),
    ("POST", "/api/admin/users/123/reset-learner", {}),
    ("POST", "/api/admin/roles/123/generate-topics", {}),
]

@pytest.mark.parametrize("method,path,payload", TARGET_ENDPOINTS)
def test_admin_endpoints_require_authentication(client, method, path, payload):
    """Without any Authorization header, every admin endpoint must return HTTP 401."""
    if method == "PATCH":
        res = client.patch(path, json=payload)
    elif method == "DELETE":
        res = client.delete(path)
    elif method == "POST":
        res = client.post(path, json=payload)
    else:
        raise ValueError(f"Unsupported method {method}")

    assert res.status_code == 401, f"Expected 401 for {method} {path}, got {res.status_code}: {res.text}"

@pytest.mark.parametrize("method,path,payload", TARGET_ENDPOINTS)
def test_admin_endpoints_reject_non_admin_users(client, non_admin_token, method, path, payload):
    """With a valid non-admin token, every admin endpoint must return HTTP 403 Forbidden."""
    headers = {"Authorization": f"Bearer {non_admin_token}"}
    if method == "PATCH":
        res = client.patch(path, json=payload, headers=headers)
    elif method == "DELETE":
        res = client.delete(path, headers=headers)
    elif method == "POST":
        res = client.post(path, json=payload, headers=headers)
    else:
        raise ValueError(f"Unsupported method {method}")

    assert res.status_code == 403, f"Expected 403 for {method} {path}, got {res.status_code}: {res.text}"
    assert "Requires admin privileges" in res.text or "admin" in res.text.lower()
