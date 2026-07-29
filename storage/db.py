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
