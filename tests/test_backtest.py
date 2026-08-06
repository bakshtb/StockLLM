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

import re

import numpy as np
import pandas as pd
import pytest

from backtest.engine import (
    MIN_TRADING_DAYS, _clean_stat, _extract_current_status, _extract_trades, _run_one, run_backtests,
)
from backtest.strategies import STRATEGIES, BENCHMARK_TICKER
from dashboard.generate_dashboard import (
    section_backtests, section_price_technicals, section_price_chart, strategy_trade_chart, price_history_chart,
    _backtest_status_box,
)


def _get_chart_option(chart_html: str) -> dict:
    """Given the div HTML register_chart() returned, look up the actual
    registered ECharts option dict -- same pattern as test_charts.py's
    own get_chart_option(), reimplemented here to avoid a cross-test-file
    import for one small helper."""
    import dashboard.generate_dashboard as gd
    m = re.search(r'id="(chart-\d+)"', chart_html)
    assert m, f"expected a chart div with an id, got: {chart_html[:120]!r}"
    return dict(gd._chart_state.charts)[m.group(1)]


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
            assert isinstance(result["trades"], list) and len(result["trades"]) == result["num_trades"]
        else:
            assert result["note"]
        # current_status is computed regardless of trade count -- it's about
        # "right now," not historical performance -- unless the underlying
        # indicator genuinely ended on NaN.
        if result["current_status"] is not None:
            assert result["current_status"]["next_action"] in ("buy", "sell")
            assert result["current_status"]["direction"] in ("above", "below")

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


class TestExtractTradesAndStatus:
    """backtest/engine.py's per-run enrichment: the trade list (for chart
    markers) and the "what would this rule tell me to do right now" status,
    both derived from a real completed Backtest run -- no extra fetches."""

    def _run(self, meta, data):
        import os
        os.environ.setdefault("TQDM_DISABLE", "1")
        from backtesting import Backtest
        bt = Backtest(data, meta["strategy_class"], cash=10_000, commission=0.001,
                      exclusive_orders=True, finalize_trades=True)
        return bt.run()

    def test_trades_have_expected_fields(self):
        meta = next(m for m in STRATEGIES if m["key"] == "rsi_mean_reversion")
        data = _synthetic_ohlcv()
        stats = self._run(meta, data)
        trades = _extract_trades(stats)
        assert int(stats["# Trades"]) == len(trades)
        if trades:
            t = trades[0]
            assert set(t.keys()) == {"entry_date", "entry_price", "exit_date", "exit_price", "return_pct"}
            assert t["entry_date"] < t["exit_date"]

    def test_price_kind_status_has_a_real_price_target(self):
        meta = next(m for m in STRATEGIES if m["key"] == "bollinger_band_reversion")
        data = _synthetic_ohlcv()
        stats = self._run(meta, data)
        status = _extract_current_status(meta, stats)
        assert status["trigger_kind"] == "price"
        assert status["unit"] == "$"
        assert status["trigger_label"] in ("Upper Bollinger Band", "Lower Bollinger Band")

    def test_reading_kind_status_has_no_price_unit(self):
        meta = next(m for m in STRATEGIES if m["key"] == "rsi_mean_reversion")
        data = _synthetic_ohlcv()
        stats = self._run(meta, data)
        status = _extract_current_status(meta, stats)
        assert status["trigger_kind"] == "reading"
        assert status["unit"] == ""
        assert status["trigger_value"] in (30, 70)  # oversold or overbought threshold

    def test_status_fn_exception_returns_none_not_crash(self):
        meta = {"status_fn": lambda instance: (_ for _ in ()).throw(AttributeError("boom"))}
        data = _synthetic_ohlcv()
        stats = self._run({**next(m for m in STRATEGIES if m["key"] == "rsi_mean_reversion"), **meta}, data)
        assert _extract_current_status(meta, stats) is None

    def test_status_with_nan_current_value_returns_none(self):
        meta = {"status_fn": lambda instance: {
            "holding": False, "next_action": "buy", "trigger_kind": "reading",
            "trigger_label": "x", "trigger_value": 30.0, "current_label": "y",
            "current_value": float("nan"), "unit": "", "direction": "below",
        }}
        data = _synthetic_ohlcv()
        stats = self._run(next(m for m in STRATEGIES if m["key"] == "rsi_mean_reversion"), data)
        assert _extract_current_status(meta, stats) is None

    def test_trend_filtered_dip_flags_trend_filter_as_the_real_blocker(self):
        """Regression case: TrendFilteredDip needs RSI oversold AND price
        above its 200-day average. A naive status readout that only shows
        the RSI half would be actively misleading whenever RSI looks ready
        to fire but the trend filter is the real, silent blocker -- craft
        exactly that: a long decline (price well below its 200-day average)
        that also leaves RSI oversold at the end."""
        n = 800
        t = np.arange(n)
        # steady decline, mostly monotonic -- keeps price under its own
        # 200-day trailing average right up to the last bar, and the final
        # stretch trending down keeps RSI low too.
        close = 200 - 0.15 * t + np.sin(t / 15)
        close = np.maximum(close, 1)
        dates = pd.bdate_range("2020-01-02", periods=n)
        data = pd.DataFrame({
            "Open": close, "High": close + 0.5, "Low": close - 0.5, "Close": close,
            "Volume": np.full(n, 1_000_000),
        }, index=dates)

        meta = next(m for m in STRATEGIES if m["key"] == "trend_filtered_dip")
        stats = self._run(meta, data)
        status = _extract_current_status(meta, stats)
        assert status is not None
        if not status["holding"]:
            # Only meaningful to assert the extra_note when the trend
            # filter is actually the blocker -- guard rather than assume,
            # since this is real (not mocked) indicator math.
            price_now = float(data["Close"].iloc[-1])
            trend_ma_now = float(pd.Series(data["Close"]).rolling(200).mean().iloc[-1])
            if price_now <= trend_ma_now:
                assert "extra_note" in status
                assert "200-day average" in status["extra_note"]


