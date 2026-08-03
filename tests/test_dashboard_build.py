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

    def test_mobile_margins_are_tightened_not_stacked(self, sample_bundle):
        # Regression: found from a screenshot -- .wrap's page-level gutter
        # and .card's own padding stack on top of each other on mobile
        # (the card padding was never reduced at all), eating ~19% of a
        # 375px screen's width before any content starts. Both must be
        # tightened together, not just the outer one.
        html = build_dashboard(sample_bundle)
        assert ".wrap { padding: 10px 10px; }" in html
        assert ".card { padding: 16px 14px; }" in html

    def test_page_overflow_hidden_safety_net_present(self, sample_bundle):
        # A real bug found on an actual iPhone: the page could be dragged
        # horizontally, revealing clipped content -- a sub-pixel of overflow
        # that headless/desktop layout checks don't see, but iOS Safari
        # still lets you elastically drag. overflow-x: hidden on html/body
        # is the standard safety net; every intentional inner scroll
        # (table-scroll, section-nav, viz-chart) sets its own overflow-x so
        # this doesn't clip anything real.
        html = build_dashboard(sample_bundle)
        assert "overflow-x: hidden" in html

    def test_echarts_registry_and_assets_wired_up(self, sample_bundle):
        # Charts are now rendered client-side by the vendored ECharts
        # runtime, not inline SVG -- responsive sizing/label collision/
        # gauge geometry are ECharts' job now, not hand-tuned CSS tiers.
        # Confirm the registry payload and both vendored <script> tags
        # actually land in the page.
        html = build_dashboard(sample_bundle)
        assert "window.__CHARTS__" in html
        assert '<script src="assets/echarts.min.js"></script>' in html
        assert '<script src="assets/dashboard.js"></script>' in html

    def test_ios_home_screen_meta_tags_present(self, sample_bundle):
        # PWA/"Add to Home Screen" support -- this page (opened via the
        # add-on's direct port, not just Ingress) is one of the two real
        # entry points a user might actually bookmark to a phone home
        # screen, alongside webapp.app's index page.
        html = build_dashboard(sample_bundle)
        assert '<meta name="apple-mobile-web-app-capable" content="yes">' in html
        assert '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">' in html
        assert '<meta name="apple-mobile-web-app-title" content="StockLLM">' in html
        assert '<link rel="apple-touch-icon" href="assets/icon.png">' in html

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
                "fair_value_low": 180.0,
                "fair_value_high": 210.0,
                "fair_value_basis": "Weighed bull/bear estimates against analyst consensus.",
            },
            "bull": {"thesis": "Upside from margin expansion.", "confidence": 70, "fair_value_estimate": 220.0},
            "bear": {"thesis": "Priced for perfection.", "confidence": 65, "fair_value_estimate": 175.0},
            "skeptic": {"unsupported_claims": ["Bull overstates durability"], "data_gaps": [], "overall_data_quality": "high"},
            "skeptic_qwen": {"unsupported_claims": ["Bull overstates durability", "Bear ignores buyback support"], "data_gaps": ["Missing recent insider activity"], "overall_data_quality": "medium"},
            "quant_check": {
                "verified_claims": ["Revenue grew 8% YoY"],
                "flagged_claims": [{"claim": "Margins expanded 500bps", "issue": "Bundle shows ~150bps, not 500bps", "bundle_figures_checked": "income_statement.annual.operating_margin_pct"}],
                "note": None,
            },
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

    def test_fair_value_range_renders(self, mock_pipeline_result):
        bundle = _minimal_bundle()
        bundle["price"] = {"current_price": 195.0}
        html = build_dashboard(bundle, mock_pipeline_result)
        soup = BeautifulSoup(html, "html.parser")
        rec_card = soup.find("div", class_="rec-card")
        assert "Fair value estimate" in rec_card.get_text()
        assert "Weighed bull/bear estimates" in rec_card.get_text()
        # the range_meter chart itself: Low/High labels made it into the
        # registered ECharts option (chart data lives in window.__CHARTS__,
        # not as literal text in the HTML body since charts render client-side)
        assert '"fmt": "Low $180.00"' in html
        assert "$220.00" in html  # bull's fair_value_estimate surfaced in the thesis grid

    def test_fair_value_absent_does_not_crash_or_leak(self, mock_pipeline_result):
        # insufficient_data or a judge response missing these keys entirely
        # (e.g. an older cached run from before this feature) must not crash
        # or leave a stray empty chart.
        del mock_pipeline_result["judge"]["fair_value_low"]
        del mock_pipeline_result["judge"]["fair_value_high"]
        del mock_pipeline_result["bull"]["fair_value_estimate"]
        del mock_pipeline_result["bear"]["fair_value_estimate"]
        bundle = _minimal_bundle()
        html = build_dashboard(bundle, mock_pipeline_result)
        assert "Fair value estimate" not in html
        assert_no_leaked_values(html)

    def test_both_skeptic_reviews_render(self, mock_pipeline_result):
        bundle = _minimal_bundle()
        html = build_dashboard(bundle, mock_pipeline_result)
        assert "Skeptic review (Claude)" in html
        assert "Skeptic review (Qwen, independent second opinion)" in html
        assert "Missing recent insider activity" in html
        assert_no_leaked_values(html)

    def test_skeptic_agreement_highlighted(self, mock_pipeline_result):
        # both skeptics flagged "Bull overstates durability" in the fixture --
        # the dashboard should call out the overlap as a stronger signal.
        bundle = _minimal_bundle()
        html = build_dashboard(bundle, mock_pipeline_result)
        assert "Both independent skeptics flagged the same claim" in html
        assert "Bull overstates durability" in html

    def test_quant_checker_flagged_claims_render(self, mock_pipeline_result):
        bundle = _minimal_bundle()
        html = build_dashboard(bundle, mock_pipeline_result)
        assert "Quant Checker" in html
        assert "Margins expanded 500bps" in html
        assert "income_statement.annual.operating_margin_pct" in html

    def test_quant_checker_all_verified_shows_reassurance_not_warning(self, mock_pipeline_result):
        mock_pipeline_result["quant_check"] = {
            "verified_claims": ["Revenue grew 8% YoY", "P/E is 28.5"], "flagged_claims": [], "note": None,
        }
        bundle = _minimal_bundle()
        html = build_dashboard(bundle, mock_pipeline_result)
        assert "verified 2 numeric claim(s)" in html
        assert "Margins expanded" not in html  # no flagged-claims block leaking through

    def test_skeptic_qwen_and_quant_check_absent_does_not_crash_or_leak(self, mock_pipeline_result):
        del mock_pipeline_result["skeptic_qwen"]
        del mock_pipeline_result["quant_check"]
        bundle = _minimal_bundle()
        html = build_dashboard(bundle, mock_pipeline_result)
        assert "Skeptic review (Qwen" not in html
        # "Quant Checker" itself still appears in the always-present glossary
        # tooltip text -- check for the actual rendered block instead.
        assert "numeric claims that didn't check out" not in html
        assert "verified" not in html or "numeric claim(s)" not in html
        assert_no_leaked_values(html)


