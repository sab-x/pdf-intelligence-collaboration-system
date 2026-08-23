"""Application settings loaded from environment variables.

Every value used by services must come from here — never hardcode secrets,
model IDs, or URLs elsewhere. Missing/invalid required vars raise at import
time (get_settings()), so the app refuses to boot rather than 500ing later.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # ---------- App ----------
    APP_ENV: Literal["development", "production"] = "development"
    LOG_LEVEL: str = "INFO"

    # ---------- Database ----------
    DATABASE_URL: str
    MIGRATION_DATABASE_URL: str

    # ---------- Auth ----------
    JWT_SECRET: str = Field(min_length=32)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 7
    GUEST_TOKEN_HOURS: int = 24
    BCRYPT_ROUNDS: int = 12

    # ---------- Google Gemini ----------
    GEMINI_API_KEY: str
    GEMINI_SUMMARY_MODEL: str = "gemini-2.5-flash"
    GEMINI_CHAT_MODEL: str = "gemini-2.5-flash"
    GEMINI_FAST_MODEL: str = "gemini-2.5-flash-lite"
    GEMINI_EMBED_MODEL: str = "gemini-embedding-001"
    EMBED_DIM: int = 768
    LLM_TIMEOUT_SECONDS: int = 60
    LLM_MAX_RETRIES: int = 3

    # ---------- Supabase Storage ----------
    SUPABASE_URL: str
    SUPABASE_SERVICE_KEY: str
    SUPABASE_BUCKET: str = "documents"
    SIGNED_URL_TTL_SECONDS: int = 900

    # ---------- Uploads ----------
    MAX_UPLOAD_MB: int = 20
    MAX_PAGES: int = 500

    # ---------- RAG tuning ----------
    CHUNK_TARGET_TOKENS: int = 1000
    CHUNK_OVERLAP_TOKENS: int = 150
    RETRIEVAL_TOP_K: int = 6
    RETRIEVAL_CANDIDATES: int = 12
    SEMANTIC_SEARCH_THRESHOLD: float = 0.55
    DIRECT_SUMMARY_CHAR_LIMIT: int = 400_000
    CHAT_HISTORY_TURNS: int = 5

    # ---------- Email — out of scope ----------
    EMAIL_ENABLED: bool = False

    # ---------- URLs / CORS ----------
    FRONTEND_URL: str = "http://localhost:5173"
    BACKEND_URL: str = "http://localhost:8000"

    # ---------- Rate limits ----------
    RATE_LIMIT_AUTH: str = "5/minute"
    RATE_LIMIT_FORGOT_PASSWORD: str = "3/hour"
    RATE_LIMIT_CHAT: str = "20/minute"
    RATE_LIMIT_CHAT_PER_SHARE_LINK: str = "60/hour"
    RATE_LIMIT_UPLOAD: str = "10/hour"
    MAX_CHAT_MESSAGES_PER_DOCUMENT_PER_DAY: int = 200

    @field_validator("DATABASE_URL", "MIGRATION_DATABASE_URL")
    @classmethod
    def _must_use_asyncpg(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("must use the postgresql+asyncpg:// scheme")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
