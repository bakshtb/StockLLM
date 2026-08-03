"""
Tests for the backtest/ package (strategies.py + engine.py) and its
dashboard/generate_dashboard.py section_backtests() rendering.

Tier 1 tests (default `pytest` run) use synthetic price data -- no network,
no real yfinance calls -- checking that each strategy runs cleanly and that
the engine's error/empty-data handling matches every other data/fetch_*.py
module's "never raise, return a note instead" convention. One
@pytest.mark.live test at the bottom exercises the real yfinance fetch path,
same pattern as tests/test_live_fetchers.py.
"""

import numpy as np
import pandas as pd
import pytest

from backtest.engine import MIN_TRADING_DAYS, _clean_stat, _run_one, run_backtests
from backtest.strategies import STRATEGIES, BENCHMARK_TICKER
from dashboard.generate_dashboard import section_backtests


def _synthetic_ohlcv(n=800, seed=0, with_benchmark=False):
    """A wavy synthetic price series long enough (n=800 trading days, ~3
    years) for every strategy's indicators -- including the 200-day moving
    average -- to warm up and actually fire a few trades, so tests exercise
    real strategy logic rather than only the "not enough data" branch."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    base = 100 + 0.03 * t + 15 * np.sin(t / 40) + 8 * np.sin(t / 13)
    close = np.maximum(base + rng.normal(0, 1.0, n), 1)
    high = close + rng.uniform(0.1, 1.5, n)
    low = close - rng.uniform(0.1, 1.5, n)
    open_ = close + rng.uniform(-0.5, 0.5, n)
    volume = rng.integers(1_000_000, 5_000_000, n)
    dates = pd.bdate_range("2020-01-02", periods=n)
    data = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=dates,
    )
    if with_benchmark:
        data["Benchmark"] = 100 + 0.02 * t + rng.normal(0, 0.5, n)
    return data


class TestStrategies:
    """Each strategy actually runs against real backtesting.Backtest without
    raising, using synthetic data long enough for its slowest indicator."""

    @pytest.mark.parametrize("meta", STRATEGIES, ids=[m["key"] for m in STRATEGIES])
    def test_strategy_runs_without_raising(self, meta):
        data = _synthetic_ohlcv(with_benchmark=meta["needs_benchmark"])
        result = _run_one(meta, data, shared_buy_hold_pct=12.34)
        assert result["key"] == meta["key"]
        assert result["name"] == meta["name"]
        # The Buy & Hold baseline is always the shared value passed in --
        # never recomputed per-strategy (see test_buy_hold_is_identical_
        # across_strategies_with_different_warmups for why that matters).
        assert result["buy_hold_return_pct"] == 12.34
        # Either it produced real numbers, or it cleanly explained why not --
        # never left half-populated or silently wrong.
        if result["num_trades"]:
            assert result["return_pct"] is not None
            assert isinstance(result["beat_buy_hold"], bool)
        else:
            assert result["note"]

    def test_all_strategies_are_long_only_no_shorting(self):
        """Every strategy's next() should only ever call self.buy()/close(),
        never self.sell() to open a short -- this is asserted at the source
        level since it's a design invariant, not something a single backtest
        run would reliably reveal (a strategy could go a whole test without
        hitting its sell-side branch)."""
        import inspect
        for meta in STRATEGIES:
            src = inspect.getsource(meta["strategy_class"])
            assert "self.sell()" not in src, f"{meta['key']} calls self.sell() -- should be long-only"

    def test_relative_strength_requires_benchmark_column(self):
        """Confirms the one strategy needing a second price series is
        flagged as such -- the engine relies on this flag to know which
        strategies need the extra Benchmark column joined in."""
        rel = next(m for m in STRATEGIES if m["key"] == "relative_strength")
        assert rel["needs_benchmark"] is True
        others = [m for m in STRATEGIES if m["key"] != "relative_strength"]
        assert all(not m["needs_benchmark"] for m in others)

    def test_strategy_keys_are_unique(self):
        keys = [m["key"] for m in STRATEGIES]
        assert len(keys) == len(set(keys))


class TestCleanStat:
    def test_none_stays_none(self):
        assert _clean_stat(None) is None

    def test_nan_becomes_none(self):
        assert _clean_stat(float("nan")) is None

    def test_rounds_to_two_decimals(self):
        assert _clean_stat(12.3456) == 12.35

    def test_non_numeric_becomes_none(self):
        assert _clean_stat("not a number") is None


class TestRunBacktests:
    def test_insufficient_history_returns_note_not_crash(self, monkeypatch):
        import backtest.engine as engine_module

        short_data = _synthetic_ohlcv(n=MIN_TRADING_DAYS - 5)
        monkeypatch.setattr(engine_module, "_fetch_history", lambda ticker: short_data)

        result = run_backtests("FAKE")
        assert result["strategies"] == []
        assert "too little" in result["note"]

    def test_total_fetch_failure_returns_note_not_crash(self, monkeypatch):
        import backtest.engine as engine_module

        def _raise(ticker):
            raise ValueError("no data found")

        monkeypatch.setattr(engine_module, "_fetch_history", _raise)

        result = run_backtests("FAKE")
        assert result["strategies"] == []
        assert result["note"]

    def test_enough_history_runs_every_strategy(self, monkeypatch):
        import backtest.engine as engine_module

        data = _synthetic_ohlcv(n=800)
        bench = _synthetic_ohlcv(n=800, seed=1)

        def _fake_fetch(ticker):
            return bench[["Open", "High", "Low", "Close", "Volume"]] if ticker == BENCHMARK_TICKER else data

        monkeypatch.setattr(engine_module, "_fetch_history", _fake_fetch)

        result = run_backtests("FAKE")
        assert result["years_tested"] is not None
        assert len(result["strategies"]) == len(STRATEGIES)
        assert {s["key"] for s in result["strategies"]} == {m["key"] for m in STRATEGIES}

    def test_buy_hold_return_is_identical_across_every_strategy(self, monkeypatch):
        """Regression test for a real bug: backtesting.py's own built-in
        "Buy & Hold Return [%]" stat is computed from each strategy's own
        indicator-warmup point (day ~14 for RSI, day 200 for a 200-day
        moving average), not from the same starting day -- so strategies
        were silently being compared against different Buy & Hold
        baselines. Every strategy must report the exact same
        buy_hold_return_pct, computed once from the full raw price series."""
        import backtest.engine as engine_module

        data = _synthetic_ohlcv(n=800)
        bench = _synthetic_ohlcv(n=800, seed=1)

        def _fake_fetch(ticker):
            return bench[["Open", "High", "Low", "Close", "Volume"]] if ticker == BENCHMARK_TICKER else data

        monkeypatch.setattr(engine_module, "_fetch_history", _fake_fetch)

        result = run_backtests("FAKE")
        buy_hold_values = {s["buy_hold_return_pct"] for s in result["strategies"]}
        assert len(buy_hold_values) == 1, f"expected one shared value, got {buy_hold_values}"

        expected = round((data["Close"].iloc[-1] - data["Close"].iloc[0]) / data["Close"].iloc[0] * 100, 2)
        assert buy_hold_values.pop() == expected

    def test_benchmark_fetch_failure_only_affects_relative_strength(self, monkeypatch):
        import backtest.engine as engine_module

        data = _synthetic_ohlcv(n=800)

        def _fake_fetch(ticker):
            if ticker == BENCHMARK_TICKER:
                raise ValueError("benchmark unavailable")
            return data

        monkeypatch.setattr(engine_module, "_fetch_history", _fake_fetch)

        result = run_backtests("FAKE")
        by_key = {s["key"]: s for s in result["strategies"]}
        assert by_key["relative_strength"]["note"]
        assert by_key["relative_strength"]["num_trades"] is None
        # every other strategy is unaffected by the benchmark failure
        assert by_key["rsi_mean_reversion"]["num_trades"] is not None


class TestSectionBacktestsDashboard:
    """dashboard/generate_dashboard.py's section_backtests(), against
    synthetic bundle shapes -- see test_dashboard_build.py for the
    full-fixture leaked-None/nan sweep this feature also has to pass."""

    def _bundle_with(self, strategies, note=None):
        return {
            "backtests": {
                "years_tested": 6.0, "history_start": "2020-08-01", "history_end": "2026-08-01",
                "strategies": strategies, "note": note,
            },
        }

    def _strategy(self, **overrides):
        base = {
            "key": "rsi_mean_reversion", "name": "RSI Mean-Reversion", "category": "Mean-reversion",
            "explanation": "Buys when oversold.", "return_pct": 34.2, "buy_hold_return_pct": 51.0,
            "win_rate_pct": 62.5, "num_trades": 8, "max_drawdown_pct": -18.3, "sharpe_ratio": 0.71,
            "beat_buy_hold": False, "note": None,
        }
        base.update(overrides)
        return base

    def test_missing_backtests_key_renders_empty_state_not_crash(self):
        html = section_backtests({})
        assert "sec-backtests" in html
        assert "Strategy Backtests" in html

    def test_empty_strategies_list_shows_note(self):
        html = section_backtests(self._bundle_with([], note="Only 40 trading days available."))
        assert "Only 40 trading days available." in html

    def test_populated_strategies_render_names_and_explanations(self):
        html = section_backtests(self._bundle_with([self._strategy()]))
        assert "RSI Mean-Reversion" in html
        assert "Buys when oversold." in html

    def test_beat_buy_hold_true_shows_positive_badge(self):
        html = section_backtests(self._bundle_with([self._strategy(beat_buy_hold=True)]))
        assert "Beat Buy &amp; Hold" in html
        assert "good" in html

    def test_beat_buy_hold_false_shows_negative_badge(self):
        html = section_backtests(self._bundle_with([self._strategy(beat_buy_hold=False)]))
        assert "Underperformed" in html
        assert "critical" in html

    def test_zero_trades_shows_no_trades_badge_not_none_leak(self):
        html = section_backtests(self._bundle_with([
            self._strategy(return_pct=None, buy_hold_return_pct=None, win_rate_pct=None,
                            num_trades=0, max_drawdown_pct=None, sharpe_ratio=None,
                            beat_buy_hold=None, note="This rule never actually triggered a trade."),
        ]))
        assert "No trades" in html
        assert ">None<" not in html
        assert "$None" not in html

    def test_no_leaked_none_across_all_strategies(self):
        """One of each real strategy shape, including the relative-strength
        no-benchmark-data case -- the exact mix run_backtests() can produce
        for a real ticker."""
        strategies = [self._strategy(key=m["key"], name=m["name"], category=m["category"],
                                      explanation=m["explanation"]) for m in STRATEGIES]
        strategies.append(self._strategy(
            key="relative_strength", name="Relative Strength vs. S&P 500", category="Trend-following",
            explanation="...", return_pct=None, buy_hold_return_pct=None, win_rate_pct=None,
            num_trades=None, max_drawdown_pct=None, sharpe_ratio=None, beat_buy_hold=None,
            note="Benchmark data unavailable.",
        ))
        html = section_backtests(self._bundle_with(strategies))
        assert ">None<" not in html
        assert "$None" not in html
        assert "None%" not in html


@pytest.mark.live
class TestRunBacktestsLive:
    """Hits real yfinance data -- see tests/test_live_fetchers.py's module
    docstring for why these are excluded from the default test run."""

    def test_aapl_produces_every_strategy(self):
        result = run_backtests("AAPL")
        assert result["years_tested"] is not None
        assert len(result["strategies"]) == len(STRATEGIES)
        for s in result["strategies"]:
            assert s["num_trades"] is None or s["num_trades"] >= 0
