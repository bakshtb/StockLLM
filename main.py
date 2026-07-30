#!/usr/bin/env python3
"""
StockLLM CLI -- v1

Usage:
    python main.py check AAPL              # full run: data + 4-agent LLM pipeline
    python main.py check AAPL --dry-run     # data fetch only, no LLM calls, no API key needed

This runs the deterministic data fetch (price, news, fundamentals), then the
4-agent LLM pipeline (bull / bear / skeptic / judge), and prints a final
recommendation to the terminal.

This is a research/decision-support tool. It is NOT financial advice, and it
does not place trades. Backtested or live performance is not guaranteed.
"""

import sys
import json
import argparse

from config import ANTHROPIC_API_KEY, MONTHLY_SPEND_LIMIT_USD
from data.bundle import build_research_bundle
from agents.pipeline import run_pipeline
from storage import db
from storage.db import get_monthly_spend


def print_dry_run(ticker: str, bundle: dict, output_path: str | None = None):
    print("\n" + "=" * 60)
    print(f"  {ticker} -- DRY RUN (raw data fetch only, no LLM calls made)")
    print("=" * 60)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2)
        print(f"  Bundle written to: {output_path}")
    else:
        print(json.dumps(bundle, indent=2))
    print("=" * 60)

    price = bundle.get("price", {})
    fundamentals = bundle.get("fundamentals", {})
    news = bundle.get("news_headlines", [])
    insider = bundle.get("insider_transactions", {})
    analyst_ratings = bundle.get("analyst_ratings", {})
    earnings_estimates = bundle.get("earnings_estimates", {})
    relative_performance = bundle.get("relative_performance", {})
    dividends_buybacks = bundle.get("dividends_buybacks", {})
    options_sentiment = bundle.get("options_sentiment", {})
    institutional = bundle.get("institutional_ownership", {})
    balance_sheet = bundle.get("balance_sheet_health", {})
    income_statement = bundle.get("income_statement", {})
    filings_raw = bundle.get("filings_raw", {})
    news_articles_raw = bundle.get("news_articles_raw", [])
    form144 = bundle.get("form144_notices", {})
    beneficial_ownership = bundle.get("beneficial_ownership", {})
    proxy_raw = bundle.get("proxy_raw", {})
    short_interest = fundamentals.get("short_interest", {})

    print(f"\n  Price + technicals populated : {'yes' if price.get('current_price') is not None else 'NO'}")
    print(f"  News headlines found          : {len(news)}")
    print(f"  Fundamentals populated        : {'yes' if fundamentals.get('pe_ratio') is not None else 'partial/no'}")
    print(f"  Short interest populated      : {'yes' if short_interest.get('shares_short') is not None else 'partial/no'}")
    print(f"  Balance sheet data populated  : {'yes' if balance_sheet.get('total_debt') is not None else 'partial/no'}")
    print(f"  Income statement populated    : {'yes' if income_statement.get('annual') is not None else 'partial/no'}")
    print(f"  Insider transactions found    : {len(insider.get('transactions', []))}")
    print(f"  Analyst rating actions found  : {len(analyst_ratings.get('actions', []))} (last {analyst_ratings.get('lookback_days', 60)}d)")
    print(f"  Earnings surprise history      : {len(earnings_estimates.get('earnings_surprise_history', []))} quarters")
    print(f"  Relative perf vs benchmark/sec : {'yes' if relative_performance.get('relative_vs_benchmark_1y_pct') is not None else 'partial/no'}")
    print(f"  Dividend/buyback data          : {'yes' if dividends_buybacks.get('dividend_yield_pct') is not None or dividends_buybacks.get('buybacks_recent_quarters') else 'none (non-payer)'}")
    print(f"  Options sentiment populated    : {'yes' if options_sentiment.get('put_call_volume_ratio') is not None else 'no -- ' + (options_sentiment.get('note') or 'no listed options')}")
    print(f"  Form 144 sale notices found   : {len(form144.get('notices', []))}")
    print(f"  Beneficial ownership (13D/G)  : {len(beneficial_ownership.get('filings', []))}")
    print(f"  Institutional holders found   : {len(institutional.get('top_institutional_holders', []))}")
    for filing_type in ["10-K", "10-Q", "8-K"]:
        f = filings_raw.get(filing_type, {})
        status = f"yes ({f.get('filing_date', '')})" if f.get("text") else "no -- " + (f.get("note") or "unknown reason")
        label = f"Raw {filing_type} fetched"
        print(f"  {label:<28}: {status}")
    print(f"  Raw proxy (DEF 14A) fetched   : {'yes (' + proxy_raw.get('filing_date', '') + ')' if proxy_raw.get('text') else 'no -- ' + (proxy_raw.get('note') or 'unknown reason')}")
    articles_with_text = sum(1 for a in news_articles_raw if a.get("full_text_fetched"))
    print(f"  Raw news articles fetched     : {articles_with_text}/{len(news_articles_raw)} full text (rest fell back to headline snippet)")
    print("  Filings digest / news digest  : skipped in dry run (LLM summarization step -- requires an API key + small cost)")

    if bundle.get("data_notes"):
        print("\n  Notes:")
        for n in bundle["data_notes"]:
            print(f"    - {n}")
    print()


