"""
SQLite storage layer. One local file DB -- no server needed.
"""

import sqlite3
import json
import os
import datetime as dt

from config import DB_PATH

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


def create_run(ticker: str) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO runs (ticker, created_at, status) VALUES (?, ?, 'pending')",
        (ticker, dt.datetime.utcnow().isoformat() + "Z"),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()
    return run_id


def save_bundle(run_id: int, bundle: dict):
    conn = get_connection()
    conn.execute(
        "INSERT INTO research_bundles (run_id, bundle_json) VALUES (?, ?)",
        (run_id, json.dumps(bundle)),
    )
    conn.commit()
    conn.close()


def save_agent_output(run_id: int, agent_name: str, model_used: str,
                       input_tokens: int, output_tokens: int, cache_read_tokens: int,
                       cost_usd: float, raw_output: dict):
    conn = get_connection()
    conn.execute(
        """INSERT INTO agent_outputs
           (run_id, agent_name, model_used, input_tokens, output_tokens,
            cache_read_tokens, cost_usd, raw_output_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (run_id, agent_name, model_used, input_tokens, output_tokens,
         cache_read_tokens, cost_usd, json.dumps(raw_output),
         dt.datetime.utcnow().isoformat() + "Z"),
    )
    conn.commit()
    conn.close()


def finalize_run(run_id: int, recommendation: str, confidence: int, total_cost_usd: float, status: str = "complete"):
    conn = get_connection()
    conn.execute(
        "UPDATE runs SET final_recommendation = ?, final_confidence = ?, total_cost_usd = ?, status = ? WHERE id = ?",
        (recommendation, confidence, total_cost_usd, status, run_id),
    )
    conn.commit()
    conn.close()


def get_monthly_spend() -> float:
    """Sum of total_cost_usd for runs created in the current calendar month."""
    conn = get_connection()
    month_prefix = dt.datetime.utcnow().strftime("%Y-%m")
    row = conn.execute(
        "SELECT SUM(total_cost_usd) as total FROM runs WHERE created_at LIKE ?",
        (f"{month_prefix}%",),
    ).fetchone()
    conn.close()
    return row["total"] or 0.0


def create_outcome(run_id: int, price_at_run: float):
    """Called right after a full (non-dry-run) check completes -- records the
    price on the day of the call, so it can be compared against the price
    later. See outcomes.py for the 7d/30d follow-up and the track-record report."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO outcomes (run_id, price_at_run, checked_at) VALUES (?, ?, ?)",
        (run_id, price_at_run, dt.datetime.utcnow().isoformat() + "Z"),
    )
    conn.commit()
    conn.close()


def get_outcomes_pending_update() -> list[dict]:
    """Every outcome still missing its 7d or 30d price, with enough info
    (ticker, created_at) for the caller to decide in Python whether it's
    actually due yet -- deliberately not filtered by date in SQL, to avoid
    depending on SQLite's parsing of the ISO8601 strings created_at is stored in."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT o.run_id, r.ticker, r.created_at, o.price_at_run,
               o.price_after_7d, o.price_after_30d
        FROM outcomes o
        JOIN runs r ON r.id = o.run_id
        WHERE o.price_after_7d IS NULL OR o.price_after_30d IS NULL
    """).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_outcome_7d(run_id: int, price: float):
    conn = get_connection()
    conn.execute(
        "UPDATE outcomes SET price_after_7d = ?, checked_at = ? WHERE run_id = ?",
        (price, dt.datetime.utcnow().isoformat() + "Z", run_id),
    )
    conn.commit()
    conn.close()


def update_outcome_30d(run_id: int, price: float):
    conn = get_connection()
    conn.execute(
        "UPDATE outcomes SET price_after_30d = ?, checked_at = ? WHERE run_id = ?",
        (price, dt.datetime.utcnow().isoformat() + "Z", run_id),
    )
    conn.commit()
    conn.close()


def get_recommendation_history(ticker: str) -> list[dict]:
    """Every completed (status='complete') real run for this ticker,
    oldest first -- the dashboard's price chart plots these as markers at
    the price/date they were actually made (see dashboard/generate_
    dashboard.py's price_history_chart()). Deliberately status='complete'
    only: a dry run never calls create_run() at all (see main.py/webapp/
    app.py), and a 'pending'/'failed' row never got a real judge
    recommendation to plot. LEFT JOINs outcomes -- price_at_run can be
    NULL if create_outcome() wasn't reached (e.g. the process died between
    finalize_run() and create_outcome()); the caller decides whether to
    skip those rather than this function silently dropping the run."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT r.id AS run_id, r.created_at, r.final_recommendation, r.final_confidence,
               o.price_at_run
        FROM runs r
        LEFT JOIN outcomes o ON o.run_id = r.id
        WHERE r.ticker = ? AND r.status = 'complete'
        ORDER BY r.created_at ASC
    """, (ticker,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_outcomes_report_data() -> list[dict]:
    """Every tracked outcome joined with its run's ticker/recommendation/
    confidence, most recent first -- the raw material for the track-record report."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT r.ticker, r.created_at, r.final_recommendation, r.final_confidence,
               o.price_at_run, o.price_after_7d, o.price_after_30d
        FROM outcomes o
        JOIN runs r ON r.id = o.run_id
        ORDER BY r.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(row) for row in rows]
