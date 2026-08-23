"""Auth flow tests — run against a dedicated test database (see conftest.py).

Covers: signup -> login -> me; wrong password -> 401; duplicate email -> 409;
password is stored as a bcrypt hash, not plaintext; a rotated or logged-out
refresh token is rejected on reuse.
"""
import bcrypt
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db.session import async_session_maker
from app.models.user import User

pytestmark = pytest.mark.asyncio

PASSWORD = "correct-horse-battery-staple"


async def _signup(client: AsyncClient, email: str, password: str = PASSWORD) -> dict:
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"name": "Test User", "email": email, "password": password},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login(client: AsyncClient, email: str, password: str = PASSWORD):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def test_signup_login_me(client: AsyncClient, unique_email: str) -> None:
    signup_body = await _signup(client, unique_email)
    assert signup_body["user"]["email"] == unique_email
    assert "access_token" in signup_body

    login_resp = await _login(client, unique_email)
    assert login_resp.status_code == 200
    access_token = login_resp.json()["access_token"]

    me_resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert me_resp.status_code == 200
    body = me_resp.json()
    assert body["email"] == unique_email
    assert "password_hash" not in body


async def test_login_wrong_password_returns_401(client: AsyncClient, unique_email: str) -> None:
    await _signup(client, unique_email)

    resp = await _login(client, unique_email, password="definitely-the-wrong-password")
    assert resp.status_code == 401


async def test_duplicate_email_signup_returns_409(client: AsyncClient, unique_email: str) -> None:
    await _signup(client, unique_email)

    resp = await client.post(
        "/api/v1/auth/signup",
        json={"name": "Someone Else", "email": unique_email, "password": "another-password-123"},
    )
    assert resp.status_code == 409


async def test_password_is_hashed_not_plaintext(client: AsyncClient, unique_email: str) -> None:
    await _signup(client, unique_email, password=PASSWORD)

    async with async_session_maker() as db:
        stored_user = await db.scalar(select(User).where(User.email == unique_email))

    assert stored_user is not None
    assert stored_user.password_hash != PASSWORD
    assert stored_user.password_hash.startswith(("$2a$", "$2b$", "$2y$"))
    assert bcrypt.checkpw(PASSWORD.encode("utf-8"), stored_user.password_hash.encode("utf-8"))


async def test_rotated_refresh_token_rejected_on_reuse(
    client: AsyncClient, unique_email: str
) -> None:
    await _signup(client, unique_email)
    login_resp = await _login(client, unique_email)
    assert login_resp.status_code == 200
    old_refresh_cookie = client.cookies.get("refresh_token")
    assert old_refresh_cookie is not None

    first_refresh = await client.post("/api/v1/auth/refresh")
    assert first_refresh.status_code == 200

    # Replay the pre-rotation cookie — it must now be rejected.
    client.cookies.set("refresh_token", old_refresh_cookie)
    reused = await client.post("/api/v1/auth/refresh")
    assert reused.status_code == 401


async def test_logged_out_refresh_token_rejected(client: AsyncClient, unique_email: str) -> None:
    await _signup(client, unique_email)
    login_resp = await _login(client, unique_email)
    assert login_resp.status_code == 200
    stolen_cookie = client.cookies.get("refresh_token")
    assert stolen_cookie is not None

    logout_resp = await client.post("/api/v1/auth/logout")
    assert logout_resp.status_code == 204

    # Simulate reuse of a captured token after logout.
    client.cookies.set("refresh_token", stolen_cookie)
    after_logout = await client.post("/api/v1/auth/refresh")
    assert after_logout.status_code == 401
