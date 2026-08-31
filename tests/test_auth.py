from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import (
    create_access_token,
    hash_password,
    init_admin_user,
    verify_access_token,
    verify_password,
)
from app.db import Base, get_db
from app.main import app
from app.models.entities import User


@pytest.fixture
def auth_client():
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    TestingSession = sessionmaker(bind=test_engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    # Seed admin user
    with TestingSession() as db:
        init_admin_user(db)

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_password_hashing():
    pwd = "MySecretPassword123!"
    hashed = hash_password(pwd)
    assert hashed.startswith("pbkdf2:sha256:")
    assert verify_password(pwd, hashed) is True
    assert verify_password("WrongPassword", hashed) is False


def test_token_creation_and_verification():
    token = create_access_token(user_id=42, username="testadmin", expires_in_seconds=3600)
    assert "." in token
    payload = verify_access_token(token)
    assert payload is not None
    assert payload["user_id"] == 42
    assert payload["username"] == "testadmin"

    # Token con firma adulterada
    fake_token = token[:-4] + "abcd"
    assert verify_access_token(fake_token) is None


def test_login_api_success(auth_client):
    res = auth_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin1234"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["user"]["username"] == "admin"
    assert "jira_session_token" in res.cookies


def test_login_api_invalid_credentials(auth_client):
    res = auth_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrongpassword"},
    )
    assert res.status_code == 401
    assert "detail" in res.json()


def test_logout(auth_client):
    res = auth_client.get("/logout", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/login"


def test_protected_routes_redirect_to_login(auth_client):
    # Sin sesión debe redirigir al login
    res = auth_client.get("/", follow_redirects=False)
    assert res.status_code == 303
    assert res.headers["location"] == "/login"

    # Con cookie válida debe responder 200
    login_res = auth_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin1234"},
    )
    cookie_token = login_res.cookies.get("jira_session_token")
    auth_client.cookies.set("jira_session_token", cookie_token)

    res_auth = auth_client.get("/", follow_redirects=False)
    assert res_auth.status_code == 200
