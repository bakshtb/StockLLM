"""
Deterministic fundamentals fetch. No LLM calls here.
"""

import datetime as dt

import yfinance as yf


def _fmt_market_cap(value):
    if not value:
        return None
    if value >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    return str(value)


def _epoch_to_date(value):
    if not value:
        return None
    try:
        return dt.date.fromtimestamp(value).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def _pct_change(current, prior):
    if not current or not prior:
        return None
    return round((current / prior - 1) * 100, 2)


def fetch_fundamentals(ticker: str) -> dict:
    tk = yf.Ticker(ticker)
    try:
        info = tk.info or {}
    except Exception:
        info = {}

    next_earnings = None
    try:
        cal = tk.calendar
        if cal is not None:
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if ed:
                    next_earnings = str(ed[0]) if isinstance(ed, list) else str(ed)
            elif hasattr(cal, "empty") and not cal.empty:
                next_earnings = str(cal.iloc[0, 0])
    except Exception:
        pass

    return {
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "market_cap": _fmt_market_cap(info.get("marketCap")),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "next_earnings_date": next_earnings,
        "analyst_recommendation": info.get("recommendationKey"),
        "target_mean_price": info.get("targetMeanPrice"),
        "target_median_price": info.get("targetMedianPrice"),
        "target_high_price": info.get("targetHighPrice"),
        "target_low_price": info.get("targetLowPrice"),
        "number_of_analyst_opinions": info.get("numberOfAnalystOpinions"),
        "short_interest": {
            "shares_short": info.get("sharesShort"),
            "shares_short_prior_month": info.get("sharesShortPriorMonth"),
            "short_change_pct": _pct_change(info.get("sharesShort"), info.get("sharesShortPriorMonth")),
            "short_ratio_days_to_cover": info.get("shortRatio"),
            "short_pct_of_float": info.get("shortPercentOfFloat"),
            "as_of_date": _epoch_to_date(info.get("dateShortInterest")),
        },
    }


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_fundamentals(ticker), indent=2))
