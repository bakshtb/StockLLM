"""
Regression tests for a real, user-reported data-accuracy bug: MBLY's
dashboard showed a stale price ($7.94 vs. the real $8.08) and a market cap
understated by ~3.4x ($2.04B vs. the real ~$6.87B). Root-caused directly
against live data (see HANDOFF.md for the full investigation):

  1. data/fetch_prices.py's current_price came only from `.history()`'s
     last daily bar, which can lag a live quote by up to a session.
  2. data/fetch_fundamentals.py trusted yfinance's marketCap/
     sharesOutstanding as-is, which only reflect the publicly-traded share
     class -- Mobileye has a second, entirely Intel-held Class B that
     yfinance silently omits.

These tests use synthetic/mocked data (no real network calls) -- see
tests/test_live_fetchers.py for the live smoke tests these fixes also
have to keep passing.
"""

import pandas as pd
import pytest

from data.fetch_fundamentals import fetch_fundamentals
from data.fetch_prices import fetch_price_summary
from data.fetch_shares_outstanding import _SHARE_CLASS_RE, fetch_true_shares_outstanding


class _FakeFastInfo(dict):
    """yfinance's real fast_info supports both dict-style .get() and
    attribute access -- only .get() is used by our code, so a plain dict
    subclass is a faithful enough stand-in."""


class _FakeTicker:
    def __init__(self, history_df, fast_info=None, info=None, calendar=None):
        self._history_df = history_df
        self.fast_info = _FakeFastInfo(fast_info or {})
        self.info = info or {}
        self.calendar = calendar

    def history(self, period="1y"):
        return self._history_df


def _synthetic_history(closes, start="2025-01-02"):
    n = len(closes)
    dates = pd.bdate_range(start, periods=n)
    return pd.DataFrame({
        "Open": closes, "High": [c + 0.1 for c in closes], "Low": [c - 0.1 for c in closes],
        "Close": closes, "Volume": [1_000_000] * n,
    }, index=dates)


class TestFetchPriceSummaryPrefersLiveQuote:
    def test_uses_fast_info_price_when_available(self, monkeypatch):
        import data.fetch_prices as fp
        hist = _synthetic_history([10.0] * 30 + [7.94])  # last history bar: stale
        fake = _FakeTicker(hist, fast_info={"lastPrice": 8.08})
        monkeypatch.setattr(fp.yf, "Ticker", lambda ticker: fake)

        result = fetch_price_summary("MBLY")
        assert result["current_price"] == 8.08  # live quote, not the stale 7.94 history close

    def test_falls_back_to_history_close_when_fast_info_missing(self, monkeypatch):
        import data.fetch_prices as fp
        hist = _synthetic_history([10.0] * 30 + [7.94])
        fake = _FakeTicker(hist, fast_info={})  # no lastPrice key
        monkeypatch.setattr(fp.yf, "Ticker", lambda ticker: fake)

        result = fetch_price_summary("MBLY")
        assert result["current_price"] == 7.94

    def test_falls_back_to_history_close_when_fast_info_raises(self, monkeypatch):
        import data.fetch_prices as fp

        class _BrokenFastInfo:
            def get(self, *a, **k):
                raise RuntimeError("boom")

        hist = _synthetic_history([10.0] * 30 + [7.94])
        fake = _FakeTicker(hist)
        fake.fast_info = _BrokenFastInfo()
        monkeypatch.setattr(fp.yf, "Ticker", lambda ticker: fake)

        result = fetch_price_summary("MBLY")
        assert result["current_price"] == 7.94  # never raises, just falls back


class TestShareClassRegex:
    def test_matches_real_filing_pattern(self):
        text = (
            "Class A common stock: $0.01 par value; 4,000,000,000 shares authorized; "
            "shares issued and outstanding: 242,205,475 as of June 27, 2026 "
            "Class B common stock: $0.01 par value; 1,500,000,000 shares authorized; "
            "shares issued and outstanding: 597,768,015 as of June 27, 2026"
        )
        matches = _SHARE_CLASS_RE.findall(text)
        assert ("A", "242,205,475") in matches
        assert ("B", "597,768,015") in matches

    def test_no_match_for_single_class_boilerplate(self):
        text = "Common stock: $0.01 par value; shares issued and outstanding: 100,000,000"
        assert _SHARE_CLASS_RE.findall(text) == []


