"""
HTTP-level integration tests for POST /api/v1/admin/register-teacher.

These tests exercise the full FastAPI stack — routing, JWT auth, request
validation, service layer, and database — against an isolated test database.

The TestClient triggers the app's lifespan (migrations + default accounts),
so admin/admin123 is available without extra setup.

Two required cases:
  1. Successful registration by an admin → 201 with correct response body.
  2. Attempt by a non-admin (teacher role) → 403 Forbidden.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """
    TestClient that runs the full app lifespan (migrations + default accounts)
    against the isolated test database set by the autouse patch_env fixture.
    """
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _login(client: TestClient, username: str, password: str, role: str) -> str:
    """Authenticate and return the JWT access token."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password, "role": role},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Test 1: successful registration by an admin
# ---------------------------------------------------------------------------

class TestRegisterTeacherSuccess:

    def test_admin_can_register_teacher(self, client: TestClient):
        token = _login(client, "admin", "admin123", "admin")

        resp = client.post(
            "/api/v1/admin/register-teacher",
            headers=_auth_headers(token),
            json={
                "username": "dr_schmidt",
                "name": "Dr. Anna Schmidt",
                "email": "a.schmidt@uni-berlin.de",
                "password": "Secure1234!",
            },
        )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["username"] == "dr_schmidt"
        assert body["name"] == "Dr. Anna Schmidt"
        assert body["email"] == "a.schmidt@uni-berlin.de"
        assert body["role"] == "teacher"
        assert isinstance(body["account_id"], int)
        assert "successfully" in body["message"].lower()

    def test_registered_teacher_can_log_in(self, client: TestClient):
        token = _login(client, "admin", "admin123", "admin")
        client.post(
            "/api/v1/admin/register-teacher",
            headers=_auth_headers(token),
            json={
                "username": "prof_muller",
                "name": "Prof. Klaus Müller",
                "email": "k.muller@tu-munich.de",
                "password": "StrongPass99",
            },
        )

        login_resp = client.post(
            "/api/v1/auth/login",
            json={"username": "prof_muller", "password": "StrongPass99", "role": "teacher"},
        )
        assert login_resp.status_code == 200
        assert login_resp.json()["role"] == "teacher"

    def test_duplicate_username_returns_409(self, client: TestClient):
        token = _login(client, "admin", "admin123", "admin")
        payload = {
            "username": "unique_teacher",
            "name": "First Teacher",
            "email": "first@uni.de",
            "password": "Pass12345!",
        }
        resp1 = client.post("/api/v1/admin/register-teacher",
                            headers=_auth_headers(token), json=payload)
        assert resp1.status_code == 201

        payload["email"] = "second@uni.de"
        resp2 = client.post("/api/v1/admin/register-teacher",
                            headers=_auth_headers(token), json=payload)
        assert resp2.status_code == 409
        assert "already taken" in resp2.json()["detail"].lower()

    def test_short_password_rejected_by_api(self, client: TestClient):
        token = _login(client, "admin", "admin123", "admin")
        resp = client.post(
            "/api/v1/admin/register-teacher",
            headers=_auth_headers(token),
            json={
                "username": "bad_teacher",
                "name": "Bad Teacher",
                "email": "bad@uni.de",
                "password": "short",        # < 8 characters
            },
        )
        assert resp.status_code == 422  # Pydantic validation error


# ---------------------------------------------------------------------------
# Test 2: non-admin caller receives 403
# ---------------------------------------------------------------------------

class TestRegisterTeacherForbidden:

    def test_teacher_role_cannot_register_another_teacher(self, client: TestClient):
        token = _login(client, "teacher", "teacher123", "teacher")

        resp = client.post(
            "/api/v1/admin/register-teacher",
            headers=_auth_headers(token),
            json={
                "username": "new_teacher",
                "name": "New Teacher",
                "email": "new@uni.de",
                "password": "StrongPass99",
            },
        )

        assert resp.status_code == 403
        detail = resp.json().get("detail", "")
        assert "teacher" in detail.lower() or "authoris" in detail.lower()

    def test_unauthenticated_request_is_rejected(self, client: TestClient):
        resp = client.post(
            "/api/v1/admin/register-teacher",
            json={
                "username": "ghost",
                "name": "Ghost",
                "email": "ghost@uni.de",
                "password": "StrongPass99",
            },
        )
        # No Authorization header → HTTPBearer raises 401 (RFC-correct: no credentials)
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Test 3: course assignment on registration
# ---------------------------------------------------------------------------

class TestRegisterTeacherWithCourses:

    def _create_course(self, client: TestClient, token: str, code: str, name: str) -> int:
        resp = client.post(
            "/api/v1/courses/",
            headers=_auth_headers(token),
            json={"code": code, "name": name},
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    def test_courses_assigned_on_registration(self, client: TestClient):
        token = _login(client, "admin", "admin123", "admin")
        cid1 = self._create_course(client, token, "CS301", "Machine Learning")
        cid2 = self._create_course(client, token, "CS302", "Deep Learning")

        resp = client.post(
            "/api/v1/admin/register-teacher",
            headers=_auth_headers(token),
            json={
                "username": "dr_hoffmann",
                "name": "Dr. Eva Hoffmann",
                "email": "e.hoffmann@tu-berlin.de",
                "password": "SecurePass1!",
                "course_ids": [cid1, cid2],
            },
        )

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["courses_assigned"] == 2
        assert "2 course" in body["message"]

    def test_invalid_course_id_returns_404_before_account_is_created(
        self, client: TestClient
    ):
        token = _login(client, "admin", "admin123", "admin")
        nonexistent_id = 99999

        resp = client.post(
            "/api/v1/admin/register-teacher",
            headers=_auth_headers(token),
            json={
                "username": "dr_ghost_teacher",
                "name": "Dr. Ghost",
                "email": "ghost.teacher@uni.de",
                "password": "SecurePass1!",
                "course_ids": [nonexistent_id],
            },
        )

        assert resp.status_code == 404
        assert str(nonexistent_id) in resp.json()["detail"]

        # The account must NOT have been created (course validation runs first)
        login_resp = client.post(
            "/api/v1/auth/login",
            json={"username": "dr_ghost_teacher",
                  "password": "SecurePass1!", "role": "teacher"},
        )
        assert login_resp.status_code == 401

    def test_registration_without_courses_still_works(self, client: TestClient):
        token = _login(client, "admin", "admin123", "admin")

        resp = client.post(
            "/api/v1/admin/register-teacher",
            headers=_auth_headers(token),
            json={
                "username": "dr_no_courses",
                "name": "Dr. No Courses",
                "email": "no.courses@uni.de",
                "password": "SecurePass1!",
                # course_ids omitted — defaults to []
            },
        )

        assert resp.status_code == 201
        assert resp.json()["courses_assigned"] == 0
