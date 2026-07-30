"""
Deterministic relative-performance fetch. No LLM calls here.

A stock's own pct_change_20d/pct_change_1y (see fetch_prices.py) says nothing
about whether that move was exceptional or just the whole market/sector
moving together -- e.g. "+63% in a year" reads very differently if the S&P
500 was flat vs. up 40% over the same stretch. This module fetches the same
two windows for a broad-market benchmark (SPY) and, where the ticker's sector
maps to a SPDR sector ETF, that sector ETF too, then reports the stock's
return minus each benchmark's return ("relative_vs_*_pct").

Takes the stock's own pct_change_20d/pct_change_1y as arguments (already
computed by fetch_prices.py) rather than re-deriving them here, to avoid a
second divergent implementation of the same calculation.
"""

import yfinance as yf

BENCHMARK_TICKER = "SPY"

# yfinance's `sector` field (see fetch_fundamentals.py) uses these exact
# strings for US equities; mapped to the standard SPDR sector ETFs.
SECTOR_ETF_MAP = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Energy": "XLE",
    "Healthcare": "XLV",
    "Consumer Defensive": "XLP",
    "Consumer Cyclical": "XLY",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Basic Materials": "XLB",
    "Industrials": "XLI",
    "Communication Services": "XLC",
}


def _pct_changes(etf_ticker: str):
    hist = yf.Ticker(etf_ticker).history(period="1y")
    hist = hist[hist["Close"].notna()]
    if hist.empty:
        return None, None
    closes = hist["Close"]
    pct_20d = round(float((closes.iloc[-1] / closes.iloc[-20] - 1) * 100), 2) if len(closes) >= 20 else None
    pct_1y = round(float((closes.iloc[-1] / closes.iloc[0] - 1) * 100), 2) if len(closes) > 0 else None
    return pct_20d, pct_1y


def fetch_relative_performance(ticker: str, sector: str, stock_pct_change_20d, stock_pct_change_1y) -> dict:
    """
    Returns the stock's 20d/1y return alongside SPY's and (if the sector maps
    to a known SPDR ETF) that sector ETF's return, plus the stock's return
    minus each. Returns whatever pieces succeed; a benchmark fetch failure
    doesn't block the others.
    """
    result = {
        "benchmark": BENCHMARK_TICKER,
        "sector_etf": SECTOR_ETF_MAP.get(sector),
        "stock_pct_change_20d": stock_pct_change_20d,
        "stock_pct_change_1y": stock_pct_change_1y,
        "benchmark_pct_change_20d": None,
        "benchmark_pct_change_1y": None,
        "relative_vs_benchmark_20d_pct": None,
        "relative_vs_benchmark_1y_pct": None,
        "sector_pct_change_20d": None,
        "sector_pct_change_1y": None,
        "relative_vs_sector_20d_pct": None,
        "relative_vs_sector_1y_pct": None,
        "note": None,
    }
    notes = []

    try:
        bench_20d, bench_1y = _pct_changes(BENCHMARK_TICKER)
        result["benchmark_pct_change_20d"] = bench_20d
        result["benchmark_pct_change_1y"] = bench_1y
        if stock_pct_change_20d is not None and bench_20d is not None:
            result["relative_vs_benchmark_20d_pct"] = round(stock_pct_change_20d - bench_20d, 2)
        if stock_pct_change_1y is not None and bench_1y is not None:
            result["relative_vs_benchmark_1y_pct"] = round(stock_pct_change_1y - bench_1y, 2)
    except Exception:
        notes.append(f"Could not fetch benchmark ({BENCHMARK_TICKER}) performance.")

    sector_etf = SECTOR_ETF_MAP.get(sector)
    if sector_etf:
        try:
            sect_20d, sect_1y = _pct_changes(sector_etf)
            result["sector_pct_change_20d"] = sect_20d
            result["sector_pct_change_1y"] = sect_1y
            if stock_pct_change_20d is not None and sect_20d is not None:
                result["relative_vs_sector_20d_pct"] = round(stock_pct_change_20d - sect_20d, 2)
            if stock_pct_change_1y is not None and sect_1y is not None:
                result["relative_vs_sector_1y_pct"] = round(stock_pct_change_1y - sect_1y, 2)
        except Exception:
            notes.append(f"Could not fetch sector ETF ({sector_etf}) performance.")
    else:
        notes.append(f"No SPDR sector ETF mapping for sector '{sector}'.")

    result["note"] = " ".join(notes) if notes else None
    return result


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    from data.fetch_prices import fetch_price_summary
    from data.fetch_fundamentals import fetch_fundamentals
    price = fetch_price_summary(ticker)
    fundamentals = fetch_fundamentals(ticker)
    print(json.dumps(
        fetch_relative_performance(ticker, fundamentals.get("sector"), price.get("pct_change_20d"), price.get("pct_change_1y")),
        indent=2,
    ))
