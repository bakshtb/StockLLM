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


class TestOutcomes:
    def test_create_outcome_round_trips(self, temp_db):
        run_id = temp_db.create_run("AAPL")
        temp_db.create_outcome(run_id, 180.0)

        conn = temp_db.get_connection()
        row = conn.execute("SELECT * FROM outcomes WHERE run_id = ?", (run_id,)).fetchone()
        conn.close()
        assert row["price_at_run"] == pytest.approx(180.0)
        assert row["price_after_7d"] is None
        assert row["price_after_30d"] is None

    def test_pending_update_includes_rows_missing_either_price(self, temp_db):
        run_a = temp_db.create_run("AAPL")
        temp_db.create_outcome(run_a, 180.0)
        run_b = temp_db.create_run("MSFT")
        temp_db.create_outcome(run_b, 400.0)
        temp_db.update_outcome_7d(run_b, 410.0)
        temp_db.update_outcome_30d(run_b, 420.0)

        pending = temp_db.get_outcomes_pending_update()
        pending_run_ids = {row["run_id"] for row in pending}
        assert run_a in pending_run_ids  # missing both
        assert run_b not in pending_run_ids  # both already filled in

    def test_pending_update_includes_ticker_and_created_at(self, temp_db):
        run_id = temp_db.create_run("AAPL")
        temp_db.create_outcome(run_id, 180.0)
        pending = temp_db.get_outcomes_pending_update()
        row = next(r for r in pending if r["run_id"] == run_id)
        assert row["ticker"] == "AAPL"
        assert row["created_at"]

    def test_update_outcome_7d_and_30d(self, temp_db):
        run_id = temp_db.create_run("AAPL")
        temp_db.create_outcome(run_id, 180.0)
        temp_db.update_outcome_7d(run_id, 185.0)
        temp_db.update_outcome_30d(run_id, 195.0)

        conn = temp_db.get_connection()
        row = conn.execute("SELECT * FROM outcomes WHERE run_id = ?", (run_id,)).fetchone()
        conn.close()
        assert row["price_after_7d"] == pytest.approx(185.0)
        assert row["price_after_30d"] == pytest.approx(195.0)

    def test_report_data_joins_run_fields(self, temp_db):
        run_id = temp_db.create_run("AAPL")
        temp_db.finalize_run(run_id, "buy", 80, 0.34)
        temp_db.create_outcome(run_id, 180.0)
        temp_db.update_outcome_30d(run_id, 195.0)

        rows = temp_db.get_outcomes_report_data()
        assert len(rows) == 1
        row = rows[0]
        assert row["ticker"] == "AAPL"
        assert row["final_recommendation"] == "buy"
        assert row["final_confidence"] == 80
        assert row["price_at_run"] == pytest.approx(180.0)
        assert row["price_after_30d"] == pytest.approx(195.0)

    def test_report_data_most_recent_first(self, temp_db):
        conn = temp_db.get_connection()
        conn.execute("INSERT INTO runs (ticker, created_at, status) VALUES ('AAPL', '2026-01-01T00:00:00Z', 'complete')")
        older_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO runs (ticker, created_at, status) VALUES ('MSFT', '2026-06-01T00:00:00Z', 'complete')")
        newer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        temp_db.create_outcome(older_id, 100.0)
        temp_db.create_outcome(newer_id, 400.0)

        rows = temp_db.get_outcomes_report_data()
        assert rows[0]["ticker"] == "MSFT"
        assert rows[1]["ticker"] == "AAPL"


class TestGetRecommendationHistory:
    def test_returns_completed_runs_oldest_first(self, temp_db):
        conn = temp_db.get_connection()
        conn.execute("INSERT INTO runs (ticker, created_at, status, final_recommendation, final_confidence) "
                     "VALUES ('AAPL', '2026-06-01T00:00:00Z', 'complete', 'sell', 60)")
        newer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("INSERT INTO runs (ticker, created_at, status, final_recommendation, final_confidence) "
                     "VALUES ('AAPL', '2026-01-01T00:00:00Z', 'complete', 'buy', 80)")
        older_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        temp_db.create_outcome(older_id, 180.0)
        temp_db.create_outcome(newer_id, 210.0)

        rows = temp_db.get_recommendation_history("AAPL")
        assert len(rows) == 2
        assert rows[0]["final_recommendation"] == "buy"
        assert rows[0]["price_at_run"] == pytest.approx(180.0)
        assert rows[1]["final_recommendation"] == "sell"
        assert rows[1]["price_at_run"] == pytest.approx(210.0)

    def test_excludes_dry_runs_and_other_tickers(self, temp_db):
        # A dry run never calls create_run() at all in the real app -- this
        # simulates the two DB-visible cases that must still be excluded:
        # a pending/failed row (never got a real judge recommendation) and
        # a different ticker.
        run_id = temp_db.create_run("AAPL")  # left at default status='pending'
        temp_db.create_run("MSFT")

        assert temp_db.get_recommendation_history("AAPL") == []
        assert temp_db.get_recommendation_history("MSFT") == []

    def test_missing_outcome_gives_null_price_not_dropped_row(self, temp_db):
        # LEFT JOIN, not INNER JOIN -- a run that never reached
        # create_outcome() must still appear (with price_at_run=None),
        # not silently vanish from the history.
        run_id = temp_db.create_run("AAPL")
        temp_db.finalize_run(run_id, "hold", 55, 0.1)

        rows = temp_db.get_recommendation_history("AAPL")
        assert len(rows) == 1
        assert rows[0]["price_at_run"] is None
