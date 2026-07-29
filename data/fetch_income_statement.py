"""
Deterministic income statement fetch. No LLM calls here.

Pulls revenue, margins, and earnings from the most recent annual filing plus
ALL available recent quarters (not just the latest one) -- a single
latest-quarter snapshot can silently skip over a one-off event (e.g. a
goodwill impairment) that landed in an intermediate quarter between the
latest annual figure and the latest quarterly figure. Also computes YoY
growth so the agents have the actual "did the business grow" numbers instead
of relying on the 10-Q digest alone.
"""

import yfinance as yf


def _row(df, row_names: list[str], col):
    if df is None or df.empty or col not in df.columns:
        return None
    for name in row_names:
        if name in df.index:
            val = df.loc[name, col]
            if val is not None and val == val:  # filters out NaN
                return float(val)
    return None


def _pct_growth(current, prior):
    if current is None or prior is None or prior == 0:
        return None
    return round((current / prior - 1) * 100, 2)


def _period_stats(df, col):
    revenue = _row(df, ["Total Revenue", "Operating Revenue"], col)
    gross_profit = _row(df, ["Gross Profit"], col)
    operating_income = _row(df, ["Operating Income"], col)
    net_income = _row(df, ["Net Income"], col)
    diluted_eps = _row(df, ["Diluted EPS"], col)

    return {
        "period_end": str(col.date()) if hasattr(col, "date") else str(col),
        "total_revenue": revenue,
        "gross_profit": gross_profit,
        "operating_income": operating_income,
        "net_income": net_income,
        "diluted_eps": diluted_eps,
        "gross_margin_pct": round(gross_profit / revenue * 100, 2) if gross_profit is not None and revenue else None,
        "operating_margin_pct": round(operating_income / revenue * 100, 2) if operating_income is not None and revenue else None,
        "net_margin_pct": round(net_income / revenue * 100, 2) if net_income is not None and revenue else None,
    }


def fetch_income_statement(ticker: str) -> dict:
    """
    Returns latest annual income statement figures (plus YoY growth) and a
    list of ALL available recent quarters (typically ~5), each with QoQ
    context, so nothing in between two snapshots is silently missed. Never
    raises -- this is a valuable extra, not a hard requirement for the
    pipeline to run.
    """
    try:
        tk = yf.Ticker(ticker)
        annual = tk.income_stmt
        quarterly = tk.quarterly_income_stmt
    except Exception as e:
        return {"annual": None, "quarterly": None, "note": f"Income statement fetch failed: {e}"}

    result = {"annual": None, "quarterly": None, "note": None}

    if annual is not None and not annual.empty and len(annual.columns) >= 1:
        latest_annual = _period_stats(annual, annual.columns[0])
        if len(annual.columns) >= 2:
            prior_annual = _period_stats(annual, annual.columns[1])
            latest_annual["revenue_growth_yoy_pct"] = _pct_growth(latest_annual["total_revenue"], prior_annual["total_revenue"])
            latest_annual["net_income_growth_yoy_pct"] = _pct_growth(latest_annual["net_income"], prior_annual["net_income"])
            latest_annual["eps_growth_yoy_pct"] = _pct_growth(latest_annual["diluted_eps"], prior_annual["diluted_eps"])
        result["annual"] = latest_annual

    if quarterly is not None and not quarterly.empty and len(quarterly.columns) >= 1:
        # quarterly.columns are sorted most-recent-first
        quarters = [_period_stats(quarterly, col) for col in quarterly.columns]

        for i, q in enumerate(quarters):
            prior_q = quarters[i + 1] if i + 1 < len(quarters) else None
            if prior_q:
                q["revenue_growth_qoq_pct"] = _pct_growth(q["total_revenue"], prior_q["total_revenue"])
                q["net_income_growth_qoq_pct"] = _pct_growth(q["net_income"], prior_q["net_income"])
            # same quarter one year ago is 4 columns back if we have that much history
            year_ago_q = quarters[i + 4] if i + 4 < len(quarters) else None
            if year_ago_q:
                q["revenue_growth_yoy_pct"] = _pct_growth(q["total_revenue"], year_ago_q["total_revenue"])
                q["net_income_growth_yoy_pct"] = _pct_growth(q["net_income"], year_ago_q["net_income"])
                q["eps_growth_yoy_pct"] = _pct_growth(q["diluted_eps"], year_ago_q["diluted_eps"])

        result["quarterly"] = quarters
        if len(quarters) < 5:
            result["note"] = "Not enough quarterly history for a same-quarter YoY comparison on the oldest quarters shown."

    return result


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_income_statement(ticker), indent=2))
