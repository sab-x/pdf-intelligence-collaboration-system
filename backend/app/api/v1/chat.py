"""RAG chat — PROJECT_PLAN.md §3, §7.

## The streaming session trap

FastAPI tears down `yield` dependencies BEFORE a StreamingResponse body is
consumed. A `Depends(get_db)` session is therefore already closed by the
time the generator runs, and every query inside it fails with an error that
points at SQLAlchemy rather than at this design. The generator opens its own
session with `async_session_maker()` and owns its whole lifetime.

The request-scoped session is used for exactly one thing: validating and
creating the chat session BEFORE streaming starts, so an authorization
failure is a real 403/404 with a status code, not an `error` event inside a
200 response that the browser has already committed to.

## Two independent authorization checks

`require_document_access` decides whether you may see this DOCUMENT. It says
nothing about whose CONVERSATION you may read. A guest holding a valid share
link could otherwise read the owner's chat history by guessing a session id.
`_load_session` is the second check, and PROJECT_PLAN.md §11 has a test for
exactly this.

## Persistence in `finally`

A user who closes the tab mid-answer has still asked a question and still
received part of an answer. Persisting in a `finally` means an aborted
stream saves what actually happened rather than vanishing — reopening the
conversation shows the truncated answer instead of a question with no reply.
"""
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import Access, Principal, require_document_access, resolve_principal
from app.core.limiter import limiter
from app.db.session import async_session_maker, get_db
from app.models.chat import ChatMessage, ChatSession
from app.models.document import Document
from app.schemas.chat import (
    ChatHistoryResponse,
    ChatMessageResponse,
    ChatRequest,
    Citation,
)
from app.services.ai import CHAT_UNAVAILABLE_MESSAGE, LLMUnavailableError, stream_answer
from app.services.retrieval import RetrievedChunk, build_context, retrieve

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

NO_CONTENT_MESSAGE = (
    "This document hasn't been indexed for chat yet. If it was just uploaded, "
    "give it a moment and try again."
)


def _sse(event: str, payload: dict) -> str:
    """One SSE frame.

    json.dumps for the data line specifically because SSE is newline
    delimited — a raw answer containing a newline would silently split into
    two frames and corrupt the stream. JSON escaping makes that impossible.
    """
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


def _principal_owns(session: ChatSession, principal: Principal) -> bool:
    """Does this principal own this conversation?

    Compared per kind rather than by "either column matches", so a guest can
    never match a user-owned row by both being None.
    """
    if principal.kind == "guest":
        return (
            principal.guest_session_id is not None
            and session.guest_session_id == principal.guest_session_id
        )
    return principal.user_id is not None and session.user_id == principal.user_id


async def _load_session(
    db: AsyncSession,
    document: Document,
    principal: Principal,
    session_id: uuid.UUID | None,
) -> ChatSession:
    """Resolve or create the conversation. 404 on anything not the caller's.

    Not 403: an unrelated session id is a stranger's, and confirming it
    exists would leak that someone else is chatting about this document.
    """
    if session_id is not None:
        session = await db.get(ChatSession, session_id)
        if (
            session is None
            or session.document_id != document.id
            or not _principal_owns(session, principal)
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat session not found")
        return session

    session = ChatSession(
        document_id=document.id,
        user_id=principal.user_id if principal.kind == "user" else None,
        guest_session_id=principal.guest_session_id if principal.kind == "guest" else None,
    )
    db.add(session)
    await db.flush()
    return session


async def _enforce_daily_cap(db: AsyncSession, document: Document) -> None:
    """Per-document daily message cap — a cost backstop on a free API key.

    Counts user turns rather than assistant turns: a failed answer still
    cost a retrieval and a generation attempt.
    """
    since = datetime.now(timezone.utc) - timedelta(days=1)
    count = await db.scalar(
        select(func.count(ChatMessage.id))
        .join(ChatSession, ChatMessage.session_id == ChatSession.id)
        .where(
            ChatSession.document_id == document.id,
            ChatMessage.role == "user",
            ChatMessage.created_at >= since,
        )
    )
    if (count or 0) >= settings.MAX_CHAT_MESSAGES_PER_DOCUMENT_PER_DAY:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "This document has reached its daily question limit. Try again tomorrow.",
        )


async def _load_history(db: AsyncSession, session_id: uuid.UUID) -> list[ChatMessage]:
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return list(result.scalars().all())


