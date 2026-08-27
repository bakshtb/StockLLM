"""
Tests for data/fetch_proxy.py's summarize_proxy() -- mirrors
test_fetch_filings_digest.py's coverage of summarize_filing(), the sibling
function this one was modeled on. Never hits a real API -- call_qwen_digest
is mocked throughout.
"""

from data.fetch_proxy import summarize_proxy
from config import MODEL_FILINGS_DIGEST


def _fake_qwen_digest(parsed=None, cost_usd=0.01):
    def _fake(model, system_prompt, user_text):
        return {
            "parsed": parsed or {"key_points": ["CEO pay rose 12% YoY"]},
            "input_tokens": 1000, "output_tokens": 100,
            "cost_usd": cost_usd, "model": model,
        }
    return _fake


class TestSummarizeProxy:
    def test_reads_digest_text_not_text(self, monkeypatch):
        captured = {}

        def fake_call(model, system_prompt, user_text):
            captured["user_text"] = user_text
            captured["model"] = model
            return {"parsed": {"key_points": []}, "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.001, "model": model}

        monkeypatch.setattr("data.fetch_proxy.call_qwen_digest", fake_call)

        proxy_raw = {"filing_date": "2026-01-08", "text": "SMALL_WINDOW", "digest_text": "BIG_WINDOW_CONTENT", "note": None}
        summarize_proxy(proxy_raw)

        assert "BIG_WINDOW_CONTENT" in captured["user_text"]
        assert "SMALL_WINDOW" not in captured["user_text"]

    def test_uses_the_filings_digest_model(self, monkeypatch):
        # Reuses MODEL_FILINGS_DIGEST rather than a separate constant --
        # same reasoning task (Qwen, large-window financial/legal text
        # summarization), just a different filing type.
        monkeypatch.setattr("data.fetch_proxy.call_qwen_digest", _fake_qwen_digest())
        proxy_raw = {"filing_date": "2026-01-08", "text": "x", "digest_text": "y", "note": None}
        result = summarize_proxy(proxy_raw)
        assert result["model"] == MODEL_FILINGS_DIGEST

    def test_no_digest_text_returns_note_not_error(self):
        proxy_raw = {"filing_date": None, "text": None, "digest_text": None, "note": "No recent DEF 14A proxy statement found."}
        result = summarize_proxy(proxy_raw)
        assert result["digest"] is None
        assert result["cost_usd"] == 0.0
        assert "No recent DEF 14A" in result["note"]

    def test_qwen_failure_returns_note_not_raise(self, monkeypatch):
        def _raise(model, system_prompt, user_text):
            raise RuntimeError("Qwen call failed after retry: timeout")

        monkeypatch.setattr("data.fetch_proxy.call_qwen_digest", _raise)
        proxy_raw = {"filing_date": "2026-01-08", "text": "x", "digest_text": "y", "note": None}
        result = summarize_proxy(proxy_raw)
        assert result["digest"] is None
        assert result["cost_usd"] == 0.0
        assert "Proxy digest failed" in result["note"]
