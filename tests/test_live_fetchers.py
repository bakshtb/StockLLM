"""
Tier 2 -- hits real external APIs (yfinance, SEC EDGAR, StockTwits). Marked
@pytest.mark.live and excluded from CI by default (pytest.ini's addopts);
run explicitly with `pytest -m live -v`. Never run unattended -- these are
slow, network-dependent, and can fail for reasons that have nothing to do
with code correctness (market closed, rate limits, a filing not present
today).

These assert SHAPE, not exact values -- prices/ratings/news change daily.
Every data/fetch_*.py module is designed to never raise on a data-source
failure (empty result + a `note` string instead), so these mostly assert
"the right keys exist and are the right type," not "the fetch succeeded."
AAPL is used throughout: large-cap, always has price history, dividends,
options, analyst coverage, and SEC filings, so it's the one ticker where
every module's "happy path" -- not just its failure fallback -- actually
gets exercised.
"""

import pytest

from data.fetch_prices import fetch_price_summary
from data.fetch_fundamentals import fetch_fundamentals
from data.fetch_analyst_ratings import fetch_analyst_ratings
from data.fetch_news import fetch_news_summary
from data.fetch_balance_sheet import fetch_balance_sheet_health
from data.fetch_income_statement import fetch_income_statement
from data.fetch_earnings_estimates import fetch_earnings_estimates
from data.fetch_dividends_buybacks import fetch_dividends_buybacks
from data.fetch_insider import fetch_insider_transactions
from data.fetch_institutional import fetch_institutional_ownership
from data.fetch_beneficial_ownership import fetch_beneficial_ownership
from data.fetch_form144 import fetch_form144_notices
from data.fetch_options_sentiment import fetch_options_sentiment
from data.fetch_relative_performance import fetch_relative_performance
from data.fetch_macro_context import fetch_macro_context
from data.fetch_social_sentiment import fetch_social_sentiment
from data.fetch_proxy import fetch_proxy_raw
from data.fetch_filings import fetch_filings_raw
from data.fetch_fmp_valuation import fetch_fmp_valuation
from data.fetch_finnhub_signals import fetch_finnhub_signals

TICKER = "AAPL"

pytestmark = pytest.mark.live


class TestFetchPriceSummary:
    def test_shape(self):
        result = fetch_price_summary(TICKER)
        assert isinstance(result["current_price"], float) and result["current_price"] > 0
        assert result["52w_high"] >= result["52w_low"]
        assert result["rsi_14"] is None or 0 <= result["rsi_14"] <= 100
        assert result["volume_trend"] in {"increasing", "decreasing", "stable"}

    def test_invalid_ticker_raises_value_error(self):
        with pytest.raises(ValueError):
            fetch_price_summary("ZZZZZZINVALID")


class TestFetchFundamentals:
    def test_shape(self):
        result = fetch_fundamentals(TICKER)
        assert isinstance(result, dict)
        assert "pe_ratio" in result
        assert result["sector"] is None or isinstance(result["sector"], str)
        assert isinstance(result["short_interest"], dict)


class TestFetchAnalystRatings:
    def test_shape(self):
        result = fetch_analyst_ratings(TICKER)
        assert isinstance(result["actions"], list)
        assert result["lookback_days"] == 60
        for action in result["actions"]:
            assert "date" in action and "firm" in action and "action" in action


class TestFetchNewsSummary:
    def test_shape(self):
        result = fetch_news_summary(TICKER)
        assert isinstance(result, list)
        for item in result:
            assert set(item.keys()) >= {"headline", "source", "date", "snippet", "url"}
            assert item["headline"]


class TestFetchBalanceSheetHealth:
    def test_shape(self):
        result = fetch_balance_sheet_health(TICKER)
        assert isinstance(result, dict)
        assert "total_debt" in result and "free_cash_flow" in result


class TestFetchIncomeStatement:
    def test_shape(self):
        result = fetch_income_statement(TICKER)
        assert result["annual"] is not None
        assert result["annual"]["total_revenue"] > 0
        assert isinstance(result["quarterly"], list)
        assert len(result["quarterly"]) > 0


class TestFetchEarningsEstimates:
    def test_shape(self):
        result = fetch_earnings_estimates(TICKER)
        assert isinstance(result["earnings_surprise_history"], list)
        assert isinstance(result["eps_estimate_trend"], dict)


class TestFetchDividendsBuybacks:
    def test_shape(self):
        result = fetch_dividends_buybacks(TICKER)
        # AAPL pays a dividend -- this is the one place we assert a specific
        # fact about the ticker, since a null yield here would mean the
        # yfinance `info` payload silently changed shape.
        assert result["dividend_yield_pct"] is not None
        assert isinstance(result["recent_dividend_history"], list)


