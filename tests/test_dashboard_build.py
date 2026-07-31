"""
Tests for dashboard/generate_dashboard.py's build_dashboard() -- the
top-level function that assembles a full HTML page from a research bundle.
Runs against every committed output/*.json fixture (via the sample_bundle
fixture) rather than one synthetic bundle, since the real edge cases this
session actually found (MBLY's null P/E, QQQ's mostly-missing sections)
only show up in real data.

This automates exactly the manual BeautifulSoup checks that got re-run by
hand after every change this session (leaked None/nan values, svg/table
counts, mobile CSS presence) -- see HANDOFF.md for the running list of
bugs those checks caught.
"""

import re

import pytest
from bs4 import BeautifulSoup

from dashboard.generate_dashboard import build_dashboard

LEAK_PATTERNS = [r">None<", r"None%", r"\$None", r">nan<", r"nan%", r"\$nan"]


def assert_no_leaked_values(html: str):
    for pattern in LEAK_PATTERNS:
        assert not re.search(pattern, html), f"leaked value matching {pattern!r} in output"


class TestBuildDashboardAgainstEveryFixture:
    """Every check here runs once per committed output/*.json bundle."""

    def test_builds_without_raising(self, sample_bundle):
        build_dashboard(sample_bundle)

    def test_produces_parseable_html(self, sample_bundle):
        html = build_dashboard(sample_bundle)
        soup = BeautifulSoup(html, "html.parser")
        assert soup.find("html") is not None
        assert soup.title is not None

    def test_no_leaked_none_or_nan(self, sample_bundle):
        html = build_dashboard(sample_bundle)
        assert_no_leaked_values(html)

    def test_every_svg_has_explicit_dimensions_or_is_empty_state(self, sample_bundle):
        html = build_dashboard(sample_bundle)
        soup = BeautifulSoup(html, "html.parser")
        for svg in soup.find_all("svg"):
            if not svg.attrs:
                continue  # bare <svg></svg> is the intentional empty-state placeholder
            # NOTE: BeautifulSoup's html.parser backend lowercases attribute
            # names (viewBox -> viewbox) even though the real generated HTML
            # correctly uses camelCase (SVG/XML is case-sensitive there) --
            # check the lowercased key, not a defect in the actual output.
            assert svg.get("viewbox"), f"svg missing viewBox: {svg}"
            assert svg.get("width"), f"svg missing width attribute: {svg}"
            assert svg.get("height"), f"svg missing height attribute: {svg}"

    def test_mobile_responsive_css_present(self, sample_bundle):
        html = build_dashboard(sample_bundle)
        assert "@media (max-width: 700px)" in html
        assert "min-width: 0" in html  # the CSS Grid blowout fix, HANDOFF.md #33

    def test_no_ai_recommendation_section_without_pipeline_result(self, sample_bundle):
        html = build_dashboard(sample_bundle)
        soup = BeautifulSoup(html, "html.parser")
        assert soup.find("div", class_="rec-card") is None

    def test_disclaimer_present(self, sample_bundle):
        html = build_dashboard(sample_bundle)
        assert "NOT financial advice" in html


class TestBuildDashboardWithPipelineResult:
    """AI Recommendation section -- only exercised with a mock pipeline
    result, since a real one requires calling the live Anthropic API."""

    @pytest.fixture
    def mock_pipeline_result(self):
        return {
            "run_id": 42,
            "total_cost_usd": 0.1234,
            "judge": {
                "recommendation": "hold",
                "confidence": 62,
                "reasoning_summary": "Strong fundamentals but stretched valuation.",
                "key_risks": ["Regulatory pressure", "High P/E leaves little room for error"],
                "data_quality_caveat": "Data is fresh and comprehensive.",
            },
            "bull": {"thesis": "Upside from margin expansion.", "confidence": 70},
            "bear": {"thesis": "Priced for perfection.", "confidence": 65},
            "skeptic": {"unsupported_claims": ["Bull overstates durability"], "data_gaps": [], "overall_data_quality": "high"},
        }

    def test_ai_recommendation_section_renders(self, mock_pipeline_result):
        bundle = _minimal_bundle()
        html = build_dashboard(bundle, mock_pipeline_result)
        soup = BeautifulSoup(html, "html.parser")
        rec_card = soup.find("div", class_="rec-card")
        assert rec_card is not None
        assert "HOLD" in rec_card.get_text()

    def test_ai_recommendation_no_leaked_values(self, mock_pipeline_result):
        bundle = _minimal_bundle()
        html = build_dashboard(bundle, mock_pipeline_result)
        assert_no_leaked_values(html)

    @pytest.mark.parametrize("rec,expected_class", [
        ("buy", "rec-good"),
        ("sell", "rec-critical"),
        ("hold", "rec-neutral"),
        ("insufficient_data", "rec-warning"),
    ])
    def test_recommendation_badge_color(self, mock_pipeline_result, rec, expected_class):
        mock_pipeline_result["judge"]["recommendation"] = rec
        bundle = _minimal_bundle()
        html = build_dashboard(bundle, mock_pipeline_result)
        soup = BeautifulSoup(html, "html.parser")
        rec_card = soup.find("div", class_=lambda c: c and "rec-card" in c)
        assert expected_class in rec_card.get("class", [])


def _minimal_bundle():
    """A deliberately thin bundle -- exercises the AI-recommendation path
    without depending on the shape of a specific committed fixture file."""
    return {"ticker": "TEST", "fetched_at": "2026-01-01T00:00:00Z"}
