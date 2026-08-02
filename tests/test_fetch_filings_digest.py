"""
Tests for data/fetch_filings.py's summarize_filing() -- the one LLM-calling
function in that module, now running on Qwen with a larger character budget
than what lands in the shared bundle (see config.MAX_FILING_CHARS_FOR_DIGEST
vs MAX_FILING_CHARS, and data/bundle.py's stripping of digest_text before
the bundle is assembled). Never hits a real API -- call_qwen_digest is
mocked throughout.
"""

import pytest

from data.fetch_filings import summarize_filing
from config import MODEL_FILINGS_DIGEST


def _fake_qwen_digest(parsed=None, cost_usd=0.01):
    def _fake(model, system_prompt, user_text):
        return {
            "parsed": parsed or {"key_points": ["Revenue grew 8% YoY"]},
            "input_tokens": 1000, "output_tokens": 100,
            "cost_usd": cost_usd, "model": model,
        }
    return _fake


class TestSummarizeFiling:
    def test_reads_digest_text_not_text(self, monkeypatch):
        captured = {}

        def fake_call(model, system_prompt, user_text):
            captured["user_text"] = user_text
            captured["model"] = model
            return {"parsed": {"key_points": []}, "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.001, "model": model}

        monkeypatch.setattr("data.fetch_filings.call_qwen_digest", fake_call)

        filings_raw = {
            "10-K": {"filing_type": "10-K", "filing_date": "2025-10-31", "text": "SMALL_WINDOW", "digest_text": "BIG_WINDOW_CONTENT", "note": None},
        }
        summarize_filing(filings_raw)

        assert "BIG_WINDOW_CONTENT" in captured["user_text"]
        assert "SMALL_WINDOW" not in captured["user_text"]

    def test_uses_the_filings_digest_model(self, monkeypatch):
        monkeypatch.setattr("data.fetch_filings.call_qwen_digest", _fake_qwen_digest())
        filings_raw = {"10-K": {"filing_type": "10-K", "filing_date": "2025-10-31", "text": "x", "digest_text": "y", "note": None}}
        result = summarize_filing(filings_raw)
        assert result["model"] == MODEL_FILINGS_DIGEST

    def test_combines_multiple_filings_into_one_call(self, monkeypatch):
        captured = {}

        def fake_call(model, system_prompt, user_text):
            captured["user_text"] = user_text
            return {"parsed": {"key_points": []}, "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.001, "model": model}

        monkeypatch.setattr("data.fetch_filings.call_qwen_digest", fake_call)

        filings_raw = {
            "10-K": {"filing_type": "10-K", "filing_date": "2025-10-31", "text": "x", "digest_text": "ANNUAL_CONTENT", "note": None},
            "10-Q": {"filing_type": "10-Q", "filing_date": "2026-07-31", "text": "x", "digest_text": "QUARTERLY_CONTENT", "note": None},
        }
        summarize_filing(filings_raw)

        assert "ANNUAL_CONTENT" in captured["user_text"]
        assert "QUARTERLY_CONTENT" in captured["user_text"]

    def test_skips_filings_with_no_digest_text(self, monkeypatch):
        captured = {}

        def fake_call(model, system_prompt, user_text):
            captured["user_text"] = user_text
            return {"parsed": {"key_points": []}, "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.001, "model": model}

        monkeypatch.setattr("data.fetch_filings.call_qwen_digest", fake_call)

        filings_raw = {
            "10-K": {"filing_type": "10-K", "filing_date": "2025-10-31", "text": "x", "digest_text": "ANNUAL_CONTENT", "note": None},
            "8-K": {"filing_type": "8-K", "filing_date": None, "text": None, "digest_text": None, "note": "No recent 8-K filing found."},
        }
        summarize_filing(filings_raw)

        assert "ANNUAL_CONTENT" in captured["user_text"]
        assert "8-K" not in captured["user_text"]

    def test_no_filings_available_returns_notes_not_error(self):
        filings_raw = {
            "10-K": {"filing_type": "10-K", "filing_date": None, "text": None, "digest_text": None, "note": "No recent 10-K filing found."},
            "10-Q": {"filing_type": "10-Q", "filing_date": None, "text": None, "digest_text": None, "note": "No recent 10-Q filing found."},
            "8-K": {"filing_type": "8-K", "filing_date": None, "text": None, "digest_text": None, "note": "No recent 8-K filing found."},
        }
        result = summarize_filing(filings_raw)
        assert result["digest"] is None
        assert result["cost_usd"] == 0.0
        assert "No recent" in result["note"]

    def test_qwen_failure_returns_note_not_raise(self, monkeypatch):
        def _raise(model, system_prompt, user_text):
            raise RuntimeError("Qwen call failed after retry: timeout")

        monkeypatch.setattr("data.fetch_filings.call_qwen_digest", _raise)
        filings_raw = {"10-K": {"filing_type": "10-K", "filing_date": "2025-10-31", "text": "x", "digest_text": "y", "note": None}}
        result = summarize_filing(filings_raw)
        assert result["digest"] is None
        assert result["cost_usd"] == 0.0
        assert "Filings digest failed" in result["note"]
