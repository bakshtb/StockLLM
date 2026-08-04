"""
A fixed, hand-picked list of well-known technical trading rules, each
implemented as a `backtesting.Strategy` subclass -- see backtest/engine.py for
where these actually get run against a ticker's price history.

Deliberately NOT an open-ended list the LLM can invent its own variations of:
picking a small, well-established, named set avoids the "test enough ideas
and one looks good by chance" trap (the same backtest-overfitting problem
documented in RESEARCH.md's RL section) -- every strategy here is a standard,
widely-known rule, not something hunted for on this data. See RESEARCH.md's
"item 1" writeup for the reasoning behind each pick.

All strategies are long-only (buy to open, close to exit) -- no short
selling. That matches how a retail investor would actually use a signal like
this, and avoids modeling margin/short-borrow mechanics this tool has no
other reason to support.
"""

import numpy as np
import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover

# The relative-strength strategy needs a second ticker's price history
# alongside the one being tested -- same benchmark data/fetch_relative_performance.py
# already uses, for consistency with the rest of the dashboard.
BENCHMARK_TICKER = "SPY"


# ============================================================================
# Indicator helpers -- plain functions over a price array, handed to
# Strategy.I() so backtesting.py can plot/track them. Each returns a numpy
# array the same length as its input; early values are NaN (or a neutral
# fill for RSI) until enough history has accumulated for that indicator.
# ============================================================================

def _rsi(closes, period=14):
    s = pd.Series(closes)
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50).values  # neutral (not oversold/overbought) during warmup


def _sma(closes, period):
    return pd.Series(closes).rolling(period).mean().values


def _macd_line(closes):
    s = pd.Series(closes)
    ema12 = s.ewm(span=12, adjust=False).mean()
    ema26 = s.ewm(span=26, adjust=False).mean()
    return (ema12 - ema26).values


def _macd_signal(closes):
    macd = pd.Series(_macd_line(closes))
    return macd.ewm(span=9, adjust=False).mean().values


def _bb_upper(closes, period=20, num_std=2):
    s = pd.Series(closes)
    mid = s.rolling(period).mean()
    std = s.rolling(period).std()
    return (mid + num_std * std).values


def _bb_lower(closes, period=20, num_std=2):
    s = pd.Series(closes)
    mid = s.rolling(period).mean()
    std = s.rolling(period).std()
    return (mid - num_std * std).values


def _donchian_high(highs, period=20):
    # shift(1): today's signal compares against the PRIOR `period` days only,
    # never including today -- without the shift this would be lookahead bias
    # (today's high trivially IS today's rolling max).
    return pd.Series(highs).rolling(period).max().shift(1).values


def _donchian_low(lows, period=20):
    return pd.Series(lows).rolling(period).min().shift(1).values


def _relative_strength(closes, benchmark, lookback=60):
    stock_change = pd.Series(closes).pct_change(lookback)
    bench_change = pd.Series(benchmark).pct_change(lookback)
    return (stock_change - bench_change).values


# ============================================================================
# Strategies
# ============================================================================

class RsiMeanReversion(Strategy):
    """Buy when RSI says the stock has been sold off a lot ("oversold"),
    sell once it recovers to a neutral-to-strong reading. Bets that a sharp,
    short-term drop tends to bounce back."""
    rsi_period = 14
    oversold = 30
    overbought = 70

    def init(self):
        self.rsi = self.I(_rsi, self.data.Close, self.rsi_period)

    def next(self):
        if self.rsi[-1] < self.oversold and not self.position:
            self.buy()
        elif self.rsi[-1] > self.overbought and self.position:
            self.position.close()


class MacdCrossover(Strategy):
    """Buy when short-term momentum (MACD) turns up and crosses above its
    own signal line, sell when it crosses back below. A trend-following
    rule -- the opposite philosophy from RSI mean-reversion."""

    def init(self):
        self.macd = self.I(_macd_line, self.data.Close)
        self.signal = self.I(_macd_signal, self.data.Close)

    def next(self):
        if crossover(self.macd, self.signal) and not self.position:
            self.buy()
        elif crossover(self.signal, self.macd) and self.position:
            self.position.close()