class TestStrategyTradeChart:
    def test_returns_none_for_empty_price_series(self):
        assert strategy_trade_chart([], []) is None

    def test_builds_chart_html_with_price_series_and_trades(self):
        price_series = [{"date": "2024-01-02", "close": 100.0}, {"date": "2024-01-03", "close": 101.0}]
        trades = [{"entry_date": "2024-01-02", "entry_price": 100.0, "exit_date": "2024-01-03",
                   "exit_price": 101.0, "return_pct": 1.0}]
        html = strategy_trade_chart(price_series, trades)
        assert html is not None
        assert "echarts-container" in html


class TestBuildPriceSeries:
    """backtest/engine.py's _build_price_series() -- full OHLCV + moving
    average overlays, shared by strategy_trade_chart() and the main
    interactive price_history_chart(), computed once."""

    def test_full_ohlcv_and_moving_averages_present(self):
        from backtest.engine import _build_price_series
        data = _synthetic_ohlcv(n=250)
        series = _build_price_series(data)
        assert len(series) == 250
        for key in ("date", "open", "high", "low", "close", "volume", "ma20", "ma50", "ma200"):
            assert key in series[0]

    def test_moving_averages_none_during_warmup_then_populated(self):
        from backtest.engine import _build_price_series
        data = _synthetic_ohlcv(n=250)
        series = _build_price_series(data)
        assert series[0]["ma20"] is None  # day 1: nowhere near 20 days of history yet
        assert series[19]["ma20"] is not None  # day 20: exactly enough for a 20-day average
        assert series[198]["ma200"] is None  # day 199: one short of 200
        assert series[199]["ma200"] is not None  # day 200: enough


