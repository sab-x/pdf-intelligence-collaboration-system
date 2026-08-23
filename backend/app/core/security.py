"""Password hashing and JWT helpers.

bcrypt has a hard 72-byte input limit. Passwords longer than that (as UTF-8
bytes) are explicitly rejected in hash_password rather than silently
truncated — silent truncation means two different passwords that agree on
their first 72 bytes hash identically, which is a correctness/security bug
disguised as a convenience.

JWT_SECRET / JWT_ALGORITHM / ACCESS_TOKEN_MINUTES / REFRESH_TOKEN_DAYS are
always read from settings — never hardcoded here.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

import bcrypt
import jwt

from app.core.config import settings

BCRYPT_MAX_BYTES = 72

TokenKind = Literal["access", "refresh"]


class PasswordTooLongError(ValueError):
    """Raised when a password exceeds bcrypt's 72-byte input limit."""


class TokenError(ValueError):
    """Raised when a JWT fails verification (bad signature, expired, wrong kind)."""


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > BCRYPT_MAX_BYTES:
        raise PasswordTooLongError(
            f"Password must be at most {BCRYPT_MAX_BYTES} bytes when UTF-8 encoded."
        )
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    password_bytes = password.encode("utf-8")
    if len(password_bytes) > BCRYPT_MAX_BYTES:
        return False
    return bcrypt.checkpw(password_bytes, password_hash.encode("utf-8"))


def _create_token(
    *,
    subject: uuid.UUID,
    kind: TokenKind,
    expires_delta: timedelta,
    jti: str | None = None,
) -> tuple[str, str]:
    jti = jti or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(subject),
        "kind": kind,
        "jti": jti,
        "iat": now,
        "exp": now + expires_delta,
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token, jti


def create_access_token(user_id: uuid.UUID) -> str:
    token, _ = _create_token(
        subject=user_id,
        kind="access",
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_MINUTES),
    )
    return token


def create_refresh_token(user_id: uuid.UUID, jti: str | None = None) -> tuple[str, str]:
    return _create_token(
        subject=user_id,
        kind="refresh",
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_DAYS),
        jti=jti,
    )


def decode_token(token: str, *, expected_kind: TokenKind) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("kind") != expected_kind:
        raise TokenError(f"expected a {expected_kind} token")
    return payload