class TestOptionalDataSources:
    """FRED (macro), FMP (DCF/PEG), and Finnhub (insider sentiment / rec
    trend) are all optional -- no key means the bundle has these sections
    present but empty (see data/fetch_*.py's own graceful-degradation
    pattern). The dashboard must render correctly both with and without them."""

    def test_renders_fred_macro_fields_when_present(self):
        bundle = _minimal_bundle()
        bundle["macro_context"] = {
            "vix_level": 16.0, "vix_change_20d": 0.5,
            "treasury_10y_yield_pct": 4.5, "treasury_10y_yield_change_20d_pct": 0.1,
            "cpi_yoy_pct": 2.9, "unemployment_rate_pct": 4.1,
            "fed_funds_rate_pct": 4.33, "yield_curve_10y_2y_pct": 0.45, "note": None,
        }
        html = build_dashboard(bundle)
        assert "CPI inflation" in html
        assert "Unemployment rate" in html
        assert "Fed funds rate" in html
        assert "yield curve" in html
        assert_no_leaked_values(html)

    def test_fred_macro_fields_absent_when_no_key(self):
        bundle = _minimal_bundle()
        bundle["macro_context"] = {
            "vix_level": 16.0, "vix_change_20d": 0.5,
            "treasury_10y_yield_pct": 4.5, "treasury_10y_yield_change_20d_pct": 0.1,
            "cpi_yoy_pct": None, "unemployment_rate_pct": None,
            "fed_funds_rate_pct": None, "yield_curve_10y_2y_pct": None, "note": None,
        }
        html = build_dashboard(bundle)
        assert "CPI inflation" not in html
        assert_no_leaked_values(html)

    def test_renders_dcf_and_peg_when_present(self):
        bundle = _minimal_bundle()
        bundle["fmp_valuation"] = {"dcf_value": 245.30, "dcf_stock_price": 230.10, "peg_ratio": 1.85, "note": None}
        html = build_dashboard(bundle)
        assert "DCF fair value" in html
        assert "PEG ratio" in html
        assert_no_leaked_values(html)

    def test_dcf_and_peg_absent_when_no_key(self):
        bundle = _minimal_bundle()
        bundle["fmp_valuation"] = {"dcf_value": None, "dcf_stock_price": None, "peg_ratio": None, "note": None}
        html = build_dashboard(bundle)
        assert "DCF fair value" not in html
        assert_no_leaked_values(html)

    def test_renders_insider_sentiment_and_rec_trend_when_present(self):
        bundle = _minimal_bundle()
        bundle["finnhub_signals"] = {
            "insider_sentiment_mspr": -12.5,
            "insider_sentiment_trend": [],
            "recommendation_trend": [
                {"period": "2026-07-01", "strong_buy": 10, "buy": 15, "hold": 5, "sell": 1, "strong_sell": 0},
            ],
            "note": None,
        }
        html = build_dashboard(bundle)
        assert "Insider sentiment (MSPR)" in html
        assert "Analyst recommendation trend" in html
        assert_no_leaked_values(html)

    def test_finnhub_signals_absent_when_no_key(self):
        bundle = _minimal_bundle()
        bundle["finnhub_signals"] = {
            "insider_sentiment_mspr": None, "insider_sentiment_trend": [],
            "recommendation_trend": [], "note": None,
        }
        html = build_dashboard(bundle)
        assert "Insider sentiment (MSPR)" not in html
        assert "Analyst recommendation trend" not in html
        assert_no_leaked_values(html)

    def test_missing_sections_entirely_do_not_crash(self):
        # A bundle from before this feature existed simply won't have these
        # keys at all -- must not KeyError.
        bundle = _minimal_bundle()
        html = build_dashboard(bundle)
        assert_no_leaked_values(html)


