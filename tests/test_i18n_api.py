from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import auth, models
from backend.api_errors import (
    ApiError,
    api_error_handler,
    http_error_handler,
    validation_error_handler,
)
from backend.routers import auth as auth_router
from backend.sqlite_db import Base, get_db


def _client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = session_factory()
    user = models.User(
        username="locale-user",
        email="locale@example.com",
        hashed_password="unused",
        role="admin",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id
    db.close()

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def override_current_user(db=Depends(get_db)):
        return db.get(models.User, user_id)

    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[auth.get_current_user] = override_current_user
    app.include_router(auth_router.router, prefix="/api")
    return TestClient(app), session_factory, user_id


def test_api_error_uses_stable_code_and_requested_language():
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)

    @app.get("/failure")
    def failure():
        raise ApiError(403, "test.permission_denied", "权限不足", "Permission denied")

    client = TestClient(app)
    english = client.get("/failure", headers={"Accept-Language": "en-US"})
    chinese = client.get("/failure", headers={"Accept-Language": "zh-CN"})

    assert english.status_code == 403
    assert english.json() == {
        "detail": "Permission denied",
        "error_code": "test.permission_denied",
        "error_params": {},
    }
    assert chinese.json()["detail"] == "权限不足"
    assert chinese.json()["error_code"] == "test.permission_denied"


def test_http_error_is_classified_and_localized():
    app = FastAPI()
    app.add_exception_handler(HTTPException, http_error_handler)

    @app.get("/legacy-failure")
    def legacy_failure():
        raise HTTPException(404, "Skill not found")

    response = TestClient(app).get(
        "/legacy-failure",
        headers={"Accept-Language": "zh-CN"},
    )
    assert response.json() == {
        "detail": "Skill 不存在",
        "error_code": "skill.not_found",
        "error_params": {},
    }

    english = TestClient(app).get(
        "/legacy-failure",
        headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    assert english.json()["detail"] == "Skill not found"
    assert english.json()["error_code"] == "skill.not_found"


def test_user_locale_preference_is_persisted():
    client, session_factory, user_id = _client()

    initial = client.get("/api/auth/users/me")
    assert initial.status_code == 200
    assert initial.json()["preferred_locale"] is None

    updated = client.put("/api/auth/users/me/locale", json={"locale": "en-US"})
    assert updated.status_code == 200
    assert updated.json() == {"locale": "en-US"}

    db = session_factory()
    try:
        assert db.get(models.User, user_id).preferred_locale == "en-US"
    finally:
        db.close()


def test_user_locale_preference_rejects_unsupported_locale():
    client, _, _ = _client()
    response = client.put("/api/auth/users/me/locale", json={"locale": "fr-FR"})
    assert response.status_code == 422


def test_validation_error_has_stable_localized_envelope():
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, validation_error_handler)

    @app.get("/items/{item_id}")
    def get_item(item_id: int):
        return {"item_id": item_id}

    response = TestClient(app).get(
        "/items/not-an-integer",
        headers={"Accept-Language": "en-US"},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "request.validation_failed"
    assert response.json()["detail"] == "Invalid request parameters"
    assert response.json()["error_params"]["errors"]
