"""
Deterministic macro-backdrop fetch. No LLM calls here.

Every other module in this bundle is ticker-specific; none of them tell the
agents anything about the market environment the ticker sits in. The same
P/E, RSI, or price move reads very differently in a risk-off, rising-rate
environment vs. a calm, low-rate one. Two free, well-known indices via
yfinance cover the essentials:
  - ^VIX: the market's near-term volatility/fear gauge.
  - ^TNX: the 10-year Treasury yield, a proxy for the risk-free rate that
    directly pressures high-multiple growth stock valuations when it rises.
    Historically CBOE quoted this scaled by 10 (46.22 -> 4.622%), but the
    yfinance feed returns the plain percent directly (verified live: 4.622,
    not 46.22) -- no rescaling here.

Not ticker-specific -- identical for every ticker checked on the same day,
by design.
"""

import yfinance as yf

VIX_TICKER = "^VIX"
TREASURY_10Y_TICKER = "^TNX"


def _level_and_change(index_ticker: str):
    hist = yf.Ticker(index_ticker).history(period="3mo")
    hist = hist[hist["Close"].notna()]
    if hist.empty:
        return None, None
    closes = hist["Close"]
    current = round(float(closes.iloc[-1]), 2)
    change_20d = round(float(closes.iloc[-1] - closes.iloc[-20]), 2) if len(closes) >= 20 else None
    return current, change_20d


def fetch_macro_context() -> dict:
    """
    Returns current VIX level and 10Y Treasury yield, each with their
    20-trading-day change. If either index is unreachable, that piece comes
    back null with a note rather than failing the whole fetch.
    """
    notes = []

    vix_level, vix_change_20d = None, None
    try:
        vix_level, vix_change_20d = _level_and_change(VIX_TICKER)
    except Exception:
        notes.append("VIX fetch failed.")

    yield_10y, yield_10y_change_20d = None, None
    try:
        yield_10y, yield_10y_change_20d = _level_and_change(TREASURY_10Y_TICKER)
    except Exception:
        notes.append("10Y Treasury yield fetch failed.")

    return {
        "vix_level": vix_level,
        "vix_change_20d": vix_change_20d,
        "treasury_10y_yield_pct": yield_10y,
        "treasury_10y_yield_change_20d_pct": yield_10y_change_20d,
        "note": " ".join(notes) if notes else None,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(fetch_macro_context(), indent=2))
