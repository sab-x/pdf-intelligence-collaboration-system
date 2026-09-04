"""Auth routes: signup, login, refresh, logout, me — PROJECT_PLAN.md §3, §4.

The refresh token is an httpOnly + Secure + SameSite=Lax cookie scoped to
/api/v1/auth. Its jti is persisted in refresh_tokens and rotated on every use
(the old row gets revoked_at + replaced_by pointing at the new row). Logout
revokes every still-active row for the user, so a captured token can't be
replayed after logout — stateless refresh tokens would make that lie.
"""
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.limiter import limiter
from app.core.security import (
    PasswordTooLongError,
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_reset_token,
    verify_password,
)
from app.db.session import get_db
from app.models.password_reset_token import PasswordResetToken
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import (
    AccessTokenResponse,
    ForgotPasswordRequest,
    LoginRequest,
    MessageResponse,
    ResetPasswordRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/api/v1/auth"
RESET_TOKEN_BYTES = 32
# Same generic copy for both branches of forgot-password — see the route
# docstring for why this can never differ by whether the account exists.
_FORGOT_PASSWORD_GENERIC_MESSAGE = (
    "If an account exists for that email, a password reset link has been sent."
)
_bearer_scheme = HTTPBearer(auto_error=False)


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
        max_age=settings.REFRESH_TOKEN_DAYS * 24 * 60 * 60,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="lax",
    )


async def _issue_refresh_token(
    db: AsyncSession, user_id: uuid.UUID, user_agent: str | None
) -> tuple[str, RefreshToken]:
    token, jti = create_refresh_token(user_id)
    row = RefreshToken(
        user_id=user_id,
        jti=jti,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_DAYS),
        user_agent=user_agent,
    )
    db.add(row)
    await db.flush()
    return token, row


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = decode_token(credentials.credentials, expected_kind="access")
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired access token") from exc
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def signup(
    request: Request,
    response: Response,
    body: SignupRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")

    try:
        password_hash = hash_password(body.password)
    except PasswordTooLongError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    user = User(name=body.name, email=body.email, password_hash=password_hash)
    db.add(user)
    await db.flush()

    access_token = create_access_token(user.id)
    refresh_token, _ = await _issue_refresh_token(db, user.id, request.headers.get("user-agent"))
    await db.commit()

    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(access_token=access_token, user=UserResponse.model_validate(user))


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")

    access_token = create_access_token(user.id)
    refresh_token, _ = await _issue_refresh_token(db, user.id, request.headers.get("user-agent"))
    await db.commit()

    _set_refresh_cookie(response, refresh_token)
    return TokenResponse(access_token=access_token, user=UserResponse.model_validate(user))


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> AccessTokenResponse:
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if raw_token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token")

    try:
        payload = decode_token(raw_token, expected_kind="refresh")
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired refresh token") from exc

    row = await db.scalar(select(RefreshToken).where(RefreshToken.jti == payload["jti"]))
    if row is None or row.revoked_at is not None or row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token has been revoked or expired")

    user_id = uuid.UUID(payload["sub"])
    new_token, new_row = await _issue_refresh_token(db, user_id, request.headers.get("user-agent"))

    row.revoked_at = datetime.now(timezone.utc)
    row.replaced_by = new_row.id
    await db.commit()

    access_token = create_access_token(user_id)
    _set_refresh_cookie(response, new_token)
    return AccessTokenResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> None:
    raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if raw_token is not None:
        try:
            payload = decode_token(raw_token, expected_kind="refresh")
        except TokenError:
            payload = None
        if payload is not None:
            await db.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.user_id == uuid.UUID(payload["sub"]),
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(timezone.utc))
            )
            await db.commit()

    _clear_refresh_cookie(response)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(user)


@router.post("/forgot-password", response_model=MessageResponse)
@limiter.limit(settings.RATE_LIMIT_FORGOT_PASSWORD)
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Issue a reset link — never reveals whether the email has an account.

    Same non-enumeration principle as require_document_access returning 404
    for a stranger: an attacker probing this endpoint must not be able to
    tell "no such account" apart from "email sent" by response shape,
    status code, or timing category. Both branches return the identical
    200 + generic message; the only difference is whether a row and a log
    line get written, and neither is observable from the response.

    Email delivery is out of scope for this project (same reason share-link
    notifications are: no verified sending domain). The reset link is
    logged instead, which is an honest stand-in for a dev/demo environment
    — call this out explicitly if asked in review, don't pretend it emails.
    """
    user = await db.scalar(select(User).where(User.email == body.email))
    if user is not None:
        raw_token = secrets.token_urlsafe(RESET_TOKEN_BYTES)
        row = PasswordResetToken(
            user_id=user.id,
            token_hash=hash_reset_token(raw_token),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.RESET_TOKEN_MINUTES),
        )
        db.add(row)
        await db.commit()

        reset_link = f"{settings.FRONTEND_URL}/reset-password?token={raw_token}"
        logger.info("Password reset requested for user_id=%s. Reset link: %s", user.id, reset_link)

    return MessageResponse(message=_FORGOT_PASSWORD_GENERIC_MESSAGE)


@router.post("/reset-password", response_model=MessageResponse)
@limiter.limit(settings.RATE_LIMIT_FORGOT_PASSWORD)
async def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Consume a reset token: set the new password, then log out everywhere.

    The token itself (not the email) is the credential here, so there's no
    enumeration concern in returning a specific "invalid or expired" error
    — a bare secrets.token_urlsafe(32) is not guessable, so a 400 here only
    ever means the link was already used, expired, or mistyped.

    Revoking every refresh_tokens row for this user on success mirrors what
    /auth/logout does, and matters more here: if the reset was triggered
    because the account was compromised, a session an attacker is already
    holding must not survive the password change.
    """
    token_hash = hash_reset_token(body.token)
    row = await db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    if (
        row is None
        or row.used_at is not None
        or row.expires_at < datetime.now(timezone.utc)
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This reset link is invalid or has expired.")

    try:
        password_hash = hash_password(body.password)
    except PasswordTooLongError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    user = await db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This reset link is invalid or has expired.")

    user.password_hash = password_hash
    row.used_at = datetime.now(timezone.utc)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()

    return MessageResponse(message="Your password has been reset. Please log in again.")
