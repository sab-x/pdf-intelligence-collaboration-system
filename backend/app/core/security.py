"""Password hashing and JWT helpers.

bcrypt has a hard 72-byte input limit. Passwords longer than that (as UTF-8
bytes) are explicitly rejected in hash_password rather than silently
truncated — silent truncation means two different passwords that agree on
their first 72 bytes hash identically, which is a correctness/security bug
disguised as a convenience.

JWT_SECRET / JWT_ALGORITHM / ACCESS_TOKEN_MINUTES / REFRESH_TOKEN_DAYS /
GUEST_TOKEN_HOURS are always read from settings — never hardcoded here.

Three token kinds, and decode_token enforces which one a caller will accept.
That enforcement is load-bearing: a guest token and a user access token are
both signed with the same secret, so without the `kind` check a guest JWT
presented to a user-only route would verify and be treated as a user. The
kind check is the only thing standing between those two, so nothing in this
module should ever be made lenient about it.
"""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings

BCRYPT_MAX_BYTES = 72

TokenKind = Literal["access", "refresh", "guest"]


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
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, str]:
    jti = jti or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "kind": kind,
        "jti": jti,
        "iat": now,
        "exp": now + expires_delta,
    }
    if extra_claims:
        # Merged after the reserved claims, but the caller is trusted code —
        # nothing here comes from a request body.
        payload.update(extra_claims)
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


def create_guest_token(
    *,
    guest_session_id: uuid.UUID,
    share_link_id: uuid.UUID,
    document_id: uuid.UUID,
) -> str:
    """Mint a guest JWT scoped to exactly one document — PROJECT_PLAN.md §4.

    Claims: kind="guest", sub/sid = guest_session_id, slid = share_link_id,
    doc = document_id.

    `doc` is carried for debuggability and as a cheap first filter, but it is
    NOT the authorization decision. require_document_access re-reads the
    share link from the database on every request, because a token is a
    frozen snapshot and revocation has to take effect immediately — a link
    revoked one second ago must not keep working for the remaining 24 hours
    of a token's life. The database is the authority; the claim is a hint.

    Deliberately NOT stored in a cookie by the frontend (sessionStorage
    instead), so it can never be replayed cross-tab as a user session.
    """
    token, _ = _create_token(
        subject=guest_session_id,
        kind="guest",
        expires_delta=timedelta(hours=settings.GUEST_TOKEN_HOURS),
        extra_claims={
            "sid": str(guest_session_id),
            "slid": str(share_link_id),
            "doc": str(document_id),
        },
    )
    return token


def decode_token(token: str, *, expected_kind: TokenKind) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("kind") != expected_kind:
        raise TokenError(f"expected a {expected_kind} token")
    return payload


def hash_reset_token(raw_token: str) -> str:
    """Hash a password-reset token for storage — PROJECT_PLAN-style follow-up.

    Plain SHA-256, deliberately not bcrypt. bcrypt's slowness exists to
    defend a low-entropy, human-chosen secret (a password) against offline
    brute force. A reset token is `secrets.token_urlsafe(32)` — 256 bits of
    randomness, the same primitive share_links uses for its token — and
    brute-forcing that is infeasible regardless of hash speed. A fast hash
    is correct here: it still means a database leak alone doesn't hand out
    usable reset tokens (nothing is stored in reversible or directly-usable
    form), without imposing bcrypt's per-hash cost on a value that gains
    nothing from it.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
