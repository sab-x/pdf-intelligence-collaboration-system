"""Chunking invariants — PROJECT_PLAN.md §5 step e, §7.

Pure unit tests: no database, no network, no PDF. services/chunking operates
on the `list[str]` that extract_pages returns, which is precisely so the
page-range and overlap behaviour can be pinned down without any of that.

The two properties worth defending here both failed in the first
implementation and would have failed silently in production:

  * Overlap actually existing. The original carried whole paragraphs
    forward, so a document whose paragraphs each fill a chunk — contracts,
    papers, most real PDFs — produced no overlap at all. Retrieval still
    worked, so nothing looked broken; facts straddling a boundary were just
    quietly unfindable.

  * Page ranges being truthful. Every [p. N] citation in the chat answer is
    read straight off these fields. Wrong page numbers make a correct answer
    look fabricated, which is worse than no citation.
"""
import pytest

from app.services.chunking import CHARS_PER_TOKEN, chunk_pages, estimate_tokens


def _pages_with_big_paragraphs(page_count: int = 3, per_page: int = 6) -> list[str]:
    """Paragraphs large enough that one nearly fills a chunk — the shape
    that broke whole-paragraph overlap.
    """
    return [
        "\n\n".join(
            f"Page {page} paragraph {index}. " + ("lorem ipsum dolor sit amet " * 20)
            for index in range(per_page)
        )
        for page in range(1, page_count + 1)
    ]


def _pages_with_small_paragraphs(page_count: int = 3, per_page: int = 40) -> list[str]:
    """Short paragraphs, so a chunk spans many of them and often two pages."""
    return [
        "\n\n".join(f"Page {page} line {index}." for index in range(per_page))
        for page in range(1, page_count + 1)
    ]


# ---------------------------------------------------------------------------
# Page ranges
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pages",
    [_pages_with_big_paragraphs(), _pages_with_small_paragraphs()],
    ids=["big-paragraphs", "small-paragraphs"],
)
def test_page_ranges_are_well_formed(pages: list[str]) -> None:
    chunks = chunk_pages(pages, target_tokens=200, overlap_tokens=40)

    assert chunks, "expected at least one chunk"
    for chunk in chunks:
        assert chunk.page_start <= chunk.page_end
        # 1-based and never past the end of the document.
        assert 1 <= chunk.page_start
        assert chunk.page_end <= len(pages)


def test_page_starts_are_non_decreasing() -> None:
    """Chunks come out in reading order.

    Phase 10 assembles retrieved chunks into a prompt and renders citations
    from them; out-of-order page numbers would make an answer cite page 7
    before page 2 for a fact stated once.
    """
    chunks = chunk_pages(_pages_with_small_paragraphs(), target_tokens=200, overlap_tokens=40)

    starts = [chunk.page_start for chunk in chunks]
    assert starts == sorted(starts)


def test_chunk_indices_are_contiguous_from_zero() -> None:
    """uq_document_chunks_document_id_chunk_index depends on this."""
    chunks = chunk_pages(_pages_with_big_paragraphs(), target_tokens=200, overlap_tokens=40)

    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


def test_a_chunk_can_span_two_pages() -> None:
    """Page-awareness has to survive a chunk that crosses a page break —
    otherwise page_end is decorative and always equals page_start.
    """
    chunks = chunk_pages(_pages_with_small_paragraphs(), target_tokens=200, overlap_tokens=40)

    assert any(chunk.page_start != chunk.page_end for chunk in chunks), (
        "no chunk spanned a page boundary; page_end is not being computed from "
        "the units that actually went into the chunk"
    )


def test_empty_pages_are_skipped_but_do_not_shift_numbering() -> None:
    """A page with no selectable text contributes nothing, yet the pages
    after it must keep their real numbers — extract_pages preserves empty
    strings precisely so this stays true.
    """
    pages = ["", "Real content here. " * 40, ""]

    chunks = chunk_pages(pages, target_tokens=200, overlap_tokens=40)

    assert chunks
    assert all(chunk.page_start == 2 and chunk.page_end == 2 for chunk in chunks)


