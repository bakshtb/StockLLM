"""
Combines price/technicals, fundamentals (incl. short interest), analyst
rating actions, earnings surprise/estimate revisions, relative performance
vs. benchmark/sector (returns AND valuation), dividends/buybacks, options
sentiment, macro context (VIX/10Y yield, plus optional FRED inflation/
unemployment/fed funds/yield curve), social/crowd sentiment (StockTwits),
balance sheet health, income statement, insider transactions (Form 4), Form
144 sale notices, beneficial ownership (13D/13G), institutional ownership,
raw filing text (incl. 8-K earnings exhibits), raw proxy text, raw news
article text, optional FMP DCF valuation + PEG ratio, optional Finnhub
insider sentiment + analyst recommendation trend, a fixed set of well-known
technical-strategy backtests against the ticker's own price history, filings
digest, and news digest into a single structured "research bundle".
This bundle is the ONLY source of truth the LLM reasoning agents
(bull/bear/skeptic/judge) are allowed to reason from -- see
agents/prompts/*.md for the grounding instructions.

Two clearly separated stages:
  1. RAW DATA -- everything above except the two digests. All deterministic,
     free, no LLM calls. Runs in FULL every time, including --dry-run.
  2. DIGESTS -- filings_digest (Qwen) and news_digest (Gemini) summarize the
     raw filing text / raw article text above -- see config.MODEL_FILINGS_DIGEST
     and config.MODEL_NEWS_DIGEST. This is the only stage that costs money
     and requires GEMINI_API_KEY + QWEN_API_KEY. Controlled by run_digests;
     skipped entirely in --dry-run, but the raw material it would summarize
     is still present in the bundle either way. The filings digest reads a
     larger window of each filing than `filings_raw` below carries (see
     data/fetch_filings.py's `digest_text` field) -- that larger window
     never itself lands in the bundle, only its summary does.
"""

import datetime as dt

from config import MODEL_NEWS_DIGEST, MODEL_FILINGS_DIGEST

