"""
Deterministic fetch of two Finnhub signals not already covered elsewhere in
the bundle. No LLM calls here.

  - Insider Sentiment (MSPR -- Monthly Share Purchase Ratio): Finnhub's own
    aggregated "were insiders net buying or selling this month" score.
    Different from insider_transactions (raw individual Form 4 filings from
    SEC EDGAR) -- this is a summarized trend on top of that raw data, not a
    duplicate of it.
  - Recommendation Trends: monthly aggregate analyst buy/hold/sell counts
    over the last few months. Different from analyst_ratings (individual
    firm-level upgrade/downgrade actions from yfinance) -- this shows
    whether consensus opinion as a whole is improving or deteriorating over
    time, not who made which specific call.

Entirely optional (uses the same FINNHUB_API_KEY as fetch_news.py) -- if it's
not set, or Finnhub is unreachable, this comes back empty with a note rather
than breaking the bundle.
"""

import datetime as dt

import requests

from config import FINNHUB_API_KEY

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
REQUEST_TIMEOUT = 10
INSIDER_SENTIMENT_LOOKBACK_DAYS = 180


def fetch_finnhub_signals(ticker: str) -> dict:
    """
    Returns Finnhub's insider sentiment (MSPR) trend and recent analyst
    recommendation trend counts. Never raises -- these are valuable extras,
    not a hard requirement for the pipeline to run.
    """
    result = {
        "insider_sentiment_mspr": None, "insider_sentiment_trend": [],
        "recommendation_trend": [], "note": None,
    }

    if not FINNHUB_API_KEY:
        return result  # silently omitted, not an error -- this data source is optional

    notes = []

    try:
        today = dt.date.today()
        start = today - dt.timedelta(days=INSIDER_SENTIMENT_LOOKBACK_DAYS)
        resp = requests.get(
            f"{FINNHUB_BASE_URL}/stock/insider-sentiment",
            params={"symbol": ticker, "from": start.isoformat(), "to": today.isoformat(), "token": FINNHUB_API_KEY},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        trend = [
            {"year": d["year"], "month": d["month"], "mspr": round(float(d["mspr"]), 2)}
            for d in data if d.get("mspr") is not None
        ]
        trend.sort(key=lambda d: (d["year"], d["month"]))
        result["insider_sentiment_trend"] = trend
        result["insider_sentiment_mspr"] = trend[-1]["mspr"] if trend else None
    except Exception as e:
        notes.append(f"Finnhub insider sentiment fetch failed: {e}")

    try:
        resp = requests.get(
            f"{FINNHUB_BASE_URL}/stock/recommendation",
            params={"symbol": ticker, "token": FINNHUB_API_KEY},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json() or []
        result["recommendation_trend"] = [
            {
                "period": d.get("period"),
                "strong_buy": d.get("strongBuy"),
                "buy": d.get("buy"),
                "hold": d.get("hold"),
                "sell": d.get("sell"),
                "strong_sell": d.get("strongSell"),
            }
            for d in data
        ]
    except Exception as e:
        notes.append(f"Finnhub recommendation trend fetch failed: {e}")

    result["note"] = " ".join(notes) if notes else None
    return result


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_finnhub_signals(ticker), indent=2))
