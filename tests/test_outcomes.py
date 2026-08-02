"""
Tests for outcomes.py -- the track-record logger. Grading logic (_grade) is
tested directly since it's the part that decides whether a past call counts
as a win; update_pending_outcomes is tested against temp_db with
fetch_price_summary mocked (never hits real yfinance here -- see
tests/test_live_fetchers.py for that).
"""

import datetime as dt

import pytest

import outcomes as outcomes_module
from outcomes import _grade, generate_report, print_report, update_pending_outcomes


class TestGrade:
    def test_buy_wins_when_price_went_up(self):
        assert _grade("buy", 100, 110) == "WIN"

    def test_buy_loses_when_price_went_down(self):
        assert _grade("buy", 100, 90) == "LOSS"

    def test_buy_loses_when_price_unchanged(self):
        # no move at all doesn't vindicate a buy call
        assert _grade("buy", 100, 100) == "LOSS"

    def test_sell_wins_when_price_went_down(self):
        assert _grade("sell", 100, 90) == "WIN"

    def test_sell_loses_when_price_went_up(self):
        assert _grade("sell", 100, 110) == "LOSS"

    def test_hold_is_always_ok_not_win_or_loss(self):
        assert _grade("hold", 100, 150) == "OK"
        assert _grade("hold", 100, 50) == "OK"

    def test_insufficient_data_is_not_graded(self):
        assert _grade("insufficient_data", 100, 110) is None

    def test_unknown_recommendation_is_not_graded(self):
        assert _grade("unknown", 100, 110) is None

    def test_missing_price_at_run_is_not_graded(self):
        assert _grade("buy", None, 110) is None

    def test_missing_price_after_is_not_graded(self):
        assert _grade("buy", 100, None) is None

    def test_case_insensitive(self):
        assert _grade("BUY", 100, 110) == "WIN"


class TestUpdatePendingOutcomes:
    def test_does_nothing_for_runs_not_yet_due(self, temp_db, monkeypatch):
        run_id = temp_db.create_run("AAPL")
        temp_db.create_outcome(run_id, 180.0)  # created just now -- not 7 days old yet

        updated = update_pending_outcomes()
        assert updated == 0

    def test_fills_in_7d_price_once_due(self, temp_db, monkeypatch):
        conn = temp_db.get_connection()
        eight_days_ago = (dt.datetime.utcnow() - dt.timedelta(days=8)).isoformat() + "Z"
        conn.execute("INSERT INTO runs (ticker, created_at, status) VALUES ('AAPL', ?, 'complete')", (eight_days_ago,))
        run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        temp_db.create_outcome(run_id, 180.0)

        monkeypatch.setattr(outcomes_module, "fetch_price_summary", lambda ticker: {"current_price": 190.0})
        updated = update_pending_outcomes()
        assert updated == 1

        conn = temp_db.get_connection()
        row = conn.execute("SELECT price_after_7d, price_after_30d FROM outcomes WHERE run_id = ?", (run_id,)).fetchone()
        conn.close()
        assert row["price_after_7d"] == pytest.approx(190.0)
        assert row["price_after_30d"] is None  # only 8 days old, 30d not due yet

    def test_fills_in_both_7d_and_30d_when_both_due(self, temp_db, monkeypatch):
        conn = temp_db.get_connection()
        forty_days_ago = (dt.datetime.utcnow() - dt.timedelta(days=40)).isoformat() + "Z"
        conn.execute("INSERT INTO runs (ticker, created_at, status) VALUES ('AAPL', ?, 'complete')", (forty_days_ago,))
        run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        temp_db.create_outcome(run_id, 180.0)

        monkeypatch.setattr(outcomes_module, "fetch_price_summary", lambda ticker: {"current_price": 200.0})
        updated = update_pending_outcomes()
        assert updated == 2  # both 7d and 30d filled in this pass

        conn = temp_db.get_connection()
        row = conn.execute("SELECT price_after_7d, price_after_30d FROM outcomes WHERE run_id = ?", (run_id,)).fetchone()
        conn.close()
        assert row["price_after_7d"] == pytest.approx(200.0)
        assert row["price_after_30d"] == pytest.approx(200.0)

    def test_invalid_ticker_skipped_not_crashed_on(self, temp_db, monkeypatch):
        conn = temp_db.get_connection()
        eight_days_ago = (dt.datetime.utcnow() - dt.timedelta(days=8)).isoformat() + "Z"
        conn.execute("INSERT INTO runs (ticker, created_at, status) VALUES ('ZZZZ', ?, 'complete')", (eight_days_ago,))
        run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()
        temp_db.create_outcome(run_id, 180.0)

        def _raise(ticker):
            raise ValueError(f"No price history found for ticker '{ticker}'.")
        monkeypatch.setattr(outcomes_module, "fetch_price_summary", _raise)

        updated = update_pending_outcomes()  # must not raise
        assert updated == 0


class TestGenerateReportAndPrint:
    def test_empty_report(self, temp_db, monkeypatch):
        report = generate_report()
        assert report["rows"] == []
        assert report["summary"]["total_calls"] == 0
        assert report["summary"]["win_rate_30d"] is None

    def test_report_computes_win_rate_from_scored_calls_only(self, temp_db, monkeypatch):
        win_id = temp_db.create_run("AAPL")
        temp_db.finalize_run(win_id, "buy", 80, 0.3)
        temp_db.create_outcome(win_id, 100.0)
        temp_db.update_outcome_30d(win_id, 110.0)

        loss_id = temp_db.create_run("MSFT")
        temp_db.finalize_run(loss_id, "buy", 70, 0.3)
        temp_db.create_outcome(loss_id, 100.0)
        temp_db.update_outcome_30d(loss_id, 90.0)

        hold_id = temp_db.create_run("GOOGL")
        temp_db.finalize_run(hold_id, "hold", 60, 0.3)
        temp_db.create_outcome(hold_id, 100.0)
        temp_db.update_outcome_30d(hold_id, 105.0)  # OK, not scored as win/loss

        report = generate_report()
        assert report["summary"]["total_calls"] == 3
        assert report["summary"]["scored_30d_calls"] == 2  # hold excluded
        assert report["summary"]["win_rate_30d"] == pytest.approx(50.0)

    def test_print_report_handles_empty_without_crashing(self, temp_db, monkeypatch, capsys):
        print_report()
        captured = capsys.readouterr()
        assert "No tracked runs yet" in captured.out

    def test_print_report_handles_pending_prices_without_crashing(self, temp_db, monkeypatch, capsys):
        run_id = temp_db.create_run("AAPL")
        temp_db.finalize_run(run_id, "buy", 80, 0.3)
        temp_db.create_outcome(run_id, 180.0)  # price_after_30d still NULL

        print_report()
        captured = capsys.readouterr()
        assert "pending" in captured.out
        assert "AAPL" in captured.out
