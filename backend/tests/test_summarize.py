"""Summarisation tests — PROJECT_PLAN.md §6.

The Gemini client is mocked in full: these tests patch app.services.ai's
_get_client() seam, so nothing here needs an API key, a network, or quota.
Both branches of the strategy are covered (direct vs map-reduce), plus the
guarantee the ingestion task depends on — that an unreachable model
degrades instead of raising.
"""
import json

import pytest

from app.core.config import settings
from app.services import ai

pytestmark = pytest.mark.asyncio

DIRECT_RESPONSE = {
    "doc_type": "Employment Agreement",
    "summary": (
        "Acme Corp and Dana Ruiz entered into an employment agreement dated 3 March 2024. "
        "It appoints Ruiz as Head of Platform Engineering at an annual salary of $185,000. "
        "The agreement includes a twelve-month non-solicitation covenant and a 90-day "
        "notice period for termination without cause."
    ),
    "key_points": [
        "Annual salary of $185,000",
        "Start date 1 April 2024",
        "12-month non-solicitation covenant",
        "90-day notice period",
    ],
}


class _FakeResponse:
    def __init__(self, text: str | None) -> None:
        self.text = text


class _FakeModels:
    """Records every generate_content call so a test can assert on how many
    calls were made and what prompts/config they carried.
    """

    def __init__(self, responses: list[object]) -> None:
        self._responses = responses
        self.calls: list[dict[str, object]] = []

    async def generate_content(self, *, model: str, contents: str, config: object):
        self.calls.append({"model": model, "contents": contents, "config": config})
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        result = self._responses[index]
        if isinstance(result, Exception):
            raise result
        return result


class _FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.models = _FakeModels(responses)

    @property
    def aio(self) -> "_FakeClient":
        return self


def _install_client(monkeypatch: pytest.MonkeyPatch, responses: list[object]) -> _FakeClient:
    client = _FakeClient(responses)
    monkeypatch.setattr(ai, "_get_client", lambda: client)
    # Collapse the exponential backoff to zero so the failure test doesn't
    # sit through real sleeps. The retry COUNT is still exercised — only
    # the waiting between attempts is removed.
    monkeypatch.setattr(ai, "_BACKOFF_BASE_SECONDS", 0.0)
    return client


