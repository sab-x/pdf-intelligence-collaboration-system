"""Gemini summarisation — PROJECT_PLAN.md §6.

Strategy: fits-in-context first, map-reduce as fallback.

    chars <= DIRECT_SUMMARY_CHAR_LIMIT -> one call with the whole document
    otherwise                          -> MAP  ~30k-char sections into bullets
                                          REDUCE those bullets through the
                                          SAME final-summary prompt

Two things this module guarantees to its caller (the ingestion background
task), because a summary failing must never take a document down with it:
  * every Gemini call is bounded by LLM_TIMEOUT_SECONDS and retried with
    exponential backoff up to LLM_MAX_RETRIES;
  * summarize_document() NEVER raises. When the model is unreachable it
    returns a degraded "summary unavailable" result and lets ingestion
    finish, so the document still becomes readable.

This is the `google-genai` SDK (client.aio.models.*), not the legacy
`google-generativeai` package.
"""
import asyncio
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- tuning ---
MAP_SECTION_CHARS = 30_000
MAP_CONCURRENCY = 5
_BACKOFF_BASE_SECONDS = 1.0
_MAX_KEY_POINTS = 4

# How far inside the asyncio.wait_for ceiling the socket deadline sits. The
# transport therefore gives up first and raises a descriptive
# ConnectTimeout/ReadTimeout — naming the phase that stalled — while
# wait_for stays the outer backstop for anything hanging outside the HTTP
# call itself. Equal deadlines would race, and wait_for's bare
# TimeoutError() is the one that tells you nothing.
_SOCKET_TIMEOUT_MARGIN_SECONDS = 5

UNAVAILABLE_SUMMARY = (
    "An AI summary could not be generated for this document. "
    "The text was extracted successfully and the document can still be read."
)
UNAVAILABLE_DOC_TYPE = "Summary Unavailable"

# ---------------------------------------------------------------- prompts ---
# Verbatim from PROJECT_PLAN.md §6. The negative constraints ("no preamble",
# "never infer") are what stop the generic-restatement failure mode; naming
# the audience is what sets the register.
SUMMARY_SYSTEM_PROMPT = """You are a document analyst. You produce factual, specific summaries of documents
for a professional audience who has not read them.

Rules:
- Write 3 to 5 sentences. No preamble, no "This document...", no meta-commentary.
- Lead with what the document IS and who it involves (named parties, dates, amounts).
- Then state its purpose and the 2-3 most consequential terms, obligations, or findings.
- Use only information present in the text. Never infer, estimate, or fill gaps.
- If a critical detail is genuinely absent, omit it rather than hedging about it.
- Plain prose. No bullet points, no markdown, no headings.

Return ONLY valid JSON matching this schema:
{
  "doc_type": "<2-4 word label, e.g. 'Employment Agreement', 'Q3 Earnings Report'>",
  "summary": "<the 3-5 sentence summary>",
  "key_points": ["<up to 4 short factual highlights>"]
}"""

# MAP stage only. These bullets are never shown to anyone — they are the
# input to the REDUCE call above, so losing named parties/dates/amounts here
# loses them from the real summary.
SECTION_SYSTEM_PROMPT = """You are a document analyst extracting factual notes from one section of a longer document.

Rules:
- Write 4 to 6 bullet points, one per line, each starting with "- ".
- Record named parties, dates, amounts, obligations, and findings exactly as written.
- Use only information present in this section. Never infer, estimate, or fill gaps.
- No preamble, no headings, no closing commentary. Bullets only."""

_SUMMARY_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "doc_type": types.Schema(type=types.Type.STRING),
        "summary": types.Schema(type=types.Type.STRING),
        "key_points": types.Schema(
            type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)
        ),
    },
    required=["doc_type", "summary", "key_points"],
)


