import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.auth import router as auth_router
from app.api.v1.comments import router as comments_router
from app.api.v1.documents import router as documents_router
from app.api.v1.search import router as search_router
from app.core.config import settings
from app.core.limiter import limiter

# Uvicorn only attaches handlers to its own uvicorn.* loggers, never to the
# root — so without this every app-level logger.info() (the whole successful
# ingestion path: "ingest: starting", "ingest: ready") is silently dropped,
# and only WARNING+ escapes via logging.lastResort. force=True because a
# no-op basicConfig (root already has a handler) would leave LOG_LEVEL
# quietly meaningless again, which is the exact bug this fixes.
logging.basicConfig(
    level=settings.LOG_LEVEL.upper(),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    force=True,
)

app = FastAPI(title="PDF Intelligence & Collaboration System", version="0.1.0")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(comments_router, prefix="/api/v1")
app.include_router(search_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.APP_ENV}