class MovingAverageCrossover(Strategy):
    """The classic "golden cross"/"death cross": buy when the 50-day average
    price crosses above the 200-day average (a new uptrend forming), sell
    when it crosses back below."""
    fast_period = 50
    slow_period = 200

    def init(self):
        self.fast = self.I(_sma, self.data.Close, self.fast_period)
        self.slow = self.I(_sma, self.data.Close, self.slow_period)

    def next(self):
        if crossover(self.fast, self.slow) and not self.position:
            self.buy()
        elif crossover(self.slow, self.fast) and self.position:
            self.position.close()


class BollingerBandReversion(Strategy):
    """Buy when the price dips below its own statistically-typical range
    (lower Bollinger Band -- "unusually cheap" relative to its recent
    volatility), sell once it pops back above the upper band. A different
    kind of oversold/overbought math than the RSI rule above."""
    period = 20
    num_std = 2

    def init(self):
        self.upper = self.I(_bb_upper, self.data.Close, self.period, self.num_std)
        self.lower = self.I(_bb_lower, self.data.Close, self.period, self.num_std)

    def next(self):
        price = self.data.Close[-1]
        if not np.isnan(self.lower[-1]) and price < self.lower[-1] and not self.position:
            self.buy()
        elif not np.isnan(self.upper[-1]) and price > self.upper[-1] and self.position:
            self.position.close()


class BreakoutChannel(Strategy):
    """Buy when the price breaks out to a new 20-day high (a "the stock is
    breaking out" signal), sell on a new 20-day low. A trend-following rule
    that bets breakouts continue, rather than reverse."""
    period = 20

    def init(self):
        self.upper = self.I(_donchian_high, self.data.High, self.period)
        self.lower = self.I(_donchian_low, self.data.Low, self.period)

    def next(self):
        price = self.data.Close[-1]
        if not np.isnan(self.upper[-1]) and price > self.upper[-1] and not self.position:
            self.buy()
        elif not np.isnan(self.lower[-1]) and price < self.lower[-1] and self.position:
            self.position.close()


class TrendFilteredDip(Strategy):
    """"Buy the dip, but only in an uptrend": same RSI-oversold entry as the
    first rule, but only while the price is still above its own 200-day
    average -- a popular real-world combination of the mean-reversion and
    trend-following ideas above, not just one or the other."""
    rsi_period = 14
    oversold = 35
    overbought = 70
    trend_period = 200

    def init(self):
        self.rsi = self.I(_rsi, self.data.Close, self.rsi_period)
        self.trend_ma = self.I(_sma, self.data.Close, self.trend_period)

    def next(self):
        price = self.data.Close[-1]
        if (not np.isnan(self.trend_ma[-1]) and self.rsi[-1] < self.oversold
                and price > self.trend_ma[-1] and not self.position):
            self.buy()
        elif self.rsi[-1] > self.overbought and self.position:
            self.position.close()


class RelativeStrength(Strategy):
    """Buy when this stock has been outperforming the S&P 500 over the last
    ~3 months, sell once it starts lagging. Bets that recent outperformance
    tends to persist for a while, rather than mean-revert."""
    lookback = 60

    def init(self):
        self.rel = self.I(_relative_strength, self.data.Close, self.data.Benchmark, self.lookback)

    def next(self):
        if not np.isnan(self.rel[-1]) and self.rel[-1] > 0 and not self.position:
            self.buy()
        elif not np.isnan(self.rel[-1]) and self.rel[-1] < 0 and self.position:
            self.position.close()