class TestFetchTrueSharesOutstanding:
    def _patch_edgar(self, monkeypatch, filing_text, forms=("10-Q",)):
        import data.fetch_shares_outstanding as mod
        monkeypatch.setattr(mod, "get_cik_for_ticker", lambda ticker: "0001910139")
        monkeypatch.setattr(mod, "get_submissions", lambda cik: {
            "filings": {"recent": {
                "form": list(forms), "accessionNumber": ["0001-26-000001"] * len(forms),
                "primaryDocument": ["filing.htm"] * len(forms),
            }},
        })
        monkeypatch.setattr(mod, "fetch_document", lambda cik, accession, doc: filing_text)

    def test_multi_class_structure_detected_and_summed(self, monkeypatch):
        text = (
            "Class A common stock: shares issued and outstanding: 242,205,475 as of June 27, 2026 "
            "Class B common stock: shares issued and outstanding: 597,768,015 as of June 27, 2026"
        )
        self._patch_edgar(monkeypatch, text)
        result = fetch_true_shares_outstanding("MBLY")
        assert result["total_shares"] == 242_205_475 + 597_768_015
        assert result["by_class"] == {"A": 242_205_475, "B": 597_768_015}
        assert result["source_filing"] == "10-Q"
        assert result["note"] is None

    def test_single_class_returns_none_total(self, monkeypatch):
        text = "Common stock outstanding: 100,000,000 shares. No other class exists."
        self._patch_edgar(monkeypatch, text)
        result = fetch_true_shares_outstanding("AAPL")
        assert result["total_shares"] is None
        assert "Single-class" in result["note"]

    def test_no_10q_or_10k_found(self, monkeypatch):
        import data.fetch_shares_outstanding as mod
        monkeypatch.setattr(mod, "get_cik_for_ticker", lambda ticker: "0001234567")
        monkeypatch.setattr(mod, "get_submissions", lambda cik: {
            "filings": {"recent": {"form": ["8-K"], "accessionNumber": ["x"], "primaryDocument": ["x.htm"]}},
        })
        result = fetch_true_shares_outstanding("XYZ")
        assert result["total_shares"] is None
        assert "No recent 10-Q/10-K" in result["note"]

    def test_no_cik_found(self, monkeypatch):
        import data.fetch_shares_outstanding as mod
        monkeypatch.setattr(mod, "get_cik_for_ticker", lambda ticker: None)
        result = fetch_true_shares_outstanding("NOTREAL")
        assert result["total_shares"] is None
        assert "Could not resolve SEC CIK" in result["note"]

    def test_network_failure_never_raises(self, monkeypatch):
        import data.fetch_shares_outstanding as mod

        def _raise(ticker):
            raise RuntimeError("network down")

        monkeypatch.setattr(mod, "get_cik_for_ticker", _raise)
        result = fetch_true_shares_outstanding("MBLY")
        assert result["total_shares"] is None
        assert "Could not verify" in result["note"]

    def test_duplicate_class_mentions_keep_the_larger_figure(self, monkeypatch):
        """A class letter mentioned twice (e.g. cover page + balance sheet,
        or current + prior period) should keep the larger of the two --
        not silently overwrite with whichever appeared last."""
        text = (
            "Class A common stock: shares issued and outstanding: 200,000,000 as of last year "
            "Class A common stock: shares issued and outstanding: 242,205,475 as of June 27, 2026 "
            "Class B common stock: shares issued and outstanding: 597,768,015 as of June 27, 2026"
        )
        self._patch_edgar(monkeypatch, text)
        result = fetch_true_shares_outstanding("MBLY")
        assert result["by_class"]["A"] == 242_205_475


class TestFetchFundamentalsMarketCapCorrection:
    def _patch_ticker(self, monkeypatch, market_cap, shares_outstanding):
        import data.fetch_fundamentals as ff
        fake = _FakeTicker(
            history_df=None,
            info={"marketCap": market_cap, "sharesOutstanding": shares_outstanding, "trailingPE": 10.0},
        )
        monkeypatch.setattr(ff.yf, "Ticker", lambda ticker: fake)

    def test_corrects_market_cap_for_confirmed_multi_class_structure(self, monkeypatch):
        import data.fetch_fundamentals as ff
        self._patch_ticker(monkeypatch, market_cap=2_039_550_208, shares_outstanding=252_419_583)
        monkeypatch.setattr(ff, "fetch_true_shares_outstanding", lambda ticker: {
            "total_shares": 839_973_490, "by_class": {"A": 242_205_475, "B": 597_768_015},
            "source_filing": "10-Q", "note": None,
        })
        result = fetch_fundamentals("MBLY", current_price=8.08)
        # 839,973,490 * 8.08 = 6,787,014,398.2 -> "6.79B"
        assert result["market_cap"] == "6.79B"
        assert result["note"] is not None
        assert "multi-class" in result["note"]

    def test_leaves_market_cap_alone_when_no_multi_class_structure_found(self, monkeypatch):
        import data.fetch_fundamentals as ff
        self._patch_ticker(monkeypatch, market_cap=3_000_000_000_000, shares_outstanding=15_000_000_000)
        monkeypatch.setattr(ff, "fetch_true_shares_outstanding", lambda ticker: {
            "total_shares": None, "by_class": {}, "source_filing": None, "note": "Single-class.",
        })
        result = fetch_fundamentals("AAPL", current_price=200.0)
        assert result["market_cap"] == "3.00T"
        assert result["note"] is None

    def test_ignores_a_barely_larger_total_not_worth_correcting(self, monkeypatch):
        """A filing-derived total that's only marginally higher than
        yfinance's own figure (date/rounding noise between two sources, not
        a real multi-class gap) shouldn't trigger a correction -- only a
        genuinely large (>10%) gap should."""
        import data.fetch_fundamentals as ff
        self._patch_ticker(monkeypatch, market_cap=1_000_000_000, shares_outstanding=100_000_000)
        monkeypatch.setattr(ff, "fetch_true_shares_outstanding", lambda ticker: {
            "total_shares": 102_000_000, "by_class": {"A": 102_000_000},
            "source_filing": "10-Q", "note": None,
        })
        result = fetch_fundamentals("TEST", current_price=10.0)
        assert result["market_cap"] == "1.00B"
        assert result["note"] is None

    def test_no_current_price_skips_correction_entirely(self, monkeypatch):
        """fetch_fundamentals(ticker) with no current_price (e.g. the
        module's own CLI usage) must not crash, and must not attempt a
        correction it has no price to compute with."""
        import data.fetch_fundamentals as ff
        self._patch_ticker(monkeypatch, market_cap=2_039_550_208, shares_outstanding=252_419_583)
        called = []
        monkeypatch.setattr(ff, "fetch_true_shares_outstanding", lambda ticker: called.append(ticker) or {})
        result = fetch_fundamentals("MBLY")
        assert result["market_cap"] == "2.04B"
        assert called == []  # never even attempted the EDGAR lookup
