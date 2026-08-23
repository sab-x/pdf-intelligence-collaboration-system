"""Gemini embeddings — PROJECT_PLAN.md §5 steps f-g, §7, §8.

Together with services/ai.py this is the only place that talks to Gemini
(rule 5). Routers and workers call these functions; nothing else constructs
a client.

Same contract as ai.py deliberately: bounded by asyncio.wait_for, retried
with exponential backoff, and returning None rather than raising, so a
failed embedding degrades retrieval instead of unwinding the ingestion task.

## Two details that are easy to get wrong

**Task type must differ between indexing and querying.** gemini-embedding-001
projects text differently for RETRIEVAL_DOCUMENT than for RETRIEVAL_QUERY —
that asymmetry is the point, and embedding a query as a document measurably
degrades recall. embed_chunks and embed_query exist as separate functions so
a caller cannot pick the wrong one by forgetting an argument.

**Dimensionality must match the column, exactly and forever.** The
`vector(768)` columns were created by migrations 0002 and 0005. Changing
EMBED_DIM without a migration produces an insert error; changing it after
data exists silently makes old and new vectors incomparable. Indexing and
querying must use the same value — see the plan's note on Matryoshka
truncation.
"""
import asyncio
import logging
import math

from google import genai
from google.genai import types

from app.core.config import settings

logger = logging.getLogger(__name__)

_BACKOFF_BASE_SECONDS = 1.0
_SOCKET_TIMEOUT_MARGIN_SECONDS = 5

#: Texts per API call. Conservative on purpose: chunks run ~1000 tokens, so
#: 16 keeps a request near 16k tokens, well inside the endpoint's limit, and
#: keeps peak memory small on a 512 MB instance.
EMBED_BATCH_SIZE = 16

#: Batches in flight at once. Enough to hide latency on a 100-chunk document
#: without tripping rate limits on a free API key.
EMBED_CONCURRENCY = 3

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Lazy singleton, mirroring services/ai.py — also the seam the tests
    patch, so no test needs a real API key or network.
    """
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def _normalize(vector: list[float]) -> list[float]:
    """Scale to unit length.

    Google recommends this whenever output_dimensionality is below the
    model's native 3072, which it is here (768). Cosine distance is
    scale-invariant so this doesn't change today's ranking, but it makes
    cosine and inner product equivalent — which means switching pgvector to
    the cheaper `<#>` operator later is a one-line change rather than a
    silent correctness bug.
    """
    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0:
        return vector
    return [component / norm for component in vector]


async def _embed_batch(texts: list[str], *, task_type: str) -> list[list[float]] | None:
    """One embed call, bounded and retried. None if every attempt failed."""
    client = _get_client()
    socket_timeout_s = max(1, settings.LLM_TIMEOUT_SECONDS - _SOCKET_TIMEOUT_MARGIN_SECONDS)

    config = types.EmbedContentConfig(
        task_type=task_type,
        output_dimensionality=settings.EMBED_DIM,
        http_options=types.HttpOptions(timeout=socket_timeout_s * 1000),
    )

    attempts = max(1, settings.LLM_MAX_RETRIES)
    for attempt in range(attempts):
        try:
            response = await asyncio.wait_for(
                client.aio.models.embed_content(
                    model=settings.GEMINI_EMBED_MODEL,
                    contents=texts,
                    config=config,
                ),
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
            embeddings = response.embeddings or []
            # A short response would silently misalign vectors with chunks —
            # chunk 5 would get chunk 6's embedding. Treat it as a failure.
            if len(embeddings) != len(texts):
                raise ValueError(
                    f"expected {len(texts)} embeddings, got {len(embeddings)}"
                )
            vectors: list[list[float]] = []
            for embedding in embeddings:
                values = embedding.values
                if not values:
                    raise ValueError("embedding came back empty")
                vectors.append(_normalize(list(values)))
            return vectors
        except Exception as exc:  # deliberately broad — mirrors ai.py
            # repr(), never str(): TimeoutError stringifies to "" and would
            # render this line with no cause at all.
            detail = f"{type(exc).__name__}: {exc!r}"
            context = (
                f"model={settings.GEMINI_EMBED_MODEL} batch={len(texts)} "
                f"task={task_type} dim={settings.EMBED_DIM} "
                f"timeout={settings.LLM_TIMEOUT_SECONDS}s"
            )
            if attempt == attempts - 1:
                logger.exception(
                    "embedding failed after %d attempts (%s): %s", attempts, context, detail
                )
                return None
            delay = _BACKOFF_BASE_SECONDS * (2**attempt)
            logger.warning(
                "embedding failed (attempt %d/%d), retrying in %.1fs (%s): %s",
                attempt + 1,
                attempts,
                delay,
                context,
                detail,
            )
            await asyncio.sleep(delay)
    return None


async def embed_chunks(texts: list[str]) -> list[list[float] | None]:
    """Embed document chunks for indexing.

    Returns a list the SAME LENGTH as `texts`, positionally aligned, with
    None wherever that text's batch failed. Alignment is the contract the
    caller depends on — writing embeddings back to chunks is a zip, so a
    filtered list would attach the wrong vector to the wrong chunk.

    Partial failure is a normal outcome, not an error: the chunks whose
    batches succeeded are still searchable by vector, and the rest fall back
    to the full-text half of hybrid retrieval.
    """
    if not texts:
        return []

    batches = [
        texts[start : start + EMBED_BATCH_SIZE]
        for start in range(0, len(texts), EMBED_BATCH_SIZE)
    ]
    semaphore = asyncio.Semaphore(EMBED_CONCURRENCY)

    async def run(batch: list[str]) -> list[list[float] | None]:
        async with semaphore:
            vectors = await _embed_batch(batch, task_type="RETRIEVAL_DOCUMENT")
            if vectors is None:
                return [None] * len(batch)
            return list(vectors)

    results = await asyncio.gather(*(run(batch) for batch in batches))

    flattened: list[list[float] | None] = []
    for batch_result in results:
        flattened.extend(batch_result)
    return flattened


async def embed_query(text: str) -> list[float] | None:
    """Embed a search query or a chat question.

    RETRIEVAL_QUERY, not RETRIEVAL_DOCUMENT — see the module docstring.
    """
    if not text.strip():
        return None
    vectors = await _embed_batch([text], task_type="RETRIEVAL_QUERY")
    return vectors[0] if vectors else None