# ============================================================================
# "Current status" functions -- given a strategy instance right after
# bt.run() finishes (still holding its final indicator readings and
# position), return "what would this rule tell me to do right now."
#
# Two shapes, on purpose: "price" strategies (Bollinger, breakout) have a
# trigger that already IS a literal price level, so that price is shown
# directly. The others (RSI, MACD, moving averages, relative strength)
# trigger off a computed indicator reading, not a raw price -- showing an
# exact "target price" for those would mean algebraically inverting each
# indicator's formula (solvable, but real per-indicator math with its own
# edge cases); showing "current reading vs. its threshold" instead is
# honest, simpler, and answers the same practical question ("how close is
# this to firing"). dashboard/generate_dashboard.py formats the sentence;
# these functions only return raw numbers.
# ============================================================================

def _rsi_status(instance, oversold, overbought):
    rsi_now = float(instance.rsi[-1])
    holding = bool(instance.position)
    return {
        "holding": holding,
        "next_action": "sell" if holding else "buy",
        "trigger_kind": "reading",
        "trigger_label": "RSI overbought threshold" if holding else "RSI oversold threshold",
        "trigger_value": overbought if holding else oversold,
        "current_label": "Current RSI",
        "current_value": rsi_now,
        "unit": "",
        "direction": "above" if holding else "below",
    }


def _rsi_mean_reversion_status(instance):
    return _rsi_status(instance, instance.oversold, instance.overbought)


def _macd_crossover_status(instance):
    holding = bool(instance.position)
    return {
        "holding": holding,
        "next_action": "sell" if holding else "buy",
        "trigger_kind": "reading",
        "trigger_label": "Signal line",
        "trigger_value": float(instance.signal[-1]),
        "current_label": "Current MACD",
        "current_value": float(instance.macd[-1]),
        "unit": "",
        "direction": "below" if holding else "above",
    }


def _ma_crossover_status(instance):
    holding = bool(instance.position)
    return {
        "holding": holding,
        "next_action": "sell" if holding else "buy",
        "trigger_kind": "reading",
        "trigger_label": "200-day average",
        "trigger_value": float(instance.slow[-1]),
        "current_label": "Current 50-day average",
        "current_value": float(instance.fast[-1]),
        "unit": "$",
        "direction": "below" if holding else "above",
    }


def _bollinger_status(instance):
    holding = bool(instance.position)
    price_now = float(instance.data.Close[-1])
    return {
        "holding": holding,
        "next_action": "sell" if holding else "buy",
        "trigger_kind": "price",
        "trigger_label": "Upper Bollinger Band" if holding else "Lower Bollinger Band",
        "trigger_value": float(instance.upper[-1]) if holding else float(instance.lower[-1]),
        "current_label": "Current price",
        "current_value": price_now,
        "unit": "$",
        "direction": "above" if holding else "below",
    }


def _breakout_status(instance):
    holding = bool(instance.position)
    price_now = float(instance.data.Close[-1])
    return {
        "holding": holding,
        "next_action": "sell" if holding else "buy",
        "trigger_kind": "price",
        "trigger_label": "20-day low" if holding else "20-day high",
        "trigger_value": float(instance.lower[-1]) if holding else float(instance.upper[-1]),
        "current_label": "Current price",
        "current_value": price_now,
        "unit": "$",
        "direction": "below" if holding else "above",
    }


def _trend_filtered_dip_status(instance):
    """This rule's buy condition is compound (RSI oversold AND price above
    its own 200-day average) -- unlike plain RsiMeanReversion, showing only
    the RSI half can be actively misleading (RSI can look like it should
    fire while the trend filter is the real, silent blocker). When not
    holding and the trend filter is what's actually blocking a buy, say so
    explicitly rather than implying RSI alone controls the trigger."""
    status = _rsi_status(instance, instance.oversold, instance.overbought)
    if not status["holding"]:
        price_now = float(instance.data.Close[-1])
        trend_ma_now = float(instance.trend_ma[-1])
        if trend_ma_now == trend_ma_now and price_now <= trend_ma_now:  # NaN-safe
            status["extra_note"] = (
                f"Also requires the price (currently ${price_now:.2f}) to be above its "
                f"200-day average (currently ${trend_ma_now:.2f}) -- not the case right now, "
                f"so this won't buy even if RSI drops further."
            )
    return status