class TestPriceHistoryChart:
    def _price_series(self, n=250, with_gaps=False):
        rng = np.random.default_rng(1)
        base = 100 + np.cumsum(rng.normal(0, 1, n))
        dates = pd.bdate_range("2024-01-02", periods=n)
        series = []
        for i, (d, c) in enumerate(zip(dates, base)):
            series.append({
                "date": d.strftime("%Y-%m-%d"),
                "open": None if with_gaps and i == 5 else round(float(c) - 0.3, 2),
                "high": round(float(c) + 0.5, 2), "low": round(float(c) - 0.5, 2),
                "close": round(float(c), 2), "volume": 1_000_000 + i * 100,
                "ma20": round(float(c), 2) if i >= 19 else None,
                "ma50": round(float(c), 2) if i >= 49 else None,
                "ma200": round(float(c), 2) if i >= 199 else None,
            })
        return series

    def test_returns_none_for_empty_series(self):
        assert price_history_chart([]) is None

    def test_builds_a_single_price_series(self):
        """No MA20/50/200 overlay, no volume subplot (an earlier version
        had both) -- see price_history_chart's docstring for why."""
        import dashboard.generate_dashboard as gd
        gd._reset_chart_registry()
        html = price_history_chart(self._price_series())
        assert html is not None
        assert "echarts-container" in html
        option = _get_chart_option(html)
        assert [s["name"] for s in option["series"]] == ["Price"]

    def test_handles_missing_ohlc_gracefully(self):
        """A gap day (e.g. a genuinely missing bar) shouldn't crash chart
        construction -- it should just produce a null candle for that day."""
        html = price_history_chart(self._price_series(with_gaps=True))
        assert html is not None

    def test_price_line_series_shape_and_color(self):
        """Price is a colored area line (not candlesticks -- see
        price_history_chart's docstring for why), green/red by net change
        over the whole series, gradient-filled and topped with a dot at
        the latest close -- both resolved client-side by hydrate.js, so
        this only checks for the token strings it dispatches on."""
        import dashboard.generate_dashboard as gd
        gd._reset_chart_registry()
        series = self._price_series(n=60)
        html = price_history_chart(series)
        option = _get_chart_option(html)
        price = next(s for s in option["series"] if s["name"] == "Price")
        assert price["type"] == "line"
        assert len(price["data"]) == 60
        is_down = series[-1]["close"] < series[0]["close"]
        expected_color = "var(--diverge-neg)" if is_down else "var(--diverge-pos)"
        expected_gradient = "__areaGradientNeg__" if is_down else "__areaGradientPos__"
        assert price["lineStyle"]["color"] == expected_color
        assert price["areaStyle"]["color"] == expected_gradient
        first = next(d for d in price["data"] if d is not None)
        assert isinstance(first["value"], (int, float))
        assert price["markPoint"]["data"][0]["coord"] == [59, series[-1]["close"]]
        assert price["markPoint"]["itemStyle"]["color"] == expected_color

    def test_default_zoom_shows_roughly_last_year_for_long_history(self):
        import dashboard.generate_dashboard as gd
        gd._reset_chart_registry()
        html = price_history_chart(self._price_series(n=1500))
        option = _get_chart_option(html)
        # (1 - 252/1500) * 100 =~ 83.2
        assert 80 < option["dataZoom"][0]["start"] < 86
        assert option["dataZoom"][0]["end"] == 100
        # inside + slider zoom, both starting from the same point
        assert option["dataZoom"][0]["start"] == option["dataZoom"][1]["start"]

    def test_short_history_shows_everything(self):
        """Fewer than a year of trading days (e.g. a very recent IPO) --
        the default view should show all of it, not a near-empty sliver."""
        import dashboard.generate_dashboard as gd
        gd._reset_chart_registry()
        html = price_history_chart(self._price_series(n=100))
        option = _get_chart_option(html)
        assert option["dataZoom"][0]["start"] == 0.0


class TestSectionPriceChart:
    """The interactive price chart lives in its own top-level
    section_price_chart(), promoted out of section_price_technicals to
    always-visible above the tab bar (see build_dashboard()) -- user
    feedback, a phone stock app reference: price + chart always at the
    top, tabs after."""

    def test_missing_backtests_key_omits_history_chart_not_crash(self):
        html = section_price_chart({"price": {}})
        assert "price-chart-wrap" not in html

    def test_present_price_series_renders_history_chart_and_range_buttons(self):
        series = TestPriceHistoryChart()._price_series(n=300)
        bundle = {"price": {}, "backtests": {"price_series": series}}
        html = section_price_chart(bundle)
        assert "price-chart-wrap" in html
        assert "chart-toolbar" in html
        assert 'data-days="252"' in html
        assert "echarts-container" in html


class TestSectionPriceTechnicalsWithoutChart:
    def test_no_history_chart_markup_left_in_this_section(self):
        """section_price_chart owns the chart now -- this section should
        have neither the chart wrapper nor the range-button toolbar."""
        series = TestPriceHistoryChart()._price_series(n=300)
        bundle = {"price": {}, "backtests": {"price_series": series}}
        html = section_price_technicals(bundle)
        assert "price-chart-wrap" not in html
        assert "chart-toolbar" not in html


