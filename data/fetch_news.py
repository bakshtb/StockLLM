"""
News fetch, split into stages:

  1. fetch_news_summary()  -- headlines + short snippets via yfinance/Finnhub.
     Deterministic, no LLM calls.
  2. fetch_news_articles_raw()  -- attempts to fetch full article text for the
     top headlines. Still no LLM calls -- this is "get all the data", and it
     runs in --dry-run too. Many fetches will fail (paywalls/blocking); that's
     expected and handled gracefully, falling back to the headline snippet.
  3. summarize_news()  -- takes the enriched article list and summarizes it
     with a cheap model (Haiku). This is the "shrink" stage -- costs a small
     amount, skipped in --dry-run.

fetch_news_digest() is a convenience wrapper that runs stages 2+3 back to
back, kept for standalone/CLI use.
"""

import datetime as dt
import requests
import yfinance as yf
from bs4 import BeautifulSoup

from config import FINNHUB_API_KEY, MAX_NEWS_ITEMS, MODEL_DIGEST, MAX_NEWS_ARTICLES_TO_FETCH
from agents.gemini_client import call_gemini_digest

NEWS_DIGEST_SYSTEM_PROMPT = (
    "You are a financial news summarizer. You will be given the headlines and, where "
    "available, full article text for several recent news items about a stock. "
    "Extract the key facts an equity analyst would care about across all of them -- "
    "do not just restate headlines, pull out concrete details (numbers, events, "
    "dates, statements from named sources). Do not add outside knowledge. If two "
    "articles cover the same event, merge into one point rather than repeating. "
    'Respond with ONLY valid JSON: {"key_facts": ["...", "..."]}'
)


def _from_yfinance(ticker: str) -> list[dict]:
    tk = yf.Ticker(ticker)
    items = []
    try:
        raw = tk.news or []
    except Exception:
        raw = []

    for item in raw:
        # yfinance news items are sometimes nested under "content"
        content = item.get("content", item)
        title = content.get("title") or item.get("title")
        if not title:
            continue
        pub = content.get("pubDate") or content.get("providerPublishTime") or ""
        source = (content.get("provider") or {}).get("displayName") if isinstance(content.get("provider"), dict) else content.get("publisher", "unknown")
        summary = content.get("summary") or content.get("description") or ""
        link = (content.get("canonicalUrl") or {}).get("url") if isinstance(content.get("canonicalUrl"), dict) else content.get("link")
        items.append({
            "headline": title,
            "source": source or "unknown",
            "date": str(pub)[:10] if pub else "",
            "snippet": (summary or "")[:200],
            "url": link,
        })
    return items


def _from_finnhub(ticker: str, days_back: int = 14) -> list[dict]:
    if not FINNHUB_API_KEY:
        return []
    today = dt.date.today()
    start = today - dt.timedelta(days=days_back)
    url = "https://finnhub.io/api/v1/company-news"
    params = {
        "symbol": ticker,
        "from": start.isoformat(),
        "to": today.isoformat(),
        "token": FINNHUB_API_KEY,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        return []

    items = []
    for item in raw:
        headline = item.get("headline")
        if not headline:
            continue
        date = dt.datetime.utcfromtimestamp(item.get("datetime", 0)).strftime("%Y-%m-%d") if item.get("datetime") else ""
        items.append({
            "headline": headline,
            "source": item.get("source", "unknown"),
            "date": date,
            "snippet": (item.get("summary") or "")[:200],
            "url": item.get("url"),
        })
    return items


def fetch_news_summary(ticker: str, max_items: int = MAX_NEWS_ITEMS) -> list[dict]:
    """
    Returns a list of recent news items: headline, source, date, short snippet.
    Deduplicates by headline. Caps at max_items, most recent first where dates known.
    """
    items = _from_yfinance(ticker) + _from_finnhub(ticker)

    seen = set()
    deduped = []
    for item in items:
        key = item["headline"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    deduped.sort(key=lambda x: x.get("date") or "", reverse=True)
    return deduped[:max_items]



# Generic client-side error banners some sites render server-side as a <p>
# alongside (or instead of) the real article body -- e.g. a React error
# boundary's fallback text. Strip these rather than let them masquerade as
# real content, or count toward the "did we get full text" length check.
_ERROR_BOILERPLATE_PREFIXES = [
    "oops, something went wrong",
]

# Below this length, what we scraped is indistinguishable from a truncated
# teaser (observed live: several MT Newswires pages return ~100-130 chars
# that cut off mid-sentence, e.g. "...took note of the Federal Reserve's
# decisi" -- previously accepted as "full text fetched" at a 100-char
# threshold, which was too low to catch this).
_MIN_REAL_ARTICLE_CHARS = 300


def _fetch_article_text(url: str, max_chars: int = 4000) -> str | None:
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0 (StockLLM research tool)"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        paragraphs = soup.find_all("p")
        text = " ".join(p.get_text(strip=True) for p in paragraphs)

        for prefix in _ERROR_BOILERPLATE_PREFIXES:
            if text.lower().startswith(prefix):
                text = text[len(prefix):].strip()

        return text[:max_chars] if len(text) > _MIN_REAL_ARTICLE_CHARS else None
    except Exception:
        return None


def fetch_news_articles_raw(news_items: list[dict]) -> list[dict]:
    """
    Attempts to fetch full article text for the top news items (no LLM calls).
    Falls back to the headline snippet for items where fetching fails or that
    are beyond the fetch cap. This is the "get all the data" stage for news.
    """
    if not news_items:
        return []

    enriched = []
    for item in news_items[:MAX_NEWS_ARTICLES_TO_FETCH]:
        full_text = _fetch_article_text(item.get("url"))
        enriched.append({
            "headline": item["headline"],
            "source": item["source"],
            "date": item["date"],
            "text": full_text or item.get("snippet", ""),
            "full_text_fetched": full_text is not None,
        })

    # Remaining items beyond the fetch cap: headlines/snippets only
    for item in news_items[MAX_NEWS_ARTICLES_TO_FETCH:]:
        enriched.append({
            "headline": item["headline"],
            "source": item["source"],
            "date": item["date"],
            "text": item.get("snippet", ""),
            "full_text_fetched": False,
        })

    return enriched


def summarize_news(enriched: list[dict]) -> dict:
    """
    Takes the output of fetch_news_articles_raw() and summarizes it into a
    compact key-facts digest via a cheap model. This is the only LLM-calling
    function in this module.
    """
    if not enriched:
        return {"digest": None, "note": "No news items to digest.", "cost_usd": 0.0}

    combined_text = "\n\n".join(
        f"[{e['date']} | {e['source']}] {e['headline']}\n{e['text']}" for e in enriched
    )

    try:
        digest_result = call_gemini_digest(MODEL_DIGEST, NEWS_DIGEST_SYSTEM_PROMPT, combined_text)
        return {
            "digest": digest_result["parsed"],
            "cost_usd": digest_result["cost_usd"],
            "input_tokens": digest_result["input_tokens"],
            "output_tokens": digest_result["output_tokens"],
            "model": digest_result["model"],
            "articles_with_full_text": sum(1 for e in enriched if e["full_text_fetched"]),
            "note": None,
        }
    except Exception as e:
        return {"digest": None, "note": f"News digest failed: {e}", "cost_usd": 0.0}


def fetch_news_digest(ticker: str, news_items: list[dict]) -> dict:
    """Convenience wrapper: raw article fetch + summarize in one call. Standalone/CLI use."""
    enriched = fetch_news_articles_raw(news_items)
    return summarize_news(enriched)


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_news_summary(ticker), indent=2))
