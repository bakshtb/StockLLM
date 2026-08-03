"""
Runs the fixed strategy list from backtest/strategies.py against a ticker's
own multi-year price history to see how each rule would actually have
performed -- deterministic, no LLM involved, same "Python computes, LLM
narrates" rule the rest of this codebase follows (see FinRobot's writeup in
research/01-llm-multi-agent-projects.md for why that split matters).

Never raises -- like every data/fetch_*.py module, a total failure (bad
ticker, no price history, network problem) returns an empty result with a
`note` explaining why, instead of blowing up the whole bundle build.
"""

import os

# backtesting.py's Backtest.run() prints a tqdm progress bar to stdout by
# default (once per strategy) -- fine interactively, but noisy/pointless on
# every CLI/webapp run where each backtest finishes in well under a second.
# Must be set before `backtesting` is imported below.
os.environ.setdefault("TQDM_DISABLE", "1")

import pandas as pd
import yfinance as yf
from backtesting import Backtest

from backtest.strategies import STRATEGIES, BENCHMARK_TICKER

# 6 years: enough runway for the slowest indicator here (a 200-day moving
# average) to warm up, plus several years of real signal history after that
# -- a single year would barely give the 200-day-MA strategies room to fire
# even once.
HISTORY_PERIOD = "6y"

STARTING_CASH = 10_000
COMMISSION = 0.001  # 0.1% per trade -- a realistic retail cost assumption,
                     # not frictionless, so results aren't overstated

MIN_TRADING_DAYS = 210  # a bit over 200 -- below this, the 200-day-MA
                         # strategies can never produce a single signal


def _fetch_history(ticker: str) -> pd.DataFrame:
    hist = yf.Ticker(ticker).history(period=HISTORY_PERIOD)
    hist = hist[hist["Close"].notna()]
    return hist[["Open", "High", "Low", "Close", "Volume"]]


def _clean_stat(value):
    """NaN-safe float rounding -- backtesting.py's stats Series legitimately
    contains NaN (e.g. Win Rate/Sharpe when a strategy made zero trades)."""
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN check without importing math for one thing
        return None
    return round(value, 2)


def _run_one(meta: dict, data: pd.DataFrame) -> dict:
    result = {
        "key": meta["key"],
        "name": meta["name"],
        "category": meta["category"],
        "explanation": meta["explanation"],
        "return_pct": None,
        "buy_hold_return_pct": None,
        "win_rate_pct": None,
        "num_trades": None,
        "max_drawdown_pct": None,
        "sharpe_ratio": None,
        "beat_buy_hold": None,
        "note": None,
    }
    try:
        bt = Backtest(
            data, meta["strategy_class"], cash=STARTING_CASH, commission=COMMISSION,
            exclusive_orders=True, finalize_trades=True,
        )
        stats = bt.run()
        num_trades = int(stats["# Trades"])
        result["num_trades"] = num_trades
        result["return_pct"] = _clean_stat(stats["Return [%]"])
        result["buy_hold_return_pct"] = _clean_stat(stats["Buy & Hold Return [%]"])
        result["max_drawdown_pct"] = _clean_stat(stats["Max. Drawdown [%]"])
        result["sharpe_ratio"] = _clean_stat(stats.get("Sharpe Ratio"))
        if num_trades > 0:
            result["win_rate_pct"] = _clean_stat(stats.get("Win Rate [%]"))
            if result["return_pct"] is not None and result["buy_hold_return_pct"] is not None:
                result["beat_buy_hold"] = result["return_pct"] > result["buy_hold_return_pct"]
        else:
            result["note"] = "This rule never actually triggered a trade over the tested period."
    except Exception as e:
        result["note"] = f"Could not run this strategy: {e}"
    return result


def run_backtests(ticker: str) -> dict:
    """
    Returns:
      {
        "years_tested": float | None,
        "history_start": str | None,
        "history_end": str | None,
        "strategies": [ {key, name, category, explanation, return_pct,
                          buy_hold_return_pct, win_rate_pct, num_trades,
                          max_drawdown_pct, sharpe_ratio, beat_buy_hold, note}, ... ],
        "note": str | None,
      }
    Every dollar/percent figure here comes straight from running real
    historical price data through backtesting.py -- nothing in this module
    is an LLM call or an opinion.
    """
    result = {
        "years_tested": None, "history_start": None, "history_end": None,
        "strategies": [], "note": None,
    }

    try:
        data = _fetch_history(ticker)
    except Exception:
        result["note"] = "Could not fetch price history for backtesting."
        return result

    if len(data) < MIN_TRADING_DAYS:
        result["note"] = (
            f"Only {len(data)} trading days of price history available -- "
            "too little for a meaningful backtest (needs at least about a "
            "year; several years is better)."
        )
        return result

    result["history_start"] = data.index[0].strftime("%Y-%m-%d")
    result["history_end"] = data.index[-1].strftime("%Y-%m-%d")
    result["years_tested"] = round(len(data) / 252, 1)  # ~252 trading days/year

    needs_benchmark = any(m.get("needs_benchmark") for m in STRATEGIES)
    benchmark_data = None
    benchmark_note = None
    if needs_benchmark:
        try:
            bench_hist = _fetch_history(BENCHMARK_TICKER)
            benchmark_data = data.join(
                bench_hist[["Close"]].rename(columns={"Close": "Benchmark"}), how="inner",
            )
        except Exception:
            benchmark_note = f"Could not fetch benchmark ({BENCHMARK_TICKER}) data for the relative-strength strategy."

    for meta in STRATEGIES:
        if meta.get("needs_benchmark"):
            if benchmark_data is None:
                result["strategies"].append({
                    "key": meta["key"], "name": meta["name"], "category": meta["category"],
                    "explanation": meta["explanation"], "return_pct": None,
                    "buy_hold_return_pct": None, "win_rate_pct": None, "num_trades": None,
                    "max_drawdown_pct": None, "sharpe_ratio": None, "beat_buy_hold": None,
                    "note": benchmark_note or "Benchmark data unavailable.",
                })
                continue
            result["strategies"].append(_run_one(meta, benchmark_data))
        else:
            result["strategies"].append(_run_one(meta, data))

    return result


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(run_backtests(ticker), indent=2))
