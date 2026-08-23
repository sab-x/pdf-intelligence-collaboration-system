"""PyMuPDF text extraction — PROJECT_PLAN.md §5 step b.

Deliberately synchronous: PyMuPDF is CPU-bound C code that blocks the event
loop on a single-worker instance. The CALLER is responsible for wrapping it
    await run_in_threadpool(extract_pages, pdf_bytes)
rather than this module hiding a thread hop inside itself — that keeps the
function trivially testable and makes the blocking cost visible at the call
site (see app/workers/ingest.py).
"""
import pymupdf


def extract_pages(pdf_bytes: bytes) -> list[str]:
    """Return the text of every page, in order — index i is page i + 1.

    Pages with no selectable text (scanned images) yield an empty string
    rather than being skipped, so len() stays a truthful page count and the
    caller can spot the scanned-PDF case from the total character count.
    """
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return [page.get_text("text") for page in doc]