def print_result(ticker: str, result: dict):
    judge = result["judge"]
    print("\n" + "=" * 60)
    print(f"  {ticker} -- StockLLM Analysis")
    print("=" * 60)
    print(f"  Recommendation : {judge.get('recommendation', 'unknown').upper()}")
    print(f"  Confidence     : {judge.get('confidence', '?')}/100")
    print("-" * 60)
    print("  Reasoning:")
    print(f"    {judge.get('reasoning_summary', '(none provided)')}")
    print("-" * 60)
    print("  Key risks:")
    for risk in judge.get("key_risks", []):
        print(f"    - {risk}")
    print("-" * 60)
    print(f"  Data quality note: {judge.get('data_quality_caveat', '(none provided)')}")
    print("-" * 60)
    print(f"  Run cost (data digests + reasoning pipeline): ${result['total_cost_usd']:.4f}  |  Run ID: {result['run_id']}")
    print("=" * 60)
    print("\n  Bull case summary: " + result["bull"].get("thesis", ""))
    print("  Bear case summary: " + result["bear"].get("thesis", ""))
    if result["skeptic"].get("unsupported_claims"):
        print("\n  Skeptic flagged unsupported claims:")
        for c in result["skeptic"]["unsupported_claims"]:
            print(f"    - {c}")
    print("\n  ⚠️  Not financial advice. This is a research tool -- verify independently.\n")


def main():
    parser = argparse.ArgumentParser(description="StockLLM -- multi-agent stock research CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Run the full analysis pipeline on a ticker")
    check_parser.add_argument("ticker", type=str, help="Stock ticker symbol, e.g. AAPL")
    check_parser.add_argument(
        "--dry-run", action="store_true",
        help="Only run the raw data-fetch layer (price/news/fundamentals/insider/institutional/balance "
             "sheet). No LLM calls at all (skips filings/news digest too), no API key required, no cost.",
    )
    check_parser.add_argument(
        "--output", "-o", type=str, default=None, metavar="PATH",
        help="With --dry-run, write the raw data bundle as JSON to this file path instead of "
             "printing it to the terminal (the summary lines still print).",
    )

    args = parser.parse_args()

    if args.command == "check":
        ticker = args.ticker.upper().strip()

        if args.dry_run:
            print(f"Fetching data for {ticker} (dry run, no LLM calls)...")
            try:
                bundle, _ = build_research_bundle(ticker, run_digests=False)
            except ValueError as e:
                print(f"ERROR: {e}")
                sys.exit(1)
            print_dry_run(ticker, bundle, output_path=args.output)
            return

        if not ANTHROPIC_API_KEY:
            print("ERROR: ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in.")
            print("(Tip: use --dry-run to test raw data fetching without an API key.)")
            sys.exit(1)

        db.init_db()

        spent = get_monthly_spend()
        if spent >= MONTHLY_SPEND_LIMIT_USD:
            print(f"ERROR: Monthly spend limit reached (${spent:.2f} / ${MONTHLY_SPEND_LIMIT_USD:.2f}).")
            print("Adjust MONTHLY_SPEND_LIMIT_USD in .env if you want to continue.")
            sys.exit(1)

        run_id = db.create_run(ticker)

        print(f"Fetching data for {ticker} (includes filings + news digest, small LLM cost)...")
        try:
            bundle, digest_calls = build_research_bundle(ticker, run_digests=True)
        except ValueError as e:
            db.finalize_run(run_id, "error", 0, 0.0, status="failed")
            print(f"ERROR: {e}")
            sys.exit(1)

        db.save_bundle(run_id, bundle)

        digest_cost = 0.0
        for dc in digest_calls:
            db.save_agent_output(
                run_id, dc["name"], "claude-haiku-4-5-20251001",
                dc["input_tokens"], dc["output_tokens"], 0, dc["cost_usd"], {},
            )
            digest_cost += dc["cost_usd"]

        print(f"Running 4-agent analysis pipeline for {ticker} (this calls the Anthropic API, costs a few more cents)...")
        try:
            result = run_pipeline(run_id, ticker, bundle, starting_cost_usd=digest_cost)
        except RuntimeError as e:
            print(f"ERROR: {e}")
            sys.exit(1)

        print_result(ticker, result)


if __name__ == "__main__":
    main()
