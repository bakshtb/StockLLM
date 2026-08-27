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
import re

import pytest

from data.bundle import build_research_bundle

TICKER = "AAPL"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_num_or_none(v):
    return v is None or isinstance(v, (int, float))


def is_str_or_none(v):
    return v is None or isinstance(v, str)

pytestmark = pytest.mark.live

EXPECTED_TOP_LEVEL_KEYS = {
    "ticker", "fetched_at", "price", "fundamentals", "analyst_ratings",
    "earnings_estimates", "relative_performance", "dividends_buybacks",
    "options_sentiment", "macro_context", "social_sentiment",
    "balance_sheet_health", "income_statement", "insider_transactions",
    "institutional_ownership", "news_headlines", "news_articles_raw",
    "filings_raw", "form144_notices", "beneficial_ownership", "proxy_raw",
    "fmp_valuation", "finnhub_signals", "backtests",
    "news_digest", "filings_digest", "proxy_digest", "data_notes",
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
        assert bundle["proxy_digest"] is None
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


# ---------------------------------------------------------------------------
# Deep field-by-field validation of every section, against one real AAPL
# bundle (the module-scoped bundle_and_calls fixture above -- one live fetch,
# reused by every class below rather than re-fetching per section).
# ---------------------------------------------------------------------------

class TestPriceFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        p = bundle["price"]
        assert isinstance(p["current_price"], float) and p["current_price"] > 0
        for key in ("ma20", "ma50", "ma200"):
            assert is_num_or_none(p[key])
            if p[key] is not None:
                assert p[key] > 0
        assert p["52w_high"] >= p["52w_low"] > 0
        assert is_num_or_none(p["volatility_20d"])
        if p["volatility_20d"] is not None:
            assert p["volatility_20d"] >= 0
        assert p["volume_trend"] in {"increasing", "decreasing", "stable"}
        assert is_num_or_none(p["pct_change_20d"])
        assert is_num_or_none(p["pct_change_1y"])
        assert p["rsi_14"] is None or 0 <= p["rsi_14"] <= 100
        # MACD's three components are computed together (_compute_macd) --
        # either all three are present or all three are None, never a mix.
        macd_fields = (p["macd"], p["macd_signal"], p["macd_histogram"])
        assert all(v is None for v in macd_fields) or all(isinstance(v, float) for v in macd_fields)


class TestFundamentalsFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        f = bundle["fundamentals"]
        assert is_num_or_none(f["pe_ratio"])
        assert is_num_or_none(f["forward_pe"])
        assert is_str_or_none(f["market_cap"])
        assert is_str_or_none(f["sector"])
        assert is_str_or_none(f["industry"])
        assert is_str_or_none(f["next_earnings_date"])
        assert is_str_or_none(f["analyst_recommendation"])
        for key in ("target_mean_price", "target_median_price", "target_high_price", "target_low_price"):
            assert is_num_or_none(f[key])
        if f["target_low_price"] and f["target_high_price"]:
            assert f["target_low_price"] <= f["target_high_price"]
        assert f["number_of_analyst_opinions"] is None or f["number_of_analyst_opinions"] >= 0

        si = f["short_interest"]
        assert is_num_or_none(si["shares_short"])
        assert is_num_or_none(si["shares_short_prior_month"])
        assert is_num_or_none(si["short_change_pct"])
        assert is_num_or_none(si["short_ratio_days_to_cover"])
        assert is_num_or_none(si["short_pct_of_float"])
        assert is_str_or_none(si["as_of_date"])
        if si["as_of_date"] is not None:
            assert DATE_RE.match(si["as_of_date"])

    def test_aapl_has_a_sector_and_pe(self, bundle_and_calls):
        # A large, heavily covered stock like AAPL should never come back
        # with these core fields empty -- if it does, the yfinance `info`
        # payload shape likely changed underneath us.
        bundle, _ = bundle_and_calls
        f = bundle["fundamentals"]
        assert f["sector"]
        assert f["pe_ratio"] is not None and f["pe_ratio"] > 0


class TestAnalystRatingsFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        ar = bundle["analyst_ratings"]
        assert ar["lookback_days"] == 60
        assert is_str_or_none(ar["note"])
        for action in ar["actions"]:
            assert DATE_RE.match(action["date"])
            assert is_str_or_none(action["firm"])
            assert isinstance(action["action"], str)
            assert is_str_or_none(action["from_grade"])
            assert is_str_or_none(action["to_grade"])
            assert is_str_or_none(action["price_target_action"])
            assert is_num_or_none(action["current_price_target"])
            assert is_num_or_none(action["prior_price_target"])

    def test_actions_sorted_most_recent_first(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        dates = [a["date"] for a in bundle["analyst_ratings"]["actions"]]
        assert dates == sorted(dates, reverse=True)


class TestEarningsEstimatesFields:
    def test_earnings_surprise_history(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        for row in bundle["earnings_estimates"]["earnings_surprise_history"]:
            assert DATE_RE.match(row["quarter_end"])
            assert is_num_or_none(row["eps_actual"])
            assert is_num_or_none(row["eps_estimate"])
            assert is_num_or_none(row["surprise_pct"])

    def test_eps_estimate_trend_and_revisions_keys(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        ee = bundle["earnings_estimates"]
        allowed_periods = {"current_quarter", "next_quarter", "current_year", "next_year"}
        assert set(ee["eps_estimate_trend"].keys()) <= allowed_periods
        assert set(ee["eps_estimate_revisions"].keys()) <= allowed_periods
        assert set(ee["revenue_estimate"].keys()) <= allowed_periods
        for period_vals in ee["revenue_estimate"].values():
            assert set(period_vals.keys()) == {"avg", "low", "high", "num_analysts", "year_ago_revenue", "growth_pct"}


class TestRelativePerformanceFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        rp = bundle["relative_performance"]
        assert rp["benchmark"] == "SPY"
        assert is_str_or_none(rp["sector_etf"])
        # SPY is one of the most liquid tickers on earth -- its own return
        # data should never fail to fetch.
        assert isinstance(rp["benchmark_pct_change_20d"], float)
        assert isinstance(rp["benchmark_pct_change_1y"], float)
        assert isinstance(rp["relative_vs_benchmark_20d_pct"], float)
        assert isinstance(rp["relative_vs_benchmark_1y_pct"], float)
        assert is_num_or_none(rp["stock_pe_ratio"])
        assert is_num_or_none(rp["benchmark_pe_ratio"])
        assert is_num_or_none(rp["pe_premium_vs_benchmark_pct"])
        assert is_str_or_none(rp["note"])


class TestDividendsBuybacksFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        db = bundle["dividends_buybacks"]
        # AAPL pays a real, small dividend -- a null yield here means the
        # yfinance `info` payload shape silently changed (see the module's
        # own docstring note on the yield-vs-payout-ratio unit quirk).
        assert db["dividend_yield_pct"] is not None
        assert 0 < db["dividend_yield_pct"] < 10
        assert is_num_or_none(db["payout_ratio_pct"])
        assert is_num_or_none(db["five_year_avg_dividend_yield_pct"])
        for entry in db["recent_dividend_history"]:
            assert DATE_RE.match(entry["date"])
            assert entry["amount"] > 0
        for entry in db["buybacks_recent_quarters"]:
            assert DATE_RE.match(entry["quarter_end"])
            assert entry["buyback_usd"] >= 0


class TestOptionsSentimentFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        os_ = bundle["options_sentiment"]
        # AAPL always has listed options -- this should be the happy path,
        # not the "no options found" fallback.
        assert os_["expiration_used"] is not None
        assert DATE_RE.match(os_["expiration_used"])
        assert isinstance(os_["days_to_expiry"], int) and os_["days_to_expiry"] >= 0
        for key in ("put_call_volume_ratio", "put_call_open_interest_ratio",
                    "atm_call_iv", "atm_put_iv", "otm_put_iv", "otm_call_iv", "iv_skew_put_minus_call"):
            assert is_num_or_none(os_[key])
            if os_[key] is not None and "ratio" in key:
                assert os_[key] >= 0


class TestMacroContextFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        mc = bundle["macro_context"]
        # ^VIX and ^TNX are core indices -- should always resolve.
        assert mc["vix_level"] is not None and mc["vix_level"] > 0
        assert mc["treasury_10y_yield_pct"] is not None and 0 < mc["treasury_10y_yield_pct"] < 20
        assert is_num_or_none(mc["vix_change_20d"])
        assert is_num_or_none(mc["treasury_10y_yield_change_20d_pct"])
        # FRED fields are optional (FRED_API_KEY) -- present either way, null if no key.
        assert is_num_or_none(mc["cpi_yoy_pct"])
        assert is_num_or_none(mc["unemployment_rate_pct"])
        assert is_num_or_none(mc["fed_funds_rate_pct"])
        assert is_num_or_none(mc["yield_curve_10y_2y_pct"])


class TestFmpValuationFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        fmp = bundle["fmp_valuation"]
        assert is_num_or_none(fmp["dcf_value"])
        assert is_num_or_none(fmp["peg_ratio"])
        assert is_str_or_none(fmp["note"])


class TestFinnhubSignalsFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        fh = bundle["finnhub_signals"]
        assert is_num_or_none(fh["insider_sentiment_mspr"])
        assert isinstance(fh["insider_sentiment_trend"], list)
        assert isinstance(fh["recommendation_trend"], list)
        for row in fh["recommendation_trend"]:
            assert set(row.keys()) == {"period", "strong_buy", "buy", "hold", "sell", "strong_sell"}


class TestSocialSentimentFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        ss = bundle["social_sentiment"]
        assert ss["message_count"] >= 0
        assert ss["bullish_count"] >= 0 and ss["bearish_count"] >= 0 and ss["untagged_count"] >= 0
        assert ss["bullish_count"] + ss["bearish_count"] + ss["untagged_count"] == ss["message_count"]
        if ss["bullish_pct_of_tagged"] is not None:
            assert 0 <= ss["bullish_pct_of_tagged"] <= 100
        assert len(ss["sample_messages_unverified"]) <= 5
        for msg in ss["sample_messages_unverified"]:
            assert set(msg.keys()) == {"created_at", "body", "sentiment"}


class TestBalanceSheetHealthFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        bs = bundle["balance_sheet_health"]
        for key in ("total_debt", "total_cash", "debt_to_equity", "current_ratio",
                    "free_cash_flow", "operating_cash_flow"):
            assert is_num_or_none(bs[key])
        assert isinstance(bs["note"], str)


class TestIncomeStatementFields:
    def _assert_period_stats(self, period):
        assert DATE_RE.match(period["period_end"])
        for key in ("total_revenue", "gross_profit", "operating_income", "net_income", "diluted_eps"):
            assert is_num_or_none(period[key])
        for key in ("gross_margin_pct", "operating_margin_pct", "net_margin_pct"):
            assert is_num_or_none(period[key])

    def test_annual_present_for_aapl(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        annual = bundle["income_statement"]["annual"]
        assert annual is not None
        self._assert_period_stats(annual)
        assert annual["total_revenue"] > 0
        # yoy growth fields should be present -- multi-year history always
        # available for AAPL.
        assert is_num_or_none(annual["revenue_growth_yoy_pct"])
        assert is_num_or_none(annual["net_income_growth_yoy_pct"])
        assert is_num_or_none(annual["eps_growth_yoy_pct"])

    def test_quarterly_present_for_aapl(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        quarterly = bundle["income_statement"]["quarterly"]
        assert quarterly is not None and len(quarterly) > 0
        for q in quarterly:
            self._assert_period_stats(q)
        # most recent first
        period_ends = [q["period_end"] for q in quarterly]
        assert period_ends == sorted(period_ends, reverse=True)


class TestInsiderTransactionsFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        for txn in bundle["insider_transactions"]["transactions"]:
            assert isinstance(txn["owner"], str) and txn["owner"]
            assert isinstance(txn["title"], str)
            assert is_str_or_none(txn["date"])
            assert txn["direction"] in {"buy", "sell", "unknown"}
            assert is_num_or_none(txn["shares"])
            assert is_num_or_none(txn["price_per_share"])
            assert is_str_or_none(txn["transaction_code"])
            assert isinstance(txn["transaction_nature"], str)
            assert isinstance(txn["is_open_market"], bool)
            # A real open-market purchase always has a price attached --
            # this is the same "no price = not a real cash purchase" check
            # a human reading the dashboard should make.
            if txn["is_open_market"] and txn["direction"] == "buy":
                assert txn["price_per_share"] is not None


class TestInstitutionalOwnershipFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        io = bundle["institutional_ownership"]
        assert len(io["top_institutional_holders"]) <= 5
        for holder in io["top_institutional_holders"]:
            assert is_str_or_none(holder["holder"])
            assert holder["shares"] is None or (isinstance(holder["shares"], int) and holder["shares"] >= 0)
            assert is_num_or_none(holder["pct_out"])
        if io["pct_held_by_institutions"] is not None:
            assert 0 <= io["pct_held_by_institutions"] <= 1
        if io["pct_held_by_insiders"] is not None:
            assert 0 <= io["pct_held_by_insiders"] <= 1

    def test_aapl_has_institutional_holders(self, bundle_and_calls):
        # AAPL is one of the most institutionally-held stocks in the world.
        bundle, _ = bundle_and_calls
        assert len(bundle["institutional_ownership"]["top_institutional_holders"]) > 0


class TestNewsHeadlinesFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        for item in bundle["news_headlines"]:
            assert isinstance(item["headline"], str) and item["headline"]
            assert isinstance(item["source"], str) and item["source"]
            assert item["date"] == "" or DATE_RE.match(item["date"])
            assert isinstance(item["snippet"], str) and len(item["snippet"]) <= 200
            assert is_str_or_none(item["url"])

    def test_deduplicated_by_headline(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        headlines = [item["headline"].strip().lower() for item in bundle["news_headlines"]]
        assert len(headlines) == len(set(headlines))

    def test_aapl_has_recent_news(self, bundle_and_calls):
        # A stock this large always has news in the last couple of weeks.
        bundle, _ = bundle_and_calls
        assert len(bundle["news_headlines"]) > 0


class TestNewsArticlesRawFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        for item in bundle["news_articles_raw"]:
            assert set(item.keys()) == {"headline", "source", "date", "text", "full_text_fetched"}
            assert isinstance(item["text"], str)
            assert isinstance(item["full_text_fetched"], bool)


class TestFilingsRawFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        filings = bundle["filings_raw"]
        assert set(filings.keys()) == {"10-K", "10-Q", "8-K"}
        for filing_type, filing in filings.items():
            assert filing["filing_type"] == filing_type
            assert is_str_or_none(filing["filing_date"])
            if filing["filing_date"] is not None:
                assert DATE_RE.match(filing["filing_date"])
            assert is_str_or_none(filing["text"])
            if filing["text"] is not None:
                assert len(filing["text"]) >= 200
            assert is_str_or_none(filing["note"])

    def test_aapl_has_a_recent_10k_and_10q(self, bundle_and_calls):
        # AAPL always has a recent annual + quarterly filing on EDGAR.
        bundle, _ = bundle_and_calls
        filings = bundle["filings_raw"]
        assert filings["10-K"]["text"] is not None
        assert filings["10-Q"]["text"] is not None

    def test_digest_text_never_lands_in_the_bundle(self, bundle_and_calls):
        # digest_text (the larger window meant only for the filings digest
        # LLM call) must never leak into the shared bundle every reasoning
        # agent sees -- only the smaller `text` window belongs there.
        bundle, _ = bundle_and_calls
        for filing in bundle["filings_raw"].values():
            assert "digest_text" not in filing


class TestForm144NoticesFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        for notice in bundle["form144_notices"]["notices"]:
            assert isinstance(notice["seller"], str) and notice["seller"]
            assert isinstance(notice["relationship"], str)
            assert is_num_or_none(notice["shares_proposed_to_sell"])
            assert is_num_or_none(notice["aggregate_market_value_usd"])
            assert is_str_or_none(notice["approx_sale_date"])


class TestBeneficialOwnershipFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        for filing in bundle["beneficial_ownership"]["filings"]:
            assert isinstance(filing["reporting_person"], str) and filing["reporting_person"]
            assert is_num_or_none(filing["shares_owned"])
            assert is_num_or_none(filing["percent_of_class"])
            assert is_str_or_none(filing["type_of_reporting_person"])
            assert is_str_or_none(filing["purpose"])
            assert filing["form"] in {"13D", "13G"}
            assert isinstance(filing["is_amendment"], bool)
            assert DATE_RE.match(filing["filing_date"])


class TestProxyRawFields:
    def test_all_fields(self, bundle_and_calls):
        bundle, _ = bundle_and_calls
        proxy = bundle["proxy_raw"]
        assert is_str_or_none(proxy["filing_date"])
        if proxy["filing_date"] is not None:
            assert DATE_RE.match(proxy["filing_date"])
        assert is_str_or_none(proxy["text"])
        if proxy["text"] is not None:
            assert len(proxy["text"]) >= 200
        assert is_str_or_none(proxy["note"])

    def test_digest_text_never_lands_in_the_bundle(self, bundle_and_calls):
        # Same reasoning as filings_raw's own digest_text stripping above --
        # the larger window meant only for the proxy digest LLM call must
        # never leak into the shared bundle every reasoning agent sees.
        bundle, _ = bundle_and_calls
        assert "digest_text" not in bundle["proxy_raw"]