# ---------------------------------------------------------------------------
# Overlap
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pages",
    [_pages_with_big_paragraphs(), _pages_with_small_paragraphs()],
    ids=["big-paragraphs", "small-paragraphs"],
)
def test_consecutive_chunks_overlap(pages: list[str]) -> None:
    """The regression test for the bug described in the module docstring.

    Asserts on the big-paragraph case specifically, because that is the one
    that silently produced zero overlap.
    """
    chunks = chunk_pages(pages, target_tokens=200, overlap_tokens=40)

    assert len(chunks) > 1, "need multiple chunks for overlap to mean anything"
    for earlier, later in zip(chunks, chunks[1:]):
        tail = earlier.content[-60:].strip()
        assert tail[:40] in later.content, (
            f"chunk {later.index} does not begin with the tail of chunk {earlier.index}"
        )


def test_overlap_does_not_prevent_forward_progress() -> None:
    """Each chunk must contain content the previous one didn't.

    A carried overlap that filled the whole next chunk would loop forever,
    or emit duplicates — this pins the property that stops it.
    """
    chunks = chunk_pages(_pages_with_big_paragraphs(), target_tokens=200, overlap_tokens=40)

    for earlier, later in zip(chunks, chunks[1:]):
        assert later.content != earlier.content
        assert not later.content.startswith(earlier.content)


def test_degenerate_overlap_larger_than_target_is_clamped() -> None:
    """A misconfiguration must not hang ingestion.

    overlap >= target would otherwise mean every chunk carries the whole
    previous chunk forward and the loop never advances.
    """
    chunks = chunk_pages(_pages_with_big_paragraphs(), target_tokens=100, overlap_tokens=500)

    assert chunks
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))


# ---------------------------------------------------------------------------
# Sizing and edge cases
# ---------------------------------------------------------------------------


def test_chunks_respect_the_target_size_approximately() -> None:
    """Approximately, not exactly — chunks break at paragraph boundaries, so
    a chunk that would exceed the target flushes early and comes in under.
    The ceiling that matters is the one Phase 10's prompt budget depends on.
    """
    target_tokens = 200
    chunks = chunk_pages(
        _pages_with_small_paragraphs(), target_tokens=target_tokens, overlap_tokens=40
    )

    target_chars = target_tokens * CHARS_PER_TOKEN
    for chunk in chunks:
        # Generous ceiling: overlap is carried on top of the target, so a
        # chunk legitimately runs over. It must not run away.
        assert len(chunk.content) <= target_chars * 2


def test_a_paragraph_larger_than_a_chunk_is_split() -> None:
    """One unbroken blob with no paragraph breaks — a table dump, or a PDF
    that extracted without newlines. It must not become one enormous chunk.
    """
    chunks = chunk_pages(["word " * 5000], target_tokens=200, overlap_tokens=40)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 200 * CHARS_PER_TOKEN * 2 for chunk in chunks)


def test_a_tiny_document_still_produces_one_chunk() -> None:
    """Below MIN_CHUNK_CHARS the fragment filter would drop it; the
    "or not chunks" escape hatch exists so a short document is still
    searchable rather than silently unindexed.
    """
    chunks = chunk_pages(["Hello world."], target_tokens=200, overlap_tokens=40)

    assert len(chunks) == 1
    assert chunks[0].content == "Hello world."
    assert chunks[0].page_start == chunks[0].page_end == 1


def test_a_document_with_no_text_produces_no_chunks() -> None:
    """The scanned-PDF path. ingest() rejects these earlier via
    MIN_EXTRACTED_CHARS, but the chunker must not invent content.
    """
    assert chunk_pages(["", "   ", "\n\n"], target_tokens=200, overlap_tokens=40) == []


def test_token_estimate_is_never_zero() -> None:
    """token_estimate is NOT NULL in the schema and is used for prompt
    budgeting, so a zero would be both a constraint risk and a lie.
    """
    assert estimate_tokens("") >= 1
    assert estimate_tokens("a") >= 1

    chunks = chunk_pages(_pages_with_big_paragraphs(), target_tokens=200, overlap_tokens=40)
    assert all(chunk.token_estimate >= 1 for chunk in chunks)
