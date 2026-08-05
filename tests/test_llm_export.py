"""
Tests for dashboard/llm_export.py -- the "Download for AI Chat" Markdown
export, and its base64 embedding into the dashboard HTML.

Field-name correctness matters more here than almost anywhere else in this
codebase: every table column is a hardcoded key guess against a bundle
shape defined in a completely different file (data/fetch_*.py). Several of
these were wrong on the first pass (caught by manually inspecting real
fixture output, not by a failing test) -- the spot-check tests below pin
the real values from a committed fixture specifically to catch that
regressing silently again.
"""

import base64
import re

from dashboard.generate_dashboard import build_dashboard, section_header
from dashboard.llm_export import build_llm_export_markdown


class TestBuildLlmExportMarkdown:
    def test_builds_without_raising_for_every_fixture(self, sample_bundle):
        md = build_llm_export_markdown(sample_bundle)
        assert isinstance(md, str)
        assert len(md) > 0

    def test_includes_instructions_and_grounding_rule(self, sample_bundle):
        md = build_llm_export_markdown(sample_bundle)
        # whitespace-tolerant: the source text is manually line-wrapped for
        # readability, so a phrase can legitimately straddle a newline in
        # the raw string without it being a real bug (Markdown renders a
        # single newline inside a paragraph the same as a space) -- a
        # literal-substring assert already broke once on exactly this.
        normalized = " ".join(md.split())
        assert "Instructions for the AI reading this file" in normalized
        assert "Do NOT use prior knowledge" in normalized
        assert "Fair-value estimate" in normalized
        assert "Bull case" in normalized
        assert "Bear case" in normalized

    def test_includes_ticker_and_all_major_section_headers(self, sample_bundle):
        md = build_llm_export_markdown(sample_bundle)
        ticker = sample_bundle.get("ticker", "")
        assert f"# {ticker} — Research Data Export" in md
        for header in [
            "## Price & Technicals", "## Fundamentals", "## Analyst Ratings & Estimates",
            "## Strategy Backtests", "## Relative Performance", "## Financials",
            "## Ownership & Insider Activity", "## Dividends, Options, Macro & Social Sentiment",
            "## Independent Valuation Signals", "## News", "## Filings", "## Data Quality Notes",
        ]:
            assert header in md, f"missing section header: {header}"

    def test_never_includes_our_own_ai_recommendation(self, sample_bundle):
        """Deliberate design choice: this export is for getting an
        independent second read from a different model, not a summary of
        what ADELE's own pipeline already concluded -- see the module
        docstring. Confirm no recommendation/confidence/fair_value fields
        from a pipeline_result ever leak in (the function doesn't even
        accept one as a parameter, but assert the behavior, not just the
        signature)."""
        md = build_llm_export_markdown(sample_bundle)
        assert "AI Recommendation" not in md
        assert "reasoning_summary" not in md

    def test_empty_bundle_does_not_crash(self):
        md = build_llm_export_markdown({})
        assert "Research Data Export" in md
        assert "No data available" in md or "_No data available._" in md

    def test_dry_run_bundle_uses_raw_news_and_filings_not_digest(self):
        bundle = {
            "ticker": "TEST",
            "news_headlines": [{"date": "2026-01-01", "headline": "Some real headline", "source": "Reuters"}],
            "news_digest": None,
            "filings_raw": {"10-K": {"text": "Full filing text here.", "filing_type": "10-K"}},
            "filings_digest": None,
        }
        md = build_llm_export_markdown(bundle)
        assert "Some real headline" in md
        assert "Full filing text here." in md
        assert "not summarized -- this was a dry run" in md

    def test_full_run_bundle_prefers_digest_over_raw(self):
        bundle = {
            "ticker": "TEST",
            "news_headlines": [{"date": "2026-01-01", "headline": "Raw headline", "source": "Reuters"}],
            "news_digest": "A concise AI-written summary of recent news.",
            "filings_raw": {},
            "filings_digest": "A concise AI-written summary of the latest filing.",
        }
        md = build_llm_export_markdown(bundle)
        assert "A concise AI-written summary of recent news." in md
        assert "A concise AI-written summary of the latest filing." in md


class TestFieldNameCorrectnessAgainstRealFixture:
    """Regression tests for real field-name bugs caught during manual
    review (guessed keys that didn't match the actual data/fetch_*.py
    output shape) -- pins real values from the committed AAPL fixture so
    these can't silently break again."""

    def test_earnings_surprise_uses_real_field_names(self, sample_bundle):
        surprises = (sample_bundle.get("earnings_estimates", {}) or {}).get("earnings_surprise_history", [])
        if not surprises:
            return
        md = build_llm_export_markdown(sample_bundle)
        first = surprises[0]
        # eps_estimate/eps_actual, not the wrong guesses (estimated_eps/actual_eps)
        if first.get("eps_actual") is not None:
            assert f"{first['eps_actual']:,.2f}" in md

    def test_insider_transactions_use_real_field_names(self, sample_bundle):
        txns = (sample_bundle.get("insider_transactions", {}) or {}).get("transactions", [])
        if not txns:
            return
        md = build_llm_export_markdown(sample_bundle)
        owner = txns[0].get("owner")
        if owner:
            assert owner in md

    def test_beneficial_ownership_uses_filings_key_not_filers(self, sample_bundle):
        beneficial = sample_bundle.get("beneficial_ownership", {}) or {}
        filings = beneficial.get("filings", [])
        md = build_llm_export_markdown(sample_bundle)
        if filings:
            person = filings[0].get("reporting_person")
            if person:
                assert person in md
        else:
            # the section must still render (as "no data"), not silently
            # vanish because the code looked for the wrong key ("filers")
            assert "Beneficial ownership" in md

    def test_income_statement_uses_period_end_and_total_revenue(self, sample_bundle):
        quarters = (sample_bundle.get("income_statement", {}) or {}).get("quarterly", [])
        if not quarters:
            return
        md = build_llm_export_markdown(sample_bundle)
        period_end = quarters[0].get("period_end")
        if period_end:
            assert period_end in md


class TestDashboardEmbedding:
    def test_section_header_includes_download_button_with_ticker(self):
        html = section_header({"ticker": "AAPL", "fetched_at": "2026-01-01"})
        assert 'id="llm-export-btn"' in html
        assert 'data-ticker="AAPL"' in html

    def test_build_dashboard_embeds_base64_export_data(self, sample_bundle):
        html = build_dashboard(sample_bundle)
        m = re.search(r'<script type="text/plain" id="llm-export-data">([^<]*)</script>', html)
        assert m, "expected an embedded llm-export-data script tag"
        b64 = m.group(1)
        decoded = base64.b64decode(b64).decode("utf-8")
        assert "Research Data Export" in decoded
        assert "Instructions for the AI reading this file" in decoded

    def test_embedded_export_round_trips_exactly(self, sample_bundle):
        """The embedded base64 must decode to EXACTLY what
        build_llm_export_markdown() itself produces for the same bundle --
        not a re-derived or truncated version. Strips the "Generated by...
        on <timestamp>" line first since that's the one line expected to
        legitimately differ between two separate calls a few microseconds
        apart (dt.datetime.utcnow() at call time, not from the bundle)."""
        strip_timestamp = lambda s: re.sub(r"Generated by ADELE on [^\s(]+", "GENERATED_AT", s)
        html = build_dashboard(sample_bundle)
        m = re.search(r'<script type="text/plain" id="llm-export-data">([^<]*)</script>', html)
        decoded = base64.b64decode(m.group(1)).decode("utf-8")
        assert strip_timestamp(decoded) == strip_timestamp(build_llm_export_markdown(sample_bundle))
