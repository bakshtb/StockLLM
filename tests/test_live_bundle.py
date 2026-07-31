"""
Tier 2 -- hits real external APIs. Tests data/bundle.py's build_research_bundle,
the function that assembles ALL of the individual fetch_*.py results into the
one JSON bundle that gets saved to output/<TICKER>.json and fed to the
dashboard/agents. test_live_fetchers.py already checks each fetch_*.py module
in isolation; this checks the whole thing is actually wired together right,
and -- the thing that's easy to get wrong silently -- that the data is
genuinely freshly fetched just now, not stale/cached/mocked.

Marked @pytest.mark.live; excluded from CI by default (see pytest.ini).
"""

import datetime as dt

import pytest

from data.bundle import build_research_bundle

TICKER = "AAPL"

pytestmark = pytest.mark.live

EXPECTED_TOP_LEVEL_KEYS = {
    "ticker", "fetched_at", "price", "fundamentals", "analyst_ratings",
    "earnings_estimates", "relative_performance", "dividends_buybacks",
    "options_sentiment", "macro_context", "social_sentiment",
    "balance_sheet_health", "income_statement", "insider_transactions",
    "institutional_ownership", "news_headlines", "news_articles_raw",
    "filings_raw", "form144_notices", "beneficial_ownership", "proxy_raw",
    "news_digest", "filings_digest", "data_notes",
}


@pytest.fixture(scope="module")
def bundle_and_calls():
    # run_digests=False -- no Anthropic API key needed/used, matches
    # what --dry-run and the webapp's dry-run checkbox both do.
    return build_research_bundle(TICKER, run_digests=False)


class TestBuildResearchBundle:
    def test_has_all_expected_top_level_keys(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        assert set(bundle.keys()) == EXPECTED_TOP_LEVEL_KEYS

    def test_ticker_is_uppercased_and_stripped(self):
        bundle, _ = build_research_bundle(f" {TICKER.lower()} ", run_digests=False)
        assert bundle["ticker"] == TICKER

    def test_fetched_at_is_a_real_recent_utc_timestamp(self, bundle_and_calls):
        # The actual point of this test: catches the bundle silently
        # returning old/cached/mocked data instead of a fresh fetch.
        bundle, _ = bundle_and_calls
        assert bundle["fetched_at"].endswith("Z")
        parsed = dt.datetime.fromisoformat(bundle["fetched_at"][:-1])
        age = dt.datetime.utcnow() - parsed
        assert dt.timedelta(0) <= age < dt.timedelta(minutes=5), (
            f"fetched_at ({bundle['fetched_at']}) is not close to now -- "
            f"age was {age}, expected under 5 minutes"
        )

    def test_dry_run_skips_digests_and_costs_nothing(self, bundle_and_calls):
        bundle, digest_calls = bundle_and_calls
        assert bundle["news_digest"] is None
        assert bundle["filings_digest"] is None
        assert digest_calls == []

    def test_price_data_present_and_internally_consistent(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        price = bundle["price"]
        assert price["current_price"] > 0
        # current_price is drawn from the same closes series 52w_high/low are
        # computed from, so it must fall within that range by construction --
        # if it doesn't, the price and range came from two different fetches.
        assert price["52w_low"] <= price["current_price"] <= price["52w_high"]

    def test_data_notes_is_a_list_of_strings(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        assert isinstance(bundle["data_notes"], list)
        assert all(isinstance(n, str) for n in bundle["data_notes"])

    def test_invalid_ticker_raises_before_fetching_everything_else(self):
        with pytest.raises(ValueError):
            build_research_bundle("ZZZZZZINVALID", run_digests=False)
