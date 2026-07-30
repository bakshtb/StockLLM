"""
Deterministic dividend and buyback fetch. No LLM calls here.

Capital return to shareholders (dividends + share repurchases) is a distinct
signal from everything else in the bundle: a growing buyback program signals
management confidence and directly reduces share count (mechanically boosting
EPS); a cut or suspended dividend is a hard warning sign balance-sheet ratios
alone might not flag yet.

Note on units (a real yfinance quirk, not a bug in this module): `dividendYield`
and `fiveYearAvgDividendYield` come back from yfinance's `info` dict already
expressed as a plain percent number (e.g. 0.32 means 0.32%, not 32%), while
`payoutRatio` comes back as a fraction (0.1259 means 12.59%) and needs the
usual *100. Verified against AAPL's actual ~0.3% yield -- do not "fix" the
dividend yield fields by multiplying them, that would be wrong.
"""

import datetime as dt

import yfinance as yf

BUYBACK_QUARTERS = 4
DIVIDEND_HISTORY_COUNT = 4


def _epoch_to_date(value):
    if not value:
        return None
    try:
        return dt.date.fromtimestamp(value).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def fetch_dividends_buybacks(ticker: str) -> dict:
    """
    Returns dividend yield/payout/history and recent quarterly buyback
    spend. Non-dividend-paying / non-repurchasing companies simply get empty
    history lists here, which is a normal, expected result, not an error.
    """
    try:
        tk = yf.Ticker(ticker)
        info = tk.info or {}
    except Exception as e:
        return {
            "dividend_yield_pct": None, "payout_ratio_pct": None,
            "five_year_avg_dividend_yield_pct": None, "recent_dividend_history": [],
            "buybacks_recent_quarters": [], "note": f"Dividends/buybacks fetch failed: {e}",
        }

    payout_ratio = info.get("payoutRatio")

    recent_dividend_history = []
    try:
        divs = tk.dividends
        if divs is not None and not divs.empty:
            for date, amount in divs.tail(DIVIDEND_HISTORY_COUNT).items():
                recent_dividend_history.append({
                    "date": str(date.date()) if hasattr(date, "date") else str(date),
                    "amount": round(float(amount), 4),
                })
    except Exception:
        pass

    buybacks_recent_quarters = []
    note = None
    try:
        cf = tk.quarterly_cashflow
        if cf is not None and not cf.empty and "Repurchase Of Capital Stock" in cf.index:
            row = cf.loc["Repurchase Of Capital Stock"]
            for quarter_end, value in row.items():
                if value is None or (isinstance(value, float) and value != value):  # NaN check
                    continue
                buyback_usd = round(-float(value), 2) or 0.0  # `or 0.0` avoids a -0.0 artifact on near-zero values
                buybacks_recent_quarters.append({
                    "quarter_end": str(quarter_end.date()) if hasattr(quarter_end, "date") else str(quarter_end),
                    "buyback_usd": buyback_usd,  # cash flow reports this as a negative (outflow)
                })
            buybacks_recent_quarters = buybacks_recent_quarters[:BUYBACK_QUARTERS]
    except Exception:
        note = "Buyback data unavailable for this ticker."

    return {
        "dividend_yield_pct": info.get("dividendYield"),
        "payout_ratio_pct": round(payout_ratio * 100, 2) if payout_ratio is not None else None,
        "five_year_avg_dividend_yield_pct": info.get("fiveYearAvgDividendYield"),
        "recent_dividend_history": recent_dividend_history,
        "buybacks_recent_quarters": buybacks_recent_quarters,
        "note": note,
    }


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_dividends_buybacks(ticker), indent=2))