class TestInsiderActivityAtAGlance:
    """The bug this fixes: 'insiders have been buying, a vote of
    confidence' used to fire for ANY transaction that increased an
    insider's holdings, including routine stock grants/awards and option
    exercises -- not just real open-market purchases with their own cash.
    See HANDOFF.md and data/fetch_insider.py's module docstring."""

    def _bundle_with_transactions(self, transactions):
        bundle = _minimal_bundle()
        bundle["insider_transactions"] = {"transactions": transactions, "note": None}
        return bundle

    def test_real_open_market_buying_reads_as_confidence_signal(self):
        txns = [
            {"direction": "buy", "is_open_market": True, "transaction_nature": "open market purchase"},
        ]
        html = build_dashboard(self._bundle_with_transactions(txns))
        assert "Company insiders have been buying" in html
        assert "vote of confidence" in html

    def test_grants_and_awards_do_not_read_as_confidence_signal(self):
        # This is exactly the real-world case found live on MBLY: millions
        # of shares via code "A" grants, no price attached.
        txns = [
            {"direction": "buy", "is_open_market": False, "transaction_nature": "grant or award"},
            {"direction": "buy", "is_open_market": False, "transaction_nature": "grant or award"},
        ]
        html = build_dashboard(self._bundle_with_transactions(txns))
        # "vote of confidence" still appears in the glossary tooltip text
        # (which explains the distinction generically) -- what must NOT
        # appear is the specific claim that these particular grants ARE one.
        assert "Company insiders have been buying" not in html
        assert "No open-market insider buying or selling" in html
        assert "routine compensation" in html

    def test_mix_of_real_buys_and_grants_only_counts_real_buys(self):
        txns = [
            {"direction": "buy", "is_open_market": True, "transaction_nature": "open market purchase"},
            {"direction": "buy", "is_open_market": False, "transaction_nature": "grant or award"},
        ]
        html = build_dashboard(self._bundle_with_transactions(txns))
        assert "1 recent open-market purchase" in html

    def test_insider_table_shows_nature_column(self):
        txns = [{
            "date": "2026-07-10", "owner": "Test CEO", "title": "CEO", "direction": "buy",
            "transaction_code": "A", "transaction_nature": "grant or award", "is_open_market": False,
            "shares": 1000000.0, "price_per_share": None,
        }]
        html = build_dashboard(self._bundle_with_transactions(txns))
        soup = BeautifulSoup(html, "html.parser")
        assert "grant or award" in html
        assert_no_leaked_values(html)