class TestBacktestStatusBox:
    def _status(self, **overrides):
        base = {
            "holding": False, "next_action": "buy", "trigger_kind": "reading",
            "trigger_label": "RSI oversold threshold", "trigger_value": 30.0,
            "current_label": "Current RSI", "current_value": 45.2, "unit": "", "direction": "below",
        }
        base.update(overrides)
        return base

    def test_none_status_renders_fallback_box_not_crash(self):
        html = _backtest_status_box(None)
        assert "status-box" in html
        assert "Not enough data to show a current reading" in html

    def test_reading_kind_box_mentions_current_and_trigger(self):
        html = _backtest_status_box(self._status())
        assert "Current RSI" in html
        assert "45.2" in html
        assert "Buy trigger" in html
        assert "30.0" in html
        assert "RSI oversold threshold" in html
        assert "drops below" in html

    def test_price_kind_uses_dollar_formatting(self):
        html = _backtest_status_box(self._status(
            trigger_kind="price", unit="$", current_label="Current price",
            current_value=303.42, trigger_value=302.26, trigger_label="Lower Bollinger Band",
            direction="below",
        ))
        assert "$303.42" in html
        assert "$302.26" in html

    def test_sell_action_uses_sell_verb(self):
        html = _backtest_status_box(self._status(holding=True, next_action="sell", direction="above"))
        assert "Sell trigger" in html
        assert ">Holding<" in html

    def test_extra_note_gets_appended_to_caption(self):
        html = _backtest_status_box(self._status(extra_note="Also needs X."))
        assert "Also needs X." in html


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

    def _bundle_with(self, strategies, note=None, price_series=None):
        return {
            "backtests": {
                "years_tested": 6.0, "history_start": "2020-08-01", "history_end": "2026-08-01",
                "price_series": price_series or [], "strategies": strategies, "note": note,
            },
        }

    def _status(self, **overrides):
        base = {
            "holding": False, "next_action": "buy", "trigger_kind": "reading",
            "trigger_label": "RSI oversold threshold", "trigger_value": 30.0,
            "current_label": "Current RSI", "current_value": 45.2, "unit": "", "direction": "below",
        }
        base.update(overrides)
        return base

    def _strategy(self, **overrides):
        base = {
            "key": "rsi_mean_reversion", "name": "RSI Mean-Reversion", "category": "Mean-reversion",
            "explanation": "Buys when oversold.", "return_pct": 34.2, "buy_hold_return_pct": 51.0,
            "win_rate_pct": 62.5, "num_trades": 8, "max_drawdown_pct": -18.3, "sharpe_ratio": 0.71,
            "beat_buy_hold": False, "current_status": self._status(), "trades": [], "note": None,
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
                            beat_buy_hold=None, current_status=self._status(),
                            note="This rule never actually triggered a trade."),
        ]))
        assert "No trades" in html
        assert ">None<" not in html
        assert "$None" not in html

    def test_holding_shows_holding_badge(self):
        html = section_backtests(self._bundle_with([
            self._strategy(current_status=self._status(holding=True, next_action="sell", direction="above")),
        ]))
        assert ">Holding<" in html

    def test_not_holding_shows_not_holding_badge(self):
        html = section_backtests(self._bundle_with([self._strategy(current_status=self._status(holding=False))]))
        assert "Not Holding" in html

    def test_missing_current_status_shows_fallback_not_crash(self):
        html = section_backtests(self._bundle_with([self._strategy(current_status=None)]))
        assert "Not enough data to show a current reading" in html
        assert ">None<" not in html

    def test_status_box_shows_current_and_trigger_as_stat_tiles(self):
        html = section_backtests(self._bundle_with([
            self._strategy(current_status=self._status(current_value=43.5, trigger_value=30.0)),
        ]))
        assert "status-box" in html
        assert "Current RSI" in html
        assert "43.5" in html
        assert "Buy trigger" in html
        assert "30.0" in html

    def test_extra_note_appears_in_rendered_status(self):
        html = section_backtests(self._bundle_with([
            self._strategy(current_status=self._status(extra_note="Also needs the trend filter.")),
        ]))
        assert "Also needs the trend filter." in html

    def test_no_trades_means_no_chart_disclosure(self):
        html = section_backtests(self._bundle_with(
            [self._strategy(trades=[])],
            price_series=[{"date": "2024-01-02", "close": 100.0}],
        ))
        assert "chart-disclosure" not in html

    def test_trades_and_price_series_render_chart_disclosure(self):
        html = section_backtests(self._bundle_with(
            [self._strategy(trades=[
                {"entry_date": "2024-01-02", "entry_price": 100.0, "exit_date": "2024-01-03",
                 "exit_price": 101.0, "return_pct": 1.0},
            ])],
            price_series=[{"date": "2024-01-02", "close": 100.0}, {"date": "2024-01-03", "close": 101.0}],
        ))
        assert "chart-disclosure" in html
        assert "Show chart" in html
        assert "echarts-container" in html

    def test_trades_but_no_price_series_means_no_chart(self):
        """Belt-and-suspenders: a chart with markers but no price line
        underneath it would be meaningless -- both must be present."""
        html = section_backtests(self._bundle_with(
            [self._strategy(trades=[
                {"entry_date": "2024-01-02", "entry_price": 100.0, "exit_date": "2024-01-03",
                 "exit_price": 101.0, "return_pct": 1.0},
            ])],
            price_series=[],
        ))
        assert "chart-disclosure" not in html

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
            current_status=None, trades=[],  # matches engine.py's real benchmark-unavailable shape
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
        assert len(result["price_series"]) > 0
        assert len(result["strategies"]) == len(STRATEGIES)
        for s in result["strategies"]:
            assert s["num_trades"] is None or s["num_trades"] >= 0
            if s["num_trades"]:
                assert len(s["trades"]) == s["num_trades"]
            if s["current_status"] is not None:
                assert s["current_status"]["next_action"] in ("buy", "sell")