def _relative_strength_status(instance):
    holding = bool(instance.position)
    return {
        "holding": holding,
        "next_action": "sell" if holding else "buy",
        "trigger_kind": "reading",
        "trigger_label": "Break-even vs. the S&P 500",
        "trigger_value": 0.0,
        "current_label": "Current 3-month outperformance",
        "current_value": float(instance.rel[-1]) * 100,
        "unit": "%",
        "direction": "below" if holding else "above",
    }


# ============================================================================
# Registry -- metadata + the Strategy class to run, in the order they should
# be displayed. backtest/engine.py iterates this list; dashboard rendering
# uses "name"/"category"/"explanation" as-is.
# ============================================================================

STRATEGIES = [
    {
        "key": "rsi_mean_reversion",
        "name": "RSI Mean-Reversion",
        "category": "Mean-reversion",
        "explanation": "Buys when the stock looks oversold (RSI below 30 — "
                        "it fell a lot recently), sells once it recovers "
                        "to a stronger reading (RSI above 70). Bets that "
                        "sharp short-term drops tend to bounce back.",
        "strategy_class": RsiMeanReversion,
        "needs_benchmark": False,
        "status_fn": _rsi_mean_reversion_status,
    },
    {
        "key": "macd_crossover",
        "name": "MACD Crossover",
        "category": "Trend-following",
        "explanation": "Buys when short-term momentum turns upward (the "
                        "MACD line crosses above its own signal line), "
                        "sells when it crosses back below. Bets that a "
                        "new upward trend, once started, keeps going for a while.",
        "strategy_class": MacdCrossover,
        "needs_benchmark": False,
        "status_fn": _macd_crossover_status,
    },
    {
        "key": "moving_average_crossover",
        "name": "Moving-Average Crossover (Golden/Death Cross)",
        "category": "Trend-following",
        "explanation": "Buys when the 50-day average price crosses above "
                        "the 200-day average (a classic \"new uptrend\" "
                        "signal), sells when it crosses back below.",
        "strategy_class": MovingAverageCrossover,
        "needs_benchmark": False,
        "status_fn": _ma_crossover_status,
    },
    {
        "key": "bollinger_band_reversion",
        "name": "Bollinger Band Reversion",
        "category": "Mean-reversion",
        "explanation": "Buys when the price dips below its own typical "
                        "trading range (statistically \"too cheap\" given "
                        "its recent volatility), sells once it pops back "
                        "above the top of that range.",
        "strategy_class": BollingerBandReversion,
        "needs_benchmark": False,
        "status_fn": _bollinger_status,
    },
    {
        "key": "breakout_channel",
        "name": "20-Day Breakout",
        "category": "Trend-following",
        "explanation": "Buys when the price breaks out to a new 20-day "
                        "high, sells on a new 20-day low. Bets that "
                        "breakouts continue rather than reverse — the "
                        "opposite belief from the mean-reversion rules above.",
        "strategy_class": BreakoutChannel,
        "needs_benchmark": False,
        "status_fn": _breakout_status,
    },
    {
        "key": "trend_filtered_dip",
        "name": "Trend-Filtered Dip Buy",
        "category": "Combined",
        "explanation": "\"Buy the dip, but only in an uptrend\": the same "
                        "oversold RSI entry as the mean-reversion rule, but "
                        "only while the price is still above its own "
                        "200-day average.",
        "strategy_class": TrendFilteredDip,
        "needs_benchmark": False,
        "status_fn": _trend_filtered_dip_status,
    },
    {
        "key": "relative_strength",
        "name": "Relative Strength vs. S&P 500",
        "category": "Trend-following",
        "explanation": "Buys when this stock has been beating the S&P 500 "
                        "over the last ~3 months, sells once it starts "
                        "lagging. Bets that recent outperformance tends to "
                        "persist for a while.",
        "strategy_class": RelativeStrength,
        "needs_benchmark": True,
        "status_fn": _relative_strength_status,
    },
]
