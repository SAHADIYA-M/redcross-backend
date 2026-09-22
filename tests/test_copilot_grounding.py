"""Batch 3: Copilot answer grounding.

Every statement in the Copilot answer must be backed by retrieved field
reports:
- zero citations  -> answer says no evidence was found (never a fabricated
  facility/location/need);
- Gemini is unavailable -> a deterministic fallback repeats ONLY what the
  retrieved citations actually hold;
- a missing location name is reported as "unknown location", never replaced
  with an invented place name.
"""

import sys
import types

import pytest

from app.services.copilot_service import NO_EVIDENCE_ANSWER, CopilotService


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.last_sql = None

    def execute(self, sql, params):
        self.last_sql = (sql, params)

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConnection:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_fake_database(monkeypatch, rows):
    psycopg = types.ModuleType("psycopg")
    psycopg.connect = lambda database_url, prepare_threshold=None: (
        _FakeConnection(rows)
    )
    pgvector = types.ModuleType("pgvector")
    pgvector_psycopg = types.ModuleType("pgvector.psycopg")
    pgvector_psycopg.register_vector = lambda conn: None
    pgvector.psycopg = pgvector_psycopg
    monkeypatch.setitem(sys.modules, "psycopg", psycopg)
    monkeypatch.setitem(sys.modules, "pgvector", pgvector)
    monkeypatch.setitem(sys.modules, "pgvector.psycopg", pgvector_psycopg)


def _install_embedding(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    import database.scripts.embedding_utils as embedding_utils

    monkeypatch.setattr(embedding_utils, "embed_text", lambda text: [0.1, 0.2])


def _row(report_id, content, location_name, similarity):
    return (report_id, content, location_name, similarity)


def _service(monkeypatch, rows, api_key=None):
    _install_fake_database(monkeypatch, rows)
    _install_embedding(monkeypatch)
    return CopilotService(database_url="postgresql://fake", api_key=api_key)


def test_zero_citations_returns_no_evidence_answer(monkeypatch) -> None:
    service = _service(monkeypatch, rows=[])
    result = service.answer_query("water needs")
    assert result["answer"] == NO_EVIDENCE_ANSWER
    assert result["citations"] == []


def test_zero_citations_skips_gemini(monkeypatch) -> None:
    import google.genai as genai

    class BoomClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("Gemini must not be called with no evidence")

    monkeypatch.setattr(genai, "Client", BoomClient)
    service = _service(monkeypatch, rows=[], api_key="fake-key")
    result = service.answer_query("water needs")
    assert result["answer"] == NO_EVIDENCE_ANSWER


def test_missing_location_is_unknown_not_fabricated(monkeypatch) -> None:
    rows = [
        _row("rp_001", "wells are flooded", None, 0.96),
        _row("rp_002", "families need drinking water", "Kozhikode", 0.88),
    ]
    service = _service(monkeypatch, rows=rows, api_key=None)
    result = service.answer_query("water needs")
    assert result["citations"][0]["location_name"] is None
    assert "Govt UP School" not in result["answer"]
    assert "unknown location" in result["answer"]
    assert "rp_001" in result["answer"]
    assert "Kozhikode" in result["answer"]


def test_gemini_failure_falls_back_to_grounded_answer(monkeypatch) -> None:
    import google.genai as genai

    rows = [_row("rp_009", "shelter materials requested", "Wayanad", 0.9)]

    class FailingGenAI:
        def __init__(self, *_args, **_kwargs):
            pass

        def models(self):
            raise RuntimeError("gemini down")

    monkeypatch.setattr(genai, "Client", FailingGenAI)
    service = _service(monkeypatch, rows=rows, api_key="fake-key")
    result = service.answer_query("shelter")
    assert "rp_009" in result["answer"]
    assert "Wayanad" in result["answer"]
    assert len(result["citations"]) == 1


def test_fallback_uses_only_retrieved_content(monkeypatch) -> None:
    rows = [
        _row("rp_031", "clean water tanks delivered", "Kannur", 0.97),
        _row("rp_032", "health camp scheduled", "Kasargod", 0.91),
    ]
    service = _service(monkeypatch, rows=rows, api_key=None)
    result = service.answer_query("what is happening?")
    answer = result["answer"].lower()
    assert "rp_031" in answer and "rp_032" in answer
    assert "kannur" in answer and "kasargod" in answer
    for token in ("school", "hospital", "flooded"):
        assert token not in answer