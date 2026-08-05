"""
Deterministic fundamentals fetch. No LLM calls here.
"""

import datetime as dt

import yfinance as yf

from data.fetch_shares_outstanding import fetch_true_shares_outstanding


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


def fetch_fundamentals(ticker: str, current_price: float | None = None) -> dict:
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

    # yfinance's marketCap/sharesOutstanding only ever reflect the
    # publicly-traded share class -- for a company with a separate,
    # never-traded control class (e.g. Mobileye: Intel holds 100% of
    # Class B), that silently understates true market cap by however much
    # that other class is worth. Confirmed for real on MBLY: yfinance's
    # own count was ~3.4x too low. Only overrides when a genuine
    # multi-class structure is found in the actual 10-Q/10-K balance
    # sheet (see fetch_shares_outstanding.py) AND the correction is
    # clearly meaningful (>10% higher), not just noise between two
    # slightly-different-dated data sources.
    market_cap_value = info.get("marketCap")
    shares_note = None
    yf_shares = info.get("sharesOutstanding")
    if current_price:
        shares_check = fetch_true_shares_outstanding(ticker)
        true_shares = shares_check.get("total_shares")
        if true_shares and (not yf_shares or true_shares > yf_shares * 1.1):
            market_cap_value = true_shares * current_price
            by_class_str = " + ".join(f"Class {k}: {v:,}" for k, v in sorted(shares_check["by_class"].items()))
            shares_note = (
                f"Market cap corrected for a multi-class share structure -- yfinance's own figure only "
                f"counts the publicly-traded class ({yf_shares:,} shares if reported); the actual "
                f"{shares_check['source_filing']} balance sheet shows {by_class_str} = "
                f"{true_shares:,} total shares, used here instead."
            )

    return {
        "company_name": info.get("longName") or info.get("shortName"),
        "website": info.get("website"),
        "pe_ratio": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "market_cap": _fmt_market_cap(market_cap_value),
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
        "note": shares_note,
    }


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_fundamentals(ticker), indent=2))