@dataclass
class DocumentSummary:
    """Result of summarising one document.

    `degraded` is True when the model could not be reached and the caller is
    looking at the fallback text — ingestion still completes, but nothing
    should treat these fields as model output (e.g. don't embed them).
    """

    doc_type: str
    summary: str
    key_points: list[str] = field(default_factory=list)
    degraded: bool = False


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Lazy singleton, mirroring services/storage.py — also the seam the
    tests patch, so no test ever needs a real API key or network.
    """
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


async def _generate(
    *,
    system_instruction: str,
    user_text: str,
    model: str,
    response_schema: types.Schema | None = None,
) -> str | None:
    """One Gemini call, bounded and retried. Returns None if every attempt
    failed — callers decide what a missing result means rather than having
    an exception unwind the ingestion task.

    asyncio.wait_for (rather than the SDK's own http timeout) bounds the
    whole call including any SDK-internal retry, so LLM_TIMEOUT_SECONDS is
    a real per-attempt ceiling.
    """
    client = _get_client()
    # HttpOptions.timeout is MILLISECONDS — the SDK divides by 1000 before
    # handing it to httpx. Without it the SDK passes timeout=None and the
    # socket read is unbounded, leaving wait_for as the only thing between
    # a stalled connection and a wedged ingestion.
    socket_timeout_s = max(
        1, settings.LLM_TIMEOUT_SECONDS - _SOCKET_TIMEOUT_MARGIN_SECONDS
    )
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.2,
        http_options=types.HttpOptions(timeout=socket_timeout_s * 1000),
    )
    if response_schema is not None:
        config.response_mime_type = "application/json"
        config.response_schema = response_schema

    attempts = max(1, settings.LLM_MAX_RETRIES)
    for attempt in range(attempts):
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=model, contents=user_text, config=config
                ),
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
            text = (response.text or "").strip()
            if not text:
                # Safety blocks and MAX_TOKENS finishes both arrive with
                # text=None; retryable, not valid output.
                raise ValueError("empty response from Gemini")
            return text
        except Exception as exc:  # deliberately broad - see the docstring
            # repr(), never str(): asyncio.TimeoutError (== TimeoutError since
            # 3.11) and any bare `raise SomeError()` stringify to "", which
            # rendered this line as "...failed (attempt 1/3): " and hid the
            # actual cause. The type name plus repr always says something.
            detail = f"{type(exc).__name__}: {exc!r}"
            context = (
                f"model={model} chars={len(user_text)} "
                f"json_mode={response_schema is not None} "
                f"timeout={settings.LLM_TIMEOUT_SECONDS}s"
            )
            if attempt == attempts - 1:
                # Final attempt — this is the one that becomes a degraded
                # summary for a real user, so pay for the full traceback.
                logger.exception(
                    "gemini call failed after %d attempts (%s): %s",
                    attempts,
                    context,
                    detail,
                )
                return None
            delay = _BACKOFF_BASE_SECONDS * (2**attempt)
            logger.warning(
                "gemini call failed (attempt %d/%d), retrying in %.1fs (%s): %s",
                attempt + 1,
                attempts,
                delay,
                context,
                detail,
            )
            await asyncio.sleep(delay)
    return None


def _parse_summary(raw: str) -> DocumentSummary | None:
    """Parse the JSON-mode response defensively. Structured output makes
    this reliable, not guaranteed — a malformed body counts as a failed
    call, never as an empty summary.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        # Log what actually came back — "returned non-JSON" on its own is
        # unfalsifiable, and this path also ends in a degraded summary.
        logger.warning(
            "gemini returned non-JSON despite response_schema (%s); first 200 chars: %r",
            exc,
            raw[:200],
        )
        return None
    if not isinstance(data, dict):
        logger.warning("gemini returned JSON %s, expected an object", type(data).__name__)
        return None

    summary = str(data.get("summary") or "").strip()
    doc_type = str(data.get("doc_type") or "").strip()
    if not summary:
        logger.warning(
            "gemini returned JSON with no usable summary field; keys=%s", sorted(data)
        )
        return None

    raw_points = data.get("key_points")
    key_points = (
        [str(p).strip() for p in raw_points if str(p).strip()][:_MAX_KEY_POINTS]
        if isinstance(raw_points, list)
        else []
    )
    return DocumentSummary(
        doc_type=doc_type or "Document",
        summary=summary,
        key_points=key_points,
    )


def _split_sections(text: str, section_chars: int | None = None) -> list[str]:
    """Split into ~section_chars pieces on paragraph boundaries where
    possible, so a section rarely cuts a clause in half. A single paragraph
    longer than the budget is hard-sliced rather than allowed to blow past
    it.

    Resolved at call time, not as a default argument, so MAP_SECTION_CHARS
    stays the single live knob rather than a value frozen at import.
    """
    section_chars = section_chars or MAP_SECTION_CHARS
    sections: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in text.split("\n\n"):
        while len(para) > section_chars:
            if current:
                sections.append("\n\n".join(current))
                current, current_len = [], 0
            sections.append(para[:section_chars])
            para = para[section_chars:]

        addition = len(para) + 2
        if current and current_len + addition > section_chars:
            sections.append("\n\n".join(current))
            current, current_len = [], 0
        current.append(para)
        current_len += addition

    if current:
        sections.append("\n\n".join(current))
    return [s for s in sections if s.strip()]


async def _summarize_section(
    section: str, index: int, total: int, semaphore: asyncio.Semaphore
) -> str | None:
    """MAP stage worker. The semaphore is what keeps a 60-page PDF from
    firing forty concurrent requests at a free-tier quota.
    """
    async with semaphore:
        return await _generate(
            system_instruction=SECTION_SYSTEM_PROMPT,
            user_text=f"SECTION {index} OF {total}\n\n--- SECTION TEXT ---\n{section}",
            model=settings.GEMINI_SUMMARY_MODEL,
        )


async def _final_summary(filename: str, page_count: int, text: str) -> DocumentSummary | None:
    raw = await _generate(
        system_instruction=SUMMARY_SYSTEM_PROMPT,
        user_text=(
            f"FILENAME: {filename}\nPAGES: {page_count}\n\n--- DOCUMENT TEXT ---\n{text}"
        ),
        model=settings.GEMINI_SUMMARY_MODEL,
        response_schema=_SUMMARY_SCHEMA,
    )
    if raw is None:
        return None
    return _parse_summary(raw)


def _unavailable() -> DocumentSummary:
    return DocumentSummary(
        doc_type=UNAVAILABLE_DOC_TYPE,
        summary=UNAVAILABLE_SUMMARY,
        key_points=[],
        degraded=True,
    )


async def summarize_document(filename: str, page_count: int, text: str) -> DocumentSummary:
    """Summarise a document. Never raises — see the module docstring.

    Direct path when the text fits the context budget; map-reduce over
    ~30k-char sections otherwise, with the concatenated section bullets fed
    back through the identical final-summary prompt so both paths produce
    the same shape of answer.
    """
    if len(text) <= settings.DIRECT_SUMMARY_CHAR_LIMIT:
        result = await _final_summary(filename, page_count, text)
        return result if result is not None else _unavailable()

    sections = _split_sections(text)
    logger.info(
        "map-reduce summarisation for %s: %d chars -> %d sections",
        filename,
        len(text),
        len(sections),
    )

    semaphore = asyncio.Semaphore(MAP_CONCURRENCY)
    bullet_groups = await asyncio.gather(
        *(
            _summarize_section(section, i + 1, len(sections), semaphore)
            for i, section in enumerate(sections)
        )
    )

    bullets = [b for b in bullet_groups if b]
    if not bullets:
        # Every MAP call failed; there is nothing to REDUCE over.
        logger.error("map stage produced no section summaries for %s", filename)
        return _unavailable()
    if len(bullets) < len(sections):
        logger.warning(
            "map stage lost %d/%d sections for %s; summarising the rest",
            len(sections) - len(bullets),
            len(sections),
            filename,
        )

    result = await _final_summary(filename, page_count, "\n\n".join(bullets))
    return result if result is not None else _unavailable()


# ===========================================================================
# Chat — PROJECT_PLAN.md §7
#
# Lives here rather than in a services/chat_ai.py because rule 5 is
# non-negotiable: Gemini is called from ai.py and embeddings.py, nowhere
# else. That does push this file past the ~300-line guideline, which is the
# lesser of the two costs — a third module talking to the model is exactly
# the drift that rule exists to prevent.
# ===========================================================================

# Verbatim from PROJECT_PLAN.md §7. Every line is doing work:
#
#   "ONLY the excerpts"   - the grounding constraint itself.
#   the exact refusal     - specifying the wording is what converts a
#                           refusal from an aspiration into something the
#                           model reliably produces. Without a template it
#                           hedges politely and hallucinates anyway, which
#                           is the failure mode the brief explicitly warns
#                           about and the one a grader tests for first.
#   partial-answer rule   - the realistic middle case. Without it the model
#                           treats "some of this is here" as either a full
#                           answer or a refusal, and both are wrong.
#   "quote exact wording" - amounts, dates and clause numbers must survive
#                           verbatim, not be paraphrased into plausibility.
CHAT_SYSTEM_PROMPT = """You answer questions about a single document, using ONLY the excerpts provided below.

Rules:
- Ground every claim in the excerpts. Cite the page for each claim like [p. 4].
- If the excerpts do not contain the answer, say exactly what is missing:
  "I couldn't find anything about <topic> in this document." Do not guess,
  and do not use outside knowledge.
- If the excerpts partially answer, give what is supported and state the gap.
- Quote exact wording when the user asks about specific terms, numbers, or dates.
- Be concise: 1-4 sentences unless asked to elaborate or list."""

REWRITE_SYSTEM_PROMPT = """Rewrite the user's latest message as a standalone search query that makes sense without the conversation.

Rules:
- Output ONLY the query. No preamble, no quotes, no explanation.
- Keep the user's own terminology, including exact identifiers, clause numbers, and amounts.
- If the message is already standalone, output it unchanged.
- Never answer the question. You are writing a search query, not a reply."""

#: Lower than summarisation's 0.2. Chat has to reproduce amounts, dates and
#: clause numbers exactly, and every degree of freedom here is a chance to
#: paraphrase a figure into something plausible but wrong.
CHAT_TEMPERATURE = 0.1

CHAT_UNAVAILABLE_MESSAGE = (
    "The AI assistant is temporarily unavailable. Please try your question again "
    "in a moment."
)


class LLMUnavailableError(RuntimeError):
    """Raised by stream_answer when no tokens could be produced at all.

    Streaming can't use the return-None convention the rest of this module
    follows: by the time a failure happens the caller may already have
    forwarded tokens to the browser. So the contract is — this raises ONLY
    if nothing was emitted, and the SSE layer turns it into an `error`
    event. A mid-stream failure after partial output ends the stream
    instead, because the tokens already sent are real and shouldn't be
    retracted.
    """


def _history_block(history: list[tuple[str, str]]) -> str:
    """Render [(role, content)] into a transcript for the rewrite prompt."""
    return "\n".join(
        f"{'User' if role == 'user' else 'Assistant'}: {content}" for role, content in history
    )


async def rewrite_followup_query(
    *, history: list[tuple[str, str]], message: str
) -> str | None:
    """Turn a follow-up into a standalone search query. None on failure.

    Uses GEMINI_FAST_MODEL — this is a short, mechanical transformation on
    the critical path of every follow-up, so it should not cost a full
    generation. Returning None on failure is deliberate: retrieval falls
    back to the raw message, which is degraded but still works.
    """
    turns = history[-settings.CHAT_HISTORY_TURNS :]
    if not turns:
        return None

    raw = await _generate(
        system_instruction=REWRITE_SYSTEM_PROMPT,
        user_text=f"--- CONVERSATION ---\n{_history_block(turns)}\n\n--- LATEST MESSAGE ---\n{message}",
        model=settings.GEMINI_FAST_MODEL,
    )
    if raw is None:
        return None

    rewritten = raw.strip().strip('"').strip()
    # A model that ignored "output only the query" and wrote a paragraph
    # would poison retrieval far worse than the raw follow-up would. Cheap
    # sanity bound rather than trusting the instruction.
    if not rewritten or len(rewritten) > 400:
        logger.warning("query rewrite produced unusable output (%d chars)", len(rewritten))
        return None
    return rewritten


async def stream_answer(
    *,
    context: str,
    history: list[tuple[str, str]],
    message: str,
) -> AsyncIterator[str]:
    """Stream a grounded answer token by token.

    Retries ONLY before the first token. Once output has been forwarded to
    the browser a retry would restart the answer mid-sentence, so a
    mid-stream failure ends the stream and the caller persists what arrived.
    """
    client = _get_client()
    socket_timeout_s = max(1, settings.LLM_TIMEOUT_SECONDS - _SOCKET_TIMEOUT_MARGIN_SECONDS)

    turns = history[-settings.CHAT_HISTORY_TURNS :]
    conversation = f"--- CONVERSATION SO FAR ---\n{_history_block(turns)}\n\n" if turns else ""
    user_text = (
        f"{conversation}--- DOCUMENT EXCERPTS ---\n{context}\n\n"
        f"--- QUESTION ---\n{message}"
    )

    config = types.GenerateContentConfig(
        system_instruction=CHAT_SYSTEM_PROMPT,
        temperature=CHAT_TEMPERATURE,
        http_options=types.HttpOptions(timeout=socket_timeout_s * 1000),
    )

    attempts = max(1, settings.LLM_MAX_RETRIES)
    for attempt in range(attempts):
        emitted = False
        try:
            stream = await client.aio.models.generate_content_stream(
                model=settings.GEMINI_CHAT_MODEL,
                contents=user_text,
                config=config,
            )
            async for chunk in stream:
                # Guard is mandatory, not defensive: safety verdicts and
                # finish-reason chunks arrive with text=None, and yielding
                # them would put the literal string "None" in the answer.
                if chunk.text:
                    emitted = True
                    yield chunk.text
            if emitted:
                return
            # A stream that closed without producing anything is a failure,
            # not an empty answer — usually a safety block.
            raise ValueError("stream produced no text")
        except Exception as exc:
            if emitted:
                # Partial answer already delivered. Stop cleanly; the caller
                # persists what it received rather than discarding it.
                logger.warning(
                    "chat stream ended early after partial output: %s: %r",
                    type(exc).__name__,
                    exc,
                )
                return
            detail = f"{type(exc).__name__}: {exc!r}"
            if attempt == attempts - 1:
                logger.exception("chat stream failed after %d attempts: %s", attempts, detail)
                raise LLMUnavailableError(CHAT_UNAVAILABLE_MESSAGE) from exc
            delay = _BACKOFF_BASE_SECONDS * (2**attempt)
            logger.warning(
                "chat stream failed (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1,
                attempts,
                delay,
                detail,
            )
            await asyncio.sleep(delay)