class TestFetchInsiderTransactions:
    def test_shape(self):
        result = fetch_insider_transactions(TICKER)
        assert isinstance(result["transactions"], list)
        for txn in result["transactions"]:
            assert txn["direction"] in {"buy", "sell", "unknown"}


class TestFetchInstitutionalOwnership:
    def test_shape(self):
        result = fetch_institutional_ownership(TICKER)
        assert isinstance(result["top_institutional_holders"], list)


class TestFetchBeneficialOwnership:
    def test_shape(self):
        result = fetch_beneficial_ownership(TICKER)
        assert isinstance(result["filings"], list)


class TestFetchForm144Notices:
    def test_shape(self):
        result = fetch_form144_notices(TICKER)
        assert isinstance(result["notices"], list)


class TestFetchOptionsSentiment:
    def test_shape(self):
        price = fetch_price_summary(TICKER)
        result = fetch_options_sentiment(TICKER, price["current_price"])
        assert isinstance(result, dict)
        if result["put_call_volume_ratio"] is not None:
            assert result["put_call_volume_ratio"] >= 0


class TestFetchRelativePerformance:
    def test_shape(self):
        price = fetch_price_summary(TICKER)
        fundamentals = fetch_fundamentals(TICKER)
        result = fetch_relative_performance(
            TICKER, fundamentals.get("sector"),
            price.get("pct_change_20d"), price.get("pct_change_1y"), fundamentals.get("pe_ratio"),
        )
        assert result["benchmark"] == "SPY"
        assert result["benchmark_pct_change_1y"] is not None


class TestFetchMacroContext:
    def test_shape(self):
        result = fetch_macro_context()
        assert result["vix_level"] is None or result["vix_level"] > 0
        assert result["treasury_10y_yield_pct"] is None or 0 < result["treasury_10y_yield_pct"] < 20

    def test_fred_fields_present_regardless_of_key(self):
        # FRED_API_KEY is optional -- these keys must exist either way, just
        # null if no key is configured in this environment.
        result = fetch_macro_context()
        assert "cpi_yoy_pct" in result
        assert "unemployment_rate_pct" in result
        assert "fed_funds_rate_pct" in result
        assert "yield_curve_10y_2y_pct" in result
        if result["unemployment_rate_pct"] is not None:
            assert 0 < result["unemployment_rate_pct"] < 30
        if result["fed_funds_rate_pct"] is not None:
            assert 0 <= result["fed_funds_rate_pct"] < 20


class TestFetchSocialSentiment:
    def test_shape(self):
        result = fetch_social_sentiment(TICKER)
        assert isinstance(result["message_count"], int)
        assert result["bullish_count"] + result["bearish_count"] <= result["message_count"]


class TestFetchProxyRaw:
    def test_shape(self):
        result = fetch_proxy_raw(TICKER)
        assert "filing_date" in result and "text" in result


class TestFetchFilingsRaw:
    def test_shape(self):
        result = fetch_filings_raw(TICKER)
        assert set(result.keys()) == {"10-K", "10-Q", "8-K"}
        for filing in result.values():
            assert "filing_type" in filing and "text" in filing and "digest_text" in filing

    def test_digest_text_is_at_least_as_long_as_text(self):
        # digest_text uses a larger character budget than text (see
        # config.MAX_FILING_CHARS_FOR_DIGEST vs MAX_FILING_CHARS) and starts
        # from the same jump point, so it can never be shorter.
        result = fetch_filings_raw(TICKER)
        for filing in result.values():
            if filing.get("text") is not None:
                assert len(filing["digest_text"]) >= len(filing["text"])


class TestFetchFmpValuation:
    def test_shape(self):
        # Optional (FMP_API_KEY) -- fields must exist and be well-typed
        # whether or not a key is configured in this environment.
        result = fetch_fmp_valuation(TICKER)
        assert "dcf_value" in result and "peg_ratio" in result
        if result["dcf_value"] is not None:
            assert result["dcf_value"] > 0
        if result["peg_ratio"] is not None:
            assert isinstance(result["peg_ratio"], float)

    def test_invalid_ticker_does_not_raise(self):
        result = fetch_fmp_valuation("ZZZZZINVALID")
        assert result["dcf_value"] is None


class TestFetchFinnhubSignals:
    def test_shape(self):
        # Optional (FINNHUB_API_KEY) -- fields must exist and be well-typed
        # whether or not a key is configured in this environment.
        result = fetch_finnhub_signals(TICKER)
        assert "insider_sentiment_mspr" in result
        assert isinstance(result["insider_sentiment_trend"], list)
        assert isinstance(result["recommendation_trend"], list)
        for row in result["recommendation_trend"]:
            assert set(row.keys()) == {"period", "strong_buy", "buy", "hold", "sell", "strong_sell"}

    def test_invalid_ticker_does_not_raise(self):
        result = fetch_finnhub_signals("ZZZZZINVALID")
        assert result["insider_sentiment_trend"] == []
