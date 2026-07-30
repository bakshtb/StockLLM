"""
Deterministic earnings-surprise and analyst-estimate-revision fetch. No LLM
calls here.

Two distinct signals, both from yfinance, both free:
  - Earnings surprise history: actual vs. estimated EPS for the last several
    reported quarters. Shows whether the company has been beating or missing
    Street expectations recently -- a beat streak vs. a fresh miss changes
    how much weight a recommendation should put on forward guidance.
  - EPS/revenue estimate trend + revisions: how the *current* consensus
    estimate for this quarter/next quarter/this year/next year has moved
    over the last 7/30/60/90 days, and how many analysts revised up vs.
    down. This is a leading indicator distinct from `analyst_ratings`
    (which tracks rating/price-target actions) -- estimates can drift for
    weeks before any firm changes its official rating.
"""

import math

import yfinance as yf

_PERIOD_LABELS = {
    "0q": "current_quarter",
    "+1q": "next_quarter",
    "0y": "current_year",
    "+1y": "next_year",
}


def _clean(value):
    """NaN -> None, else plain float/int."""
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
    except TypeError:
        pass
    return value


def _df_to_period_dict(df, columns):
    """Converts a yfinance estimate/revision DataFrame (indexed by period code
    like '0q'/'+1q'/'0y'/'+1y') into {friendly_period_name: {col: value}}."""
    if df is None or df.empty:
        return {}
    result = {}
    for period_code, row in df.iterrows():
        label = _PERIOD_LABELS.get(period_code)
        if not label:
            continue
        result[label] = {col: _clean(row.get(col)) for col in columns if col in row}
    return result


def fetch_earnings_estimates(ticker: str) -> dict:
    """
    Returns recent earnings surprise history plus forward EPS/revenue
    estimate trends and revisions. If any individual piece is unavailable,
    that piece comes back empty rather than failing the whole fetch --
    coverage varies by ticker (small/foreign names often lack analyst
    estimate coverage entirely).
    """
    notes = []
    try:
        tk = yf.Ticker(ticker)
    except Exception as e:
        return {
            "earnings_surprise_history": [], "eps_estimate_trend": {},
            "eps_estimate_revisions": {}, "revenue_estimate": {},
            "note": f"Earnings estimates fetch failed: {e}",
        }

    earnings_surprise_history = []
    try:
        hist = tk.earnings_history
        if hist is not None and not hist.empty:
            for quarter_end, row in hist.iterrows():
                earnings_surprise_history.append({
                    "quarter_end": str(quarter_end.date()) if hasattr(quarter_end, "date") else str(quarter_end),
                    "eps_actual": _clean(row.get("epsActual")),
                    "eps_estimate": _clean(row.get("epsEstimate")),
                    "surprise_pct": round(_clean(row.get("surprisePercent")) * 100, 2) if _clean(row.get("surprisePercent")) is not None else None,
                })
    except Exception:
        notes.append("Earnings surprise history unavailable for this ticker.")

    eps_estimate_trend = {}
    try:
        eps_estimate_trend = _df_to_period_dict(
            tk.eps_trend, ["current", "7daysAgo", "30daysAgo", "60daysAgo", "90daysAgo"]
        )
    except Exception:
        notes.append("EPS estimate trend unavailable for this ticker.")

    eps_estimate_revisions = {}
    try:
        eps_estimate_revisions = _df_to_period_dict(
            tk.eps_revisions, ["upLast7days", "upLast30days", "downLast30days", "downLast7Days"]
        )
    except Exception:
        notes.append("EPS estimate revisions unavailable for this ticker.")

    revenue_estimate = {}
    try:
        rev_df = tk.revenue_estimate
        raw = _df_to_period_dict(rev_df, ["avg", "low", "high", "numberOfAnalysts", "yearAgoRevenue", "growth"])
        for period, vals in raw.items():
            revenue_estimate[period] = {
                "avg": vals.get("avg"),
                "low": vals.get("low"),
                "high": vals.get("high"),
                "num_analysts": vals.get("numberOfAnalysts"),
                "year_ago_revenue": vals.get("yearAgoRevenue"),
                "growth_pct": round(vals["growth"] * 100, 2) if vals.get("growth") is not None else None,
            }
    except Exception:
        notes.append("Revenue estimates unavailable for this ticker.")

    return {
        "earnings_surprise_history": earnings_surprise_history,
        "eps_estimate_trend": eps_estimate_trend,
        "eps_estimate_revisions": eps_estimate_revisions,
        "revenue_estimate": revenue_estimate,
        "note": " ".join(notes) if notes else None,
    }


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_earnings_estimates(ticker), indent=2))
