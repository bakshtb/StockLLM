"""
Tests for storage/db.py against the temp_db fixture (a tmp SQLite file,
never the real repo DB). Covers schema creation and the CRUD round-trips
that every run of the full (non-dry-run) pipeline depends on, plus
get_monthly_spend's calendar-month scoping since that directly gates
whether a user is blocked from running by MONTHLY_SPEND_LIMIT_USD.
"""

import datetime as dt
import json

import pytest


class TestInitDb:
    def test_creates_all_tables(self, temp_db):
        conn = temp_db.get_connection()
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        conn.close()
        assert {"runs", "research_bundles", "agent_outputs", "outcomes"} <= tables

    def test_idempotent(self, temp_db):
        # init_db uses CREATE TABLE IF NOT EXISTS -- calling it twice must not raise.
        temp_db.init_db()


class TestCreateRun:
    def test_returns_incrementing_ids(self, temp_db):
        first = temp_db.create_run("AAPL")
        second = temp_db.create_run("MSFT")
        assert second == first + 1

    def test_default_status_is_pending(self, temp_db):
        run_id = temp_db.create_run("AAPL")
        conn = temp_db.get_connection()
        row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
        conn.close()
        assert row["status"] == "pending"


class TestSaveBundle:
    def test_round_trips_json(self, temp_db):
        run_id = temp_db.create_run("AAPL")
        bundle = {"ticker": "AAPL", "nested": {"a": [1, 2, 3]}}
        temp_db.save_bundle(run_id, bundle)

        conn = temp_db.get_connection()
        row = conn.execute("SELECT bundle_json FROM research_bundles WHERE run_id = ?", (run_id,)).fetchone()
        conn.close()
        assert json.loads(row["bundle_json"]) == bundle


class TestSaveAgentOutput:
    def test_round_trips_all_fields(self, temp_db):
        run_id = temp_db.create_run("AAPL")
        temp_db.save_agent_output(
            run_id, "bull", "claude-haiku-4-5-20251001",
            input_tokens=1000, output_tokens=200, cache_read_tokens=50,
            cost_usd=0.0123, raw_output={"thesis": "x"},
        )
        conn = temp_db.get_connection()
        row = conn.execute("SELECT * FROM agent_outputs WHERE run_id = ?", (run_id,)).fetchone()
        conn.close()
        assert row["agent_name"] == "bull"
        assert row["input_tokens"] == 1000
        assert row["cache_read_tokens"] == 50
        assert row["cost_usd"] == pytest.approx(0.0123)
        assert json.loads(row["raw_output_json"]) == {"thesis": "x"}


class TestFinalizeRun:
    def test_updates_run_fields(self, temp_db):
        run_id = temp_db.create_run("AAPL")
        temp_db.finalize_run(run_id, recommendation="buy", confidence=80, total_cost_usd=0.25)

        conn = temp_db.get_connection()
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        conn.close()
        assert row["final_recommendation"] == "buy"
        assert row["final_confidence"] == 80
        assert row["total_cost_usd"] == pytest.approx(0.25)
        assert row["status"] == "complete"

    def test_status_overridable(self, temp_db):
        run_id = temp_db.create_run("AAPL")
        temp_db.finalize_run(run_id, recommendation=None, confidence=None, total_cost_usd=0.1, status="failed")
        conn = temp_db.get_connection()
        row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
        conn.close()
        assert row["status"] == "failed"


class TestGetMonthlySpend:
    def test_no_runs_returns_zero(self, temp_db):
        assert temp_db.get_monthly_spend() == 0.0

    def test_sums_current_month_runs(self, temp_db):
        run_a = temp_db.create_run("AAPL")
        run_b = temp_db.create_run("MSFT")
        temp_db.finalize_run(run_a, "buy", 80, 1.50)
        temp_db.finalize_run(run_b, "hold", 50, 2.25)
        assert temp_db.get_monthly_spend() == pytest.approx(3.75)

    def test_excludes_runs_from_a_different_month(self, temp_db):
        conn = temp_db.get_connection()
        conn.execute(
            "INSERT INTO runs (ticker, created_at, total_cost_usd, status) VALUES (?, ?, ?, 'complete')",
            ("AAPL", "2020-01-15T00:00:00Z", 99.0),
        )
        conn.commit()
        conn.close()
        assert temp_db.get_monthly_spend() == 0.0

    def test_null_total_cost_treated_as_zero_not_null(self, temp_db):
        # a run that's still 'pending' has total_cost_usd = NULL; SUM() must
        # not let a single NULL row poison the whole aggregate.
        run_id = temp_db.create_run("AAPL")  # pending, total_cost_usd is NULL
        other = temp_db.create_run("MSFT")
        temp_db.finalize_run(other, "buy", 80, 5.0)
        assert temp_db.get_monthly_spend() == pytest.approx(5.0)
