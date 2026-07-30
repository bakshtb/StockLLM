"""
Deterministic analyst ratings fetch. No LLM calls here.

Pulls individual analyst-firm rating actions (upgrades/downgrades/initiations/
reiterations, each with a from/to grade and any price-target change) from
yfinance's `upgrades_downgrades` feed -- free, no API key. This is a
different, more granular signal than fundamentals.analyst_recommendation
(a single aggregated consensus + mean target): here each row is one named
firm's specific action on a specific date, which lets the agents reason
about recent sentiment shifts (e.g. "3 upgrades in the last 2 weeks") rather
than only a static snapshot.
"""

import datetime as dt

import yfinance as yf

LOOKBACK_DAYS = 60

_ACTION_LABELS = {
    "up": "upgrade",
    "down": "downgrade",
    "main": "maintained",
    "reit": "reiterated",
    "init": "initiated",
}


def fetch_analyst_ratings(ticker: str, lookback_days: int = LOOKBACK_DAYS) -> dict:
    """
    Returns recent individual analyst-firm actions (not just the aggregated
    consensus), limited to the last `lookback_days` days. If the feed is
    empty or unreachable, returns an empty list with a note rather than
    raising -- this is a nice-to-have signal, not a hard requirement.
    """
    try:
        tk = yf.Ticker(ticker)
        df = tk.upgrades_downgrades
        if df is None or df.empty:
            return {"actions": [], "lookback_days": lookback_days, "note": "No analyst upgrade/downgrade data available."}

        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=lookback_days)
        df = df.reset_index()  # GradeDate becomes a column instead of the index

        actions = []
        for _, row in df.iterrows():
            grade_date = row.get("GradeDate")
            if grade_date is None:
                continue
            grade_dt = grade_date.to_pydatetime()
            if grade_dt.tzinfo is None:
                grade_dt = grade_dt.replace(tzinfo=dt.timezone.utc)
            if grade_dt < cutoff:
                continue

            current_target = row.get("currentPriceTarget")
            prior_target = row.get("priorPriceTarget")
            action_code = row.get("Action")

            actions.append({
                "date": grade_date.date().isoformat(),
                "firm": row.get("Firm"),
                "action": _ACTION_LABELS.get(action_code, action_code),
                "from_grade": row.get("FromGrade") or None,
                "to_grade": row.get("ToGrade") or None,
                "price_target_action": row.get("priceTargetAction") or None,
                "current_price_target": current_target if current_target else None,
                "prior_price_target": prior_target if prior_target else None,
            })

        actions.sort(key=lambda a: a["date"], reverse=True)
        note = None if actions else f"No analyst actions in the last {lookback_days} days."
        return {"actions": actions, "lookback_days": lookback_days, "note": note}

    except Exception as e:
        return {"actions": [], "lookback_days": lookback_days, "note": f"Analyst ratings fetch failed: {e}"}


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_analyst_ratings(ticker), indent=2))