class TestSectionNav:
    """The mobile jump-to-section pill bar (HANDOFF.md: dashboard UX pass) --
    every link's href must resolve to a real section id on the same page,
    or a phone user tapping it lands nowhere."""

    def test_nav_present_with_anchors_for_every_section(self, sample_bundle):
        html = build_dashboard(sample_bundle)
        soup = BeautifulSoup(html, "html.parser")
        nav = soup.find("nav", class_="section-nav")
        assert nav is not None
        hrefs = [a["href"] for a in nav.find_all("a")]
        assert hrefs, "nav has no links"
        for href in hrefs:
            assert href.startswith("#")
            target_id = href[1:]
            assert soup.find(id=target_id) is not None, f"nav links to #{target_id} but no element has that id"

    def test_every_top_level_card_has_matching_nav_link(self, sample_bundle):
        html = build_dashboard(sample_bundle)
        soup = BeautifulSoup(html, "html.parser")
        nav_targets = {a["href"][1:] for a in soup.find("nav", class_="section-nav").find_all("a")}
        expected_ids = {
            "sec-price", "sec-analyst", "sec-relative", "sec-ownership",
            "sec-financials", "sec-extras", "sec-news", "sec-filings",
        }
        assert expected_ids <= nav_targets


class TestHeroBlock:
    """The hero price block (HANDOFF.md: dashboard UX pass) -- the one
    focal point the page should lead with before any scrolling."""

    def test_hero_present_with_price(self, sample_bundle):
        html = build_dashboard(sample_bundle)
        soup = BeautifulSoup(html, "html.parser")
        hero = soup.find("div", class_="hero")
        assert hero is not None
        assert soup.find("span", class_="hero-price") is not None

    def test_no_rec_badge_without_pipeline_result(self, sample_bundle):
        html = build_dashboard(sample_bundle)
        soup = BeautifulSoup(html, "html.parser")
        assert soup.find("span", class_="hero-rec-badge") is None

    def test_rec_badge_present_with_pipeline_result(self):
        bundle = _minimal_bundle()
        bundle["price"] = {"current_price": 195.0, "pct_change_20d": 3.2}
        pipeline_result = {"judge": {"recommendation": "buy", "confidence": 80}}
        html = build_dashboard(bundle, pipeline_result)
        soup = BeautifulSoup(html, "html.parser")
        badge = soup.find("span", class_="hero-rec-badge")
        assert badge is not None
        assert "BUY" in badge.get_text()
        assert "80% confidence" in html

    def test_hero_no_leaked_values(self, sample_bundle):
        html = build_dashboard(sample_bundle)
        assert_no_leaked_values(html)

    def test_missing_price_does_not_crash_or_leak(self):
        # A dry-run or thin bundle may have no price section at all.
        bundle = _minimal_bundle()
        html = build_dashboard(bundle)
        assert_no_leaked_values(html)


class TestMobileSafeTables:
    """data_table() emits a data-label on every <td> so the mobile media
    query can render each row as a stacked card instead of a cramped
    horizontally-scrolling table (HANDOFF.md: dashboard UX pass)."""

    def test_data_tables_carry_data_label_on_every_cell(self, sample_bundle):
        html = build_dashboard(sample_bundle)
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table", class_="data-table")
        assert tables, "no data tables rendered for this fixture"
        checked_any_row = False
        for table in tables:
            headers = [th.get_text() for th in table.find_all("th")]
            for row in table.find("tbody").find_all("tr"):
                cells = row.find_all("td")
                assert len(cells) == len(headers)
                for cell, header in zip(cells, headers):
                    assert cell.get("data-label") == header
                checked_any_row = True
        assert checked_any_row

    def test_mobile_card_list_css_present(self, sample_bundle):
        html = build_dashboard(sample_bundle)
        assert "content: attr(data-label)" in html


def _minimal_bundle():
    """A deliberately thin bundle -- exercises the AI-recommendation path
    without depending on the shape of a specific committed fixture file."""
    return {"ticker": "TEST", "fetched_at": "2026-01-01T00:00:00Z"}