async def test_direct_path_returns_structured_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _install_client(monkeypatch, [_FakeResponse(json.dumps(DIRECT_RESPONSE))])

    result = await ai.summarize_document("offer.pdf", 4, "Short contract text.")

    assert result.degraded is False
    assert result.doc_type == "Employment Agreement"
    assert result.summary == DIRECT_RESPONSE["summary"]
    assert result.key_points == DIRECT_RESPONSE["key_points"]

    # One call only — the whole document fit in context.
    assert len(client.models.calls) == 1
    call = client.models.calls[0]
    assert "FILENAME: offer.pdf" in call["contents"]
    assert "PAGES: 4" in call["contents"]
    # JSON mode, not prose parsing, and the §6 temperature.
    config = call["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is not None
    assert config.temperature == 0.2
    assert config.system_instruction == ai.SUMMARY_SYSTEM_PROMPT


async def test_key_points_are_capped_at_four(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {**DIRECT_RESPONSE, "key_points": [f"point {i}" for i in range(9)]}
    _install_client(monkeypatch, [_FakeResponse(json.dumps(payload))])

    result = await ai.summarize_document("offer.pdf", 4, "Short contract text.")

    assert len(result.key_points) == 4


async def test_map_reduce_path_triggers_above_direct_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Keep the fake document small but push the threshold below it, so the
    # test exercises the branch without building a 400k-char string.
    monkeypatch.setattr(settings, "DIRECT_SUMMARY_CHAR_LIMIT", 1_000)
    monkeypatch.setattr(ai, "MAP_SECTION_CHARS", 500)

    paragraph = ("Section text about Acme Corp and the 2024 fiscal year. " * 10).strip()
    long_text = "\n\n".join([paragraph] * 12)
    assert len(long_text) > settings.DIRECT_SUMMARY_CHAR_LIMIT

    section_bullets = _FakeResponse("- Acme Corp\n- 2024 fiscal year\n- $185,000\n- 90 days")
    final = _FakeResponse(json.dumps(DIRECT_RESPONSE))
    client = _FakeClient([section_bullets] * 20)
    monkeypatch.setattr(ai, "_get_client", lambda: client)

    # The last call is the REDUCE; make it return the structured summary.
    original_generate = client.models.generate_content
    expected_sections = len(ai._split_sections(long_text))

    async def _generate(*, model: str, contents: str, config: object):
        if contents.startswith("FILENAME:"):
            client.models.calls.append({"model": model, "contents": contents, "config": config})
            return final
        return await original_generate(model=model, contents=contents, config=config)

    monkeypatch.setattr(client.models, "generate_content", _generate)

    result = await ai.summarize_document("annual-report.pdf", 120, long_text)

    assert result.degraded is False
    assert result.doc_type == "Employment Agreement"

    # One MAP call per section, plus exactly one REDUCE call.
    assert expected_sections > 1
    assert len(client.models.calls) == expected_sections + 1

    map_calls = [c for c in client.models.calls if not c["contents"].startswith("FILENAME:")]
    assert len(map_calls) == expected_sections
    assert all(c["config"].system_instruction == ai.SECTION_SYSTEM_PROMPT for c in map_calls)
    # MAP calls are plain text; only the REDUCE call uses JSON mode.
    assert all(c["config"].response_mime_type is None for c in map_calls)

    reduce_call = client.models.calls[-1]
    assert reduce_call["config"].system_instruction == ai.SUMMARY_SYSTEM_PROMPT
    # REDUCE runs over the bullets, not the original text.
    assert "- Acme Corp" in reduce_call["contents"]
    assert paragraph not in reduce_call["contents"]


async def test_map_stage_concurrency_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """The semaphore is the whole point of the MAP stage on a free-tier
    quota — assert it actually bounds in-flight calls, not just that it
    exists.
    """
    monkeypatch.setattr(settings, "DIRECT_SUMMARY_CHAR_LIMIT", 1_000)
    monkeypatch.setattr(ai, "MAP_SECTION_CHARS", 500)
    long_text = "\n\n".join([("Acme Corp fiscal detail. " * 20).strip()] * 20)

    in_flight = 0
    peak = 0

    class _CountingModels:
        async def generate_content(self, *, model: str, contents: str, config: object):
            nonlocal in_flight, peak
            if contents.startswith("FILENAME:"):
                return _FakeResponse(json.dumps(DIRECT_RESPONSE))
            in_flight += 1
            peak = max(peak, in_flight)
            try:
                # Yield control so other coroutines can pile up if unbounded.
                await ai.asyncio.sleep(0)
                return _FakeResponse("- bullet one\n- bullet two")
            finally:
                in_flight -= 1

    class _CountingClient:
        def __init__(self) -> None:
            self.models = _CountingModels()

        @property
        def aio(self) -> "_CountingClient":
            return self

    monkeypatch.setattr(ai, "_get_client", _CountingClient)

    await ai.summarize_document("big.pdf", 200, long_text)

    assert peak <= ai.MAP_CONCURRENCY


async def test_gemini_failure_after_all_retries_degrades_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boom = RuntimeError("503 Service Unavailable")
    client = _install_client(monkeypatch, [boom])

    # Must not raise — the ingestion task depends on this.
    result = await ai.summarize_document("offer.pdf", 4, "Short contract text.")

    assert result.degraded is True
    assert result.doc_type == ai.UNAVAILABLE_DOC_TYPE
    assert result.summary == ai.UNAVAILABLE_SUMMARY
    assert result.key_points == []
    # Retried the configured number of times before giving up.
    assert len(client.models.calls) == settings.LLM_MAX_RETRIES


async def test_transient_failure_is_retried_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _install_client(
        monkeypatch,
        [RuntimeError("429 rate limited"), _FakeResponse(json.dumps(DIRECT_RESPONSE))],
    )

    result = await ai.summarize_document("offer.pdf", 4, "Short contract text.")

    assert result.degraded is False
    assert result.doc_type == "Employment Agreement"
    assert len(client.models.calls) == 2


async def test_malformed_json_is_treated_as_a_failed_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-JSON body must degrade, never surface as an empty summary."""
    _install_client(monkeypatch, [_FakeResponse("Sure! Here is your summary:")])

    result = await ai.summarize_document("offer.pdf", 4, "Short contract text.")

    assert result.degraded is True
    assert result.summary == ai.UNAVAILABLE_SUMMARY


async def test_empty_response_text_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    """Safety blocks and MAX_TOKENS finishes both arrive as text=None."""
    client = _install_client(monkeypatch, [_FakeResponse(None)])

    result = await ai.summarize_document("offer.pdf", 4, "Short contract text.")

    assert result.degraded is True
    assert len(client.models.calls) == settings.LLM_MAX_RETRIES
