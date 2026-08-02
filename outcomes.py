"""
Tracks whether StockLLM's own past recommendations were actually good calls.
Two pieces:

  1. update_pending_outcomes() -- for every full-run check that's now 7 or 30
     days old and doesn't have that price checked yet, fetch the current price
     and fill it in. Free -- one yfinance lookup per ticker, no LLM calls.
  2. generate_report() / print_report() -- turns the saved history into a
     simple win/loss table, so there's real evidence of whether the system's
     calls are good, instead of just a plausible-sounding narrative.

Run `python main.py performance` to update and print the report. See
storage/schema.sql's `outcomes` table and HANDOFF.md for the design.
"""

import datetime as dt

from data.fetch_prices import fetch_price_summary
from storage import db

SEVEN_DAYS = dt.timedelta(days=7)
THIRTY_DAYS = dt.timedelta(days=30)


def update_pending_outcomes() -> int:
    """Fetches a fresh price for every run that's due for its 7d or 30d
    check and doesn't have it yet. Returns how many price checks were filled in."""
    pending = db.get_outcomes_pending_update()
    now = dt.datetime.utcnow()
    updated = 0

    for row in pending:
        created_at = dt.datetime.fromisoformat(row["created_at"].rstrip("Z"))
        age = now - created_at

        needs_7d = row["price_after_7d"] is None and age >= SEVEN_DAYS
        needs_30d = row["price_after_30d"] is None and age >= THIRTY_DAYS
        if not needs_7d and not needs_30d:
            continue

        try:
            price = fetch_price_summary(row["ticker"])["current_price"]
        except ValueError:
            continue  # ticker temporarily unavailable -- try again next time

        if needs_7d:
            db.update_outcome_7d(row["run_id"], price)
            updated += 1
        if needs_30d:
            db.update_outcome_30d(row["run_id"], price)
            updated += 1

    return updated


def _grade(recommendation: str, price_at_run, price_after) -> str | None:
    """Returns "WIN"/"LOSS"/"OK", or None if this call isn't scored -- hold is
    directionless by design, and insufficient_data made no call to grade."""
    if price_at_run is None or price_after is None:
        return None
    recommendation = (recommendation or "").lower()
    if recommendation == "buy":
        return "WIN" if price_after > price_at_run else "LOSS"
    if recommendation == "sell":
        return "WIN" if price_after < price_at_run else "LOSS"
    if recommendation == "hold":
        return "OK"
    return None


def generate_report() -> dict:
    """Returns {"rows": [...], "summary": {...}} -- rows are per-run detail
    for the table, summary is the aggregate honest bottom line."""
    raw_rows = db.get_outcomes_report_data()
    rows = []
    for r in raw_rows:
        rows.append({
            "ticker": r["ticker"],
            "date": r["created_at"][:10],
            "recommendation": r["final_recommendation"],
            "confidence": r["final_confidence"],
            "price_at_run": r["price_at_run"],
            "price_after_7d": r["price_after_7d"],
            "price_after_30d": r["price_after_30d"],
            "result_7d": _grade(r["final_recommendation"], r["price_at_run"], r["price_after_7d"]),
            "result_30d": _grade(r["final_recommendation"], r["price_at_run"], r["price_after_30d"]),
        })

    scored_30d = [r for r in rows if r["result_30d"] in ("WIN", "LOSS")]
    wins_30d = sum(1 for r in scored_30d if r["result_30d"] == "WIN")
    confidences = [r["confidence"] for r in rows if r["confidence"] is not None]

    summary = {
        "total_calls": len(rows),
        "scored_30d_calls": len(scored_30d),
        "win_rate_30d": round(wins_30d / len(scored_30d) * 100, 1) if scored_30d else None,
        "average_confidence": round(sum(confidences) / len(confidences), 1) if confidences else None,
    }
    return {"rows": rows, "summary": summary}


def print_report():
    report = generate_report()
    rows, summary = report["rows"], report["summary"]

    if not rows:
        print("No tracked runs yet. Run `python main.py check TICKER` (without --dry-run) "
              "to start building a track record.")
        return

    print("\n" + "=" * 100)
    print("  StockLLM -- Track Record")
    print("=" * 100)
    print(f"{'Ticker':<8}{'Date':<12}{'Called':<10}{'Conf':<6}{'Price then':<13}{'Price (30d)':<14}{'Change':<10}{'Result'}")
    print("-" * 100)
    for r in rows:
        conf_str = f"{r['confidence']}%" if r["confidence"] is not None else "?"
        price_then_str = f"${r['price_at_run']:.2f}" if r["price_at_run"] is not None else "?"
        if r["price_at_run"] and r["price_after_30d"]:
            change_30d = (r["price_after_30d"] / r["price_at_run"] - 1) * 100
            price_30d_str = f"${r['price_after_30d']:.2f}"
            change_str = f"{change_30d:+.1f}%"
        else:
            price_30d_str = "pending"
            change_str = "pending"
        print(
            f"{r['ticker']:<8}{r['date']:<12}{(r['recommendation'] or '?').upper():<10}"
            f"{conf_str:<6}{price_then_str:<13}{price_30d_str:<14}{change_str:<10}{r['result_30d'] or '-'}"
        )
    print("-" * 100)
    print(f"  Total tracked calls: {summary['total_calls']}")
    if summary["win_rate_30d"] is not None:
        print(f"  30-day win rate (buy/sell calls only): {summary['win_rate_30d']}% "
              f"({summary['scored_30d_calls']} scored calls)")
    else:
        print("  30-day win rate: not enough scored calls yet (need buy/sell calls at least 30 days old)")
    if summary["average_confidence"] is not None:
        print(f"  Average stated confidence: {summary['average_confidence']}%")
    print("=" * 100 + "\n")