def _citations(chunks: list[RetrievedChunk]) -> list[dict]:
    return [
        {
            "chunk_id": chunk.id,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "excerpt": chunk.content,
            "matched_by": list(chunk.matched_by),
        }
        for chunk in chunks
    ]


@router.post("/documents/{document_id}/chat")
@limiter.limit(settings.RATE_LIMIT_CHAT)
async def chat(
    request: Request,
    body: ChatRequest,
    access: tuple[Document, Access] = Depends(require_document_access(Access.VIEW)),
    principal: Principal = Depends(resolve_principal),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Ask a question. Responds with SSE: citations, token*, done | error."""
    document, _granted = access

    # Everything that can legitimately fail with a status code happens here,
    # on the request-scoped session, BEFORE the response starts streaming.
    await _enforce_daily_cap(db, document)
    session = await _load_session(db, document, principal, body.session_id)
    history_rows = await _load_history(db, session.id)
    history = [(row.role, row.content) for row in history_rows]

    user_message = ChatMessage(session_id=session.id, role="user", content=body.message)
    db.add(user_message)
    await db.commit()

    # Bind primitives, not ORM objects: `db` closes when this function
    # returns and any attribute access on a detached instance inside the
    # generator would raise.
    session_id = session.id
    document_id = str(document.id)
    message = body.message

    async def event_stream() -> AsyncIterator[str]:
        answer_parts: list[str] = []
        citations: list[dict] = []

        # Its own session. See the module docstring — this is the single
        # most common FastAPI streaming bug and the reason this generator
        # does not touch `db`.
        async with async_session_maker() as stream_db:
            try:
                # retrieve() opens its own sessions so the vector and text
                # searches can run concurrently — see its docstring.
                chunks, search_query = await retrieve(
                    document_id=document_id,
                    message=message,
                    history=history,
                )

                if not chunks:
                    # No indexed content. Not an error — a truthful answer.
                    yield _sse("token", {"text": NO_CONTENT_MESSAGE})
                    answer_parts.append(NO_CONTENT_MESSAGE)
                    yield _sse("done", {"session_id": str(session_id)})
                    return

                citations = _citations(chunks)
                # Sent BEFORE the tokens so the "grounded in" panel is
                # populated while the answer is still arriving — the reader
                # can see what the model was given as it writes.
                yield _sse("citations", {"citations": citations, "query": search_query})

                async for token in stream_answer(
                    context=build_context(chunks), history=history, message=message
                ):
                    answer_parts.append(token)
                    yield _sse("token", {"text": token})

                yield _sse("done", {"session_id": str(session_id)})

            except LLMUnavailableError:
                # Raised only when nothing was emitted, so there is no
                # partial answer to contradict.
                yield _sse("error", {"message": CHAT_UNAVAILABLE_MESSAGE})
            except Exception:
                logger.exception("chat stream failed for document %s", document_id)
                yield _sse("error", {"message": CHAT_UNAVAILABLE_MESSAGE})
            finally:
                # Runs on client disconnect too — a closed tab mid-answer
                # still saves what was generated.
                answer = "".join(answer_parts).strip()
                if answer:
                    try:
                        stream_db.add(
                            ChatMessage(
                                session_id=session_id,
                                role="assistant",
                                content=answer,
                                citations=citations or None,
                            )
                        )
                        await stream_db.commit()
                    except Exception:
                        logger.exception("could not persist assistant message")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # Without this nginx and friends buffer the whole body and
            # deliver it in one lump — the stream still "works" and the
            # token-by-token effect is entirely gone.
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get(
    "/documents/{document_id}/chat/history",
    response_model=ChatHistoryResponse,
)
async def chat_history(
    session_id: uuid.UUID,
    access: tuple[Document, Access] = Depends(require_document_access(Access.VIEW)),
    principal: Principal = Depends(resolve_principal),
    db: AsyncSession = Depends(get_db),
) -> ChatHistoryResponse:
    """Prior turns. Same two-check authorization as POST — document access
    is not enough, the session must be the caller's.
    """
    document, _granted = access
    session = await _load_session(db, document, principal, session_id)
    rows = await _load_history(db, session.id)

    return ChatHistoryResponse(
        session_id=session.id,
        messages=[
            ChatMessageResponse(
                id=row.id,
                role=row.role,  # type: ignore[arg-type]
                content=row.content,
                citations=(
                    [Citation.model_validate(c) for c in row.citations]
                    if row.citations
                    else None
                ),
                created_at=row.created_at,
            )
            for row in rows
        ],
    )