from data.fetch_prices import fetch_price_summary
from data.fetch_news import fetch_news_summary, fetch_news_articles_raw, summarize_news
from data.fetch_fundamentals import fetch_fundamentals
from data.fetch_analyst_ratings import fetch_analyst_ratings
from data.fetch_earnings_estimates import fetch_earnings_estimates
from data.fetch_relative_performance import fetch_relative_performance
from data.fetch_dividends_buybacks import fetch_dividends_buybacks
from data.fetch_options_sentiment import fetch_options_sentiment
from data.fetch_macro_context import fetch_macro_context
from data.fetch_social_sentiment import fetch_social_sentiment
from data.fetch_balance_sheet import fetch_balance_sheet_health
from data.fetch_income_statement import fetch_income_statement
from data.fetch_insider import fetch_insider_transactions
from data.fetch_institutional import fetch_institutional_ownership
from data.fetch_filings import fetch_filings_raw, summarize_filing
from data.fetch_form144 import fetch_form144_notices
from data.fetch_beneficial_ownership import fetch_beneficial_ownership
from data.fetch_proxy import fetch_proxy_raw
from data.fetch_fmp_valuation import fetch_fmp_valuation
from data.fetch_finnhub_signals import fetch_finnhub_signals
from backtest.engine import run_backtests


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
    analyst_ratings = fetch_analyst_ratings(ticker)
    earnings_estimates = fetch_earnings_estimates(ticker)
    relative_performance = fetch_relative_performance(
        ticker, fundamentals.get("sector"), price.get("pct_change_20d"), price.get("pct_change_1y"),
        fundamentals.get("pe_ratio"),
    )
    dividends_buybacks = fetch_dividends_buybacks(ticker)
    options_sentiment = fetch_options_sentiment(ticker, price.get("current_price"))
    macro_context = fetch_macro_context()
    social_sentiment = fetch_social_sentiment(ticker)
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
    fmp_valuation = fetch_fmp_valuation(ticker)  # DCF + PEG, optional (FMP_API_KEY)
    finnhub_signals = fetch_finnhub_signals(ticker)  # insider sentiment + rec trend, optional (FINNHUB_API_KEY)
    backtests = run_backtests(ticker)  # fixed well-known strategies vs. own price history, no LLM

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
                "model": filings_digest.get("model", MODEL_FILINGS_DIGEST),
            })

        news_digest = summarize_news(news_articles_raw)
        if news_digest.get("cost_usd"):
            digest_calls.append({
                "name": "news_digest", "cost_usd": news_digest["cost_usd"],
                "input_tokens": news_digest.get("input_tokens", 0),
                "output_tokens": news_digest.get("output_tokens", 0),
                "model": news_digest.get("model", MODEL_NEWS_DIGEST),
            })

    # filings_raw's `digest_text` field (a larger window, read only by
    # summarize_filing() above) never itself lands in the bundle -- only
    # `text` (the smaller window every reasoning agent sees) does. Stripped
    # here, after the digest call has already used it.
    filings_raw_for_bundle = {
        filing_type: {k: v for k, v in filing.items() if k != "digest_text"}
        for filing_type, filing in filings_raw.items()
    }

    bundle = {
        "ticker": ticker,
        "fetched_at": dt.datetime.utcnow().isoformat() + "Z",
        "price": price,
        "fundamentals": fundamentals,
        "analyst_ratings": analyst_ratings,  # individual firm actions (last ~60 days), no LLM
        "earnings_estimates": earnings_estimates,  # surprise history + EPS/revenue estimate trends, no LLM
        "relative_performance": relative_performance,  # stock return vs. SPY + sector ETF, no LLM
        "dividends_buybacks": dividends_buybacks,  # dividend yield/history + quarterly buyback spend, no LLM
        "options_sentiment": options_sentiment,  # put/call ratio + IV skew, no LLM
        "macro_context": macro_context,  # VIX + 10Y yield, same for every ticker on a given day, no LLM
        "social_sentiment": social_sentiment,  # StockTwits crowd bullish/bearish tags, no LLM
        "balance_sheet_health": balance_sheet,
        "income_statement": income_statement,
        "insider_transactions": insider,
        "institutional_ownership": institutional,
        "news_headlines": news_items,             # raw headline list kept for reference/citation
        "news_articles_raw": news_articles_raw,    # raw/full article text where fetchable, no LLM
        "filings_raw": filings_raw_for_bundle,      # raw text for latest 10-K, 10-Q, AND 8-K (incl. earnings exhibit), no LLM
        "form144_notices": form144,                # proposed insider sales (leading signal), no LLM
        "beneficial_ownership": beneficial_ownership,  # 13D/13G >5% stakes, active vs passive, no LLM
        "proxy_raw": proxy_raw,                    # raw DEF 14A text (comp/governance), no LLM
        "fmp_valuation": fmp_valuation,             # DCF fair value + PEG ratio, optional, no LLM
        "finnhub_signals": finnhub_signals,         # insider sentiment (MSPR) + analyst rec trend, optional, no LLM
        "backtests": backtests,                     # fixed well-known strategies vs. real price history, no LLM
        "news_digest": news_digest.get("digest"),
        "filings_digest": filings_digest.get("digest"),
        "data_notes": [
            n for n in [
                insider.get("note"), institutional.get("note"), analyst_ratings.get("note"),
                earnings_estimates.get("note"), relative_performance.get("note"),
                dividends_buybacks.get("note"), options_sentiment.get("note"), macro_context.get("note"),
                social_sentiment.get("note"), income_statement.get("note"),
                *[f.get("note") for f in filings_raw.values()],
                form144.get("note"), beneficial_ownership.get("note"), proxy_raw.get("note"),
                fmp_valuation.get("note"), finnhub_signals.get("note"), backtests.get("note"),
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
