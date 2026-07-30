"""
Deterministic social/crowd sentiment fetch. No LLM calls here.

Everything else in this bundle is professional/institutional in nature
(analyst ratings, SEC filings, fundamentals). StockTwits' public symbol
stream is a genuinely different perspective: retail trader sentiment, in
near-real-time, with an explicit self-reported Bullish/Bearish tag on a
meaningful fraction of posts. No auth required for read access; StockTwits'
documented public rate limit is 200 requests/hour/IP, far more than a
manually-run CLI needs.

This is unmoderated public chatter, not a vetted data source -- it's
included as a sentiment gauge (what retail is currently saying), not as a
source of factual claims. The agent prompts' "only use facts from the
bundle" rule still applies to the sentiment counts/ratio; individual message
bodies are included for color/citation, not as facts to reason from.
"""

import requests

STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
SAMPLE_MESSAGE_COUNT = 5
REQUEST_TIMEOUT = 15


def fetch_social_sentiment(ticker: str) -> dict:
    """
    Returns bullish/bearish tag counts (and ratio) from the most recent
    ~30 public StockTwits messages for this ticker, plus a few sample
    messages for color. Returns an empty result with a note on any failure
    (network, symbol not found, etc.) rather than raising -- this is a
    nice-to-have signal, not a hard requirement.
    """
    try:
        resp = requests.get(
            STOCKTWITS_URL.format(ticker=ticker),
            headers={"User-Agent": "StockLLM research tool (github.com/bakshtb/StockLLM)"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return {
                "message_count": 0, "bullish_count": 0, "bearish_count": 0,
                "untagged_count": 0, "bullish_pct_of_tagged": None,
                "sample_messages": [],
                "note": f"StockTwits returned status {resp.status_code} for '{ticker}'.",
            }
        data = resp.json()
    except Exception as e:
        return {
            "message_count": 0, "bullish_count": 0, "bearish_count": 0,
            "untagged_count": 0, "bullish_pct_of_tagged": None,
            "sample_messages": [], "note": f"Social sentiment fetch failed: {e}",
        }

    messages = data.get("messages", [])
    bullish_count = 0
    bearish_count = 0
    sample_messages = []

    for msg in messages:
        sentiment = (msg.get("entities") or {}).get("sentiment")
        tag = sentiment.get("basic") if sentiment else None
        if tag == "Bullish":
            bullish_count += 1
        elif tag == "Bearish":
            bearish_count += 1

        if len(sample_messages) < SAMPLE_MESSAGE_COUNT:
            sample_messages.append({
                "created_at": msg.get("created_at"),
                "body": msg.get("body"),
                "sentiment": tag,
            })

    tagged_total = bullish_count + bearish_count
    bullish_pct = round(bullish_count / tagged_total * 100, 1) if tagged_total else None

    return {
        "message_count": len(messages),
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "untagged_count": len(messages) - tagged_total,
        "bullish_pct_of_tagged": bullish_pct,
        "sample_messages": sample_messages,
        "note": None,
    }


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_social_sentiment(ticker), indent=2))
