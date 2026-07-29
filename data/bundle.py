"""
Combines price/technicals, fundamentals (incl. short interest), balance sheet
health, income statement, insider transactions (Form 4), Form 144 sale
notices, beneficial ownership (13D/13G), institutional ownership, raw filing
text (incl. 8-K earnings exhibits), raw proxy text, raw news article text,
filings digest, and news digest into a single structured "research bundle".
This bundle is the ONLY source of truth the LLM reasoning agents
(bull/bear/skeptic/judge) are allowed to reason from -- see
agents/prompts/*.md for the grounding instructions.

Two clearly separated stages:
  1. RAW DATA -- everything above except the two digests. All deterministic,
     free, no LLM calls. Runs in FULL every time, including --dry-run.
  2. DIGESTS -- filings_digest and news_digest summarize the raw filing text
     / raw article text above via a cheap model. This is the only stage that
     costs money and requires ANTHROPIC_API_KEY. Controlled by run_digests;
     skipped entirely in --dry-run, but the raw material it would summarize
     is still present in the bundle either way.
"""

import datetime as dt

from data.fetch_prices import fetch_price_summary
from data.fetch_news import fetch_news_summary, fetch_news_articles_raw, summarize_news
from data.fetch_fundamentals import fetch_fundamentals
from data.fetch_balance_sheet import fetch_balance_sheet_health
from data.fetch_income_statement import fetch_income_statement
from data.fetch_insider import fetch_insider_transactions
from data.fetch_institutional import fetch_institutional_ownership
from data.fetch_filings import fetch_filings_raw, summarize_filing
from data.fetch_form144 import fetch_form144_notices
from data.fetch_beneficial_ownership import fetch_beneficial_ownership
from data.fetch_proxy import fetch_proxy_raw


def build_research_bundle(ticker: str, run_digests: bool = True) -> tuple[dict, list[dict]]:
    """
    Returns (bundle, digest_calls) where digest_calls is a list of dicts with
    keys: name, cost_usd, input_tokens, output_tokens -- for cost logging by
    the caller. Empty list if run_digests=False.
    """
    ticker = ticker.upper().strip()
    digest_calls = []

    # --- Stage 1: raw data, always runs, no LLM calls ---
    price = fetch_price_summary(ticker)  # raises ValueError if ticker invalid -- do this first, fail fast
    fundamentals = fetch_fundamentals(ticker)
    balance_sheet = fetch_balance_sheet_health(ticker)
    income_statement = fetch_income_statement(ticker)
    insider = fetch_insider_transactions(ticker)
    institutional = fetch_institutional_ownership(ticker)
    news_items = fetch_news_summary(ticker)
    filings_raw = fetch_filings_raw(ticker)
    news_articles_raw = fetch_news_articles_raw(news_items)
    form144 = fetch_form144_notices(ticker)
    beneficial_ownership = fetch_beneficial_ownership(ticker)
    proxy_raw = fetch_proxy_raw(ticker)

    # --- Stage 2: digests, only when run_digests=True (costs money, needs API key) ---
    filings_digest = {"digest": None, "note": "Skipped (dry run)."}
    news_digest = {"digest": None, "note": "Skipped (dry run)."}

    if run_digests:
        filings_digest = summarize_filing(filings_raw)
        if filings_digest.get("cost_usd"):
            digest_calls.append({
                "name": "filings_digest", "cost_usd": filings_digest["cost_usd"],
                "input_tokens": filings_digest.get("input_tokens", 0),
                "output_tokens": filings_digest.get("output_tokens", 0),
            })

        news_digest = summarize_news(news_articles_raw)
        if news_digest.get("cost_usd"):
            digest_calls.append({
                "name": "news_digest", "cost_usd": news_digest["cost_usd"],
                "input_tokens": 0, "output_tokens": 0,
            })

    bundle = {
        "ticker": ticker,
        "fetched_at": dt.datetime.utcnow().isoformat() + "Z",
        "price": price,
        "fundamentals": fundamentals,
        "balance_sheet_health": balance_sheet,
        "income_statement": income_statement,
        "insider_transactions": insider,
        "institutional_ownership": institutional,
        "news_headlines": news_items,             # raw headline list kept for reference/citation
        "news_articles_raw": news_articles_raw,    # raw/full article text where fetchable, no LLM
        "filings_raw": filings_raw,                # raw text for latest 10-K, 10-Q, AND 8-K (incl. earnings exhibit), no LLM
        "form144_notices": form144,                # proposed insider sales (leading signal), no LLM
        "beneficial_ownership": beneficial_ownership,  # 13D/13G >5% stakes, active vs passive, no LLM
        "proxy_raw": proxy_raw,                    # raw DEF 14A text (comp/governance), no LLM
        "news_digest": news_digest.get("digest"),
        "filings_digest": filings_digest.get("digest"),
        "data_notes": [
            n for n in [
                insider.get("note"), institutional.get("note"),
                income_statement.get("note"),
                *[f.get("note") for f in filings_raw.values()],
                form144.get("note"), beneficial_ownership.get("note"), proxy_raw.get("note"),
                filings_digest.get("note"), news_digest.get("note"),
            ] if n
        ],
    }

    return bundle, digest_calls


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    dry = "--dry-run" in sys.argv
    bundle, digest_calls = build_research_bundle(ticker, run_digests=not dry)
    print(json.dumps(bundle, indent=2))
    if digest_calls:
        print("\nDigest call costs:", json.dumps(digest_calls, indent=2))
