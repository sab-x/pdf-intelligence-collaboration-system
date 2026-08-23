"""Page-aware chunking — PROJECT_PLAN.md §5 step e, §7.

## Why there is no exact token count

Gemini's tokenizer isn't available locally, and `tiktoken` is OpenAI's — it
would produce confidently wrong numbers for this model while adding a
dependency. So sizes here are estimated at CHARS_PER_TOKEN characters per
token, and every "token" figure in this module and in the database is
approximate by construction.

That is a real trade-off, not a shortcut nobody noticed, and it's cheap
because retrieval quality is insensitive to chunk size within ±15%. What it
would NOT be safe for is packing a context window to its exact limit — the
chat prompt in Phase 10 must leave headroom rather than trusting these
numbers.

## Why paragraph-preferred

Splitting mid-sentence produces chunks that retrieve well and read badly:
the model receives a fragment beginning "…and shall terminate on" with no
subject. Paragraph boundaries are the cheapest available proxy for a
semantic unit, so the splitter fills up to the target size and then breaks
at the last paragraph boundary it passed. Only a single paragraph larger
than a whole chunk is split by character count, and that is rare enough to
be worth the ugly edge case.

Pure functions over the `list[str]` that services/pdf.extract_pages already
returns — no PDF, no database, no network — so the page-range and overlap
behaviour is testable directly.
"""
import re
from dataclasses import dataclass

# Rough average across English prose for most tokenizers. See the module
# docstring: this is an estimate and is named as one everywhere it surfaces.
CHARS_PER_TOKEN = 4

#: Chunks shorter than this are dropped. A page break can leave a trailing
#: fragment like "3" or "Confidential" behind; embedding it wastes an API
#: call and pollutes retrieval with a chunk that matches everything weakly.
MIN_CHUNK_CHARS = 80

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class Chunk:
    """One slice, ready to be persisted as a DocumentChunk row."""

    index: int
    content: str
    #: 1-based, inclusive. Equal when the chunk sits within a single page.
    page_start: int
    page_end: int
    token_estimate: int


@dataclass(frozen=True)
class _Unit:
    """A paragraph, tagged with the page it came from."""

    text: str
    page: int

    @property
    def chars(self) -> int:
        # +2 for the "\n\n" that will rejoin it to its neighbour, so the
        # accumulated size matches what actually gets stored.
        return len(self.text) + 2


def estimate_tokens(text: str) -> int:
    """Approximate token count. See the module docstring."""
    return max(1, len(text) // CHARS_PER_TOKEN)


def _split_pages_into_units(pages: list[str]) -> list[_Unit]:
    """Flatten pages into page-tagged paragraphs, in reading order."""
    units: list[_Unit] = []
    for page_number, page_text in enumerate(pages, start=1):
        for raw in _PARAGRAPH_BREAK.split(page_text):
            paragraph = raw.strip()
            if paragraph:
                units.append(_Unit(text=paragraph, page=page_number))
    return units


def _hard_split(unit: _Unit, max_chars: int) -> list[_Unit]:
    """Break a paragraph that is bigger than a whole chunk.

    Splits on whitespace near the boundary rather than mid-word, because a
    chunk ending "…the agreem" embeds badly and reads worse. Falls back to a
    blunt character cut only when there is no whitespace to find, which in
    practice means a base64 blob or a table with no spaces.
    """
    if len(unit.text) <= max_chars:
        return [unit]

    pieces: list[_Unit] = []
    remaining = unit.text
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        cut = window.rfind(" ")
        # Only honour the whitespace break if it isn't pathologically early;
        # otherwise we'd emit a sliver and loop forever on the rest.
        if cut < max_chars // 2:
            cut = max_chars
        pieces.append(_Unit(text=remaining[:cut].strip(), page=unit.page))
        remaining = remaining[cut:].strip()
    if remaining:
        pieces.append(_Unit(text=remaining, page=unit.page))
    return [piece for piece in pieces if piece.text]


def _overlap_tail(content: str, overlap_chars: int, page: int) -> _Unit | None:
    """The trailing ~overlap_chars of a chunk, to seed the next one.

    Overlap exists so a fact straddling a chunk boundary is retrievable from
    either side.

    This works at character level rather than carrying whole paragraphs,
    which was the first thing I tried and which silently produced NO overlap
    at all on real documents: when a single paragraph is large enough to
    fill a chunk on its own — the common case in contracts and papers — there
    is no earlier paragraph to carry, so every chunk came out isolated. A
    character tail always yields overlap regardless of paragraph size.

    The cut is moved to a whitespace boundary so the tail doesn't begin
    mid-word, and it is capped at half the target so the next chunk always
    makes forward progress.
    """
    if overlap_chars <= 0 or not content:
        return None

    tail = content[-overlap_chars:]
    # Advance to the first whitespace so the tail starts at a word boundary,
    # unless that would consume most of it.
    space = tail.find(" ")
    if 0 <= space < len(tail) // 2:
        tail = tail[space + 1 :]

    tail = tail.strip()
    if not tail:
        return None
    # The tail is carried from the END of the previous chunk, so it belongs
    # to that chunk's last page. Tagging it correctly is what lets a chunk
    # that begins with overlap from page 3 report page_start = 3.
    return _Unit(text=tail, page=page)


def chunk_pages(
    pages: list[str],
    *,
    target_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    """Split extracted page text into overlapping, page-tagged chunks.

    `pages` is exactly what services/pdf.extract_pages returns: index i is
    page i + 1, and empty strings are preserved for pages with no selectable
    text (they simply contribute no units).
    """
    target_chars = max(1, target_tokens) * CHARS_PER_TOKEN
    overlap_chars = max(0, overlap_tokens) * CHARS_PER_TOKEN
    # A degenerate config (overlap >= target) would make every chunk a copy
    # of the last one. Clamp rather than trusting the caller.
    overlap_chars = min(overlap_chars, target_chars // 2)

    units: list[_Unit] = []
    for unit in _split_pages_into_units(pages):
        units.extend(_hard_split(unit, target_chars))

    chunks: list[Chunk] = []
    current: list[_Unit] = []
    current_chars = 0
    # Whether `current` holds anything beyond a carried-over overlap tail.
    # Flushing a chunk made only of overlap would emit a duplicate of the
    # previous chunk's ending and make no forward progress, so the flush
    # condition is gated on this rather than on `current` being non-empty.
    has_new_content = False

    def flush() -> None:
        nonlocal current, current_chars, has_new_content
        if not current or not has_new_content:
            return

        content = "\n\n".join(unit.text for unit in current).strip()
        if len(content) >= MIN_CHUNK_CHARS or not chunks:
            # `or not chunks` keeps a very short document from producing
            # nothing at all — one undersized chunk beats zero.
            chunks.append(
                Chunk(
                    index=len(chunks),
                    content=content,
                    page_start=min(unit.page for unit in current),
                    page_end=max(unit.page for unit in current),
                    token_estimate=estimate_tokens(content),
                )
            )

        tail = _overlap_tail(content, overlap_chars, current[-1].page)
        current = [tail] if tail else []
        current_chars = tail.chars if tail else 0
        has_new_content = False

    for unit in units:
        if has_new_content and current_chars + unit.chars > target_chars:
            flush()
        current.append(unit)
        current_chars += unit.chars
        has_new_content = True

    flush()

    return chunks
