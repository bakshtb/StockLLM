"""
Deterministic price data fetch. No LLM calls here -- pure data, summarized down
to compact stats so we don't burn tokens shipping raw OHLCV rows to the agents.
"""

import yfinance as yf
import numpy as np
import pandas as pd


def _compute_rsi(closes: pd.Series, period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period).mean().iloc[-1]
    avg_loss = loss.rolling(window=period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi), 2)


def _compute_macd(closes: pd.Series):
    if len(closes) < 35:
        return None, None, None
    ema12 = closes.ewm(span=12, adjust=False).mean()
    ema26 = closes.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    return (
        round(float(macd_line.iloc[-1]), 3),
        round(float(signal_line.iloc[-1]), 3),
        round(float(histogram.iloc[-1]), 3),
    )


def fetch_price_summary(ticker: str) -> dict:
    """
    Returns a compact dict of current price + derived stats and technical
    indicators, using ~1 year of history for indicator stability.
    Raises ValueError if the ticker has no data (likely invalid symbol, or a
    network/API problem reaching Yahoo Finance).
    """
    try:
        tk = yf.Ticker(ticker)
        hist = tk.history(period="1y")
    except Exception as e:
        raise ValueError(
            f"Could not fetch price data for '{ticker}' -- this is usually either an "
            f"invalid ticker symbol or a temporary problem reaching Yahoo Finance. "
            f"Check your internet connection and the symbol, then try again. (Details: {e})"
        )

    if hist.empty:
        raise ValueError(f"No price history found for ticker '{ticker}'. Check the symbol is correct.")

    # yfinance sometimes includes a trailing row (most recent session) with
    # all-NaN OHLC data before that day's data has fully settled. Drop any
    # rows with a NaN close so stats aren't computed against missing data.
    hist = hist[hist["Close"].notna()]
    if hist.empty:
        raise ValueError(f"No usable price history found for ticker '{ticker}' (all rows had missing close data).")

    closes = hist["Close"]
    # `.history()`'s last daily bar can genuinely lag a live/most-recent
    # quote by up to a full session -- confirmed directly on a real ticker
    # (MBLY): history's last close was $7.94 while the live quote was
    # already $8.08. Prefer the live quote (fast_info, a lighter/faster
    # call than the full .info) when it's available; fall back to the
    # historical close only if fast_info is missing/broken for this ticker.
    current_price = round(float(closes.iloc[-1]), 2)
    try:
        live_price = tk.fast_info.get("lastPrice")
        if live_price:
            current_price = round(float(live_price), 2)
    except Exception:
        pass
    ma20 = round(float(closes.tail(20).mean()), 2) if len(closes) >= 20 else None
    ma50 = round(float(closes.tail(50).mean()), 2) if len(closes) >= 50 else None
    ma200 = round(float(closes.tail(200).mean()), 2) if len(closes) >= 200 else None

    daily_returns = closes.pct_change(fill_method=None).dropna()
    volatility_20d = round(float(daily_returns.tail(20).std()), 4) if len(daily_returns) >= 20 else None

    volumes = hist["Volume"]
    avg_volume_20d = int(volumes.tail(20).mean()) if len(volumes) >= 20 else None
    avg_volume_50d = int(volumes.tail(50).mean()) if len(volumes) >= 50 else None
    volume_trend = "increasing" if (
        avg_volume_20d and avg_volume_50d and avg_volume_20d > avg_volume_50d * 1.1
    ) else "decreasing" if (
        avg_volume_20d and avg_volume_50d and avg_volume_20d < avg_volume_50d * 0.9
    ) else "stable"

    macd, macd_signal, macd_histogram = _compute_macd(closes)

    # 52-week high/low over the full 1y window we now fetch
    return {
        "current_price": current_price,
        "ma20": ma20,
        "ma50": ma50,
        "ma200": ma200,
        "52w_high": round(float(closes.max()), 2),
        "52w_low": round(float(closes.min()), 2),
        "volatility_20d": volatility_20d,
        "volume_trend": volume_trend,
        "pct_change_20d": round(float((closes.iloc[-1] / closes.iloc[-20] - 1) * 100), 2) if len(closes) >= 20 else None,
        "pct_change_1y": round(float((closes.iloc[-1] / closes.iloc[0] - 1) * 100), 2) if len(closes) > 0 else None,
        "rsi_14": _compute_rsi(closes, 14),
        "macd": macd,
        "macd_signal": macd_signal,
        "macd_histogram": macd_histogram,
    }


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_price_summary(ticker), indent=2))
