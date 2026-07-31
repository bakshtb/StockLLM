"""
Tests for config.py: env-var overrides for OUTPUT_DIR/DB_PATH, and the
estimate_cost_usd arithmetic (including the cache-read discount, which
directly affects real $ figures shown in the dashboard and enforced against
MONTHLY_SPEND_LIMIT_USD).
"""

import importlib
import os

import pytest

import config


class TestEstimateCostUsd:
    def test_known_model_basic_cost(self):
        # claude-sonnet-5: $2/M input, $10/M output
        cost = config.estimate_cost_usd("claude-sonnet-5", input_tokens=1_000_000, output_tokens=0)
        assert cost == pytest.approx(2.00)

    def test_output_tokens_priced_separately(self):
        cost = config.estimate_cost_usd("claude-sonnet-5", input_tokens=0, output_tokens=1_000_000)
        assert cost == pytest.approx(10.00)

    def test_cache_read_tokens_get_discount(self):
        # cache_read_tokens are billed at 10% of the base input rate, and are
        # excluded from the "regular" input token count.
        cost = config.estimate_cost_usd(
            "claude-sonnet-5", input_tokens=1_000_000, output_tokens=0, cache_read_tokens=1_000_000,
        )
        assert cost == pytest.approx(2.00 * 0.10)

    def test_mixed_regular_and_cached_input(self):
        cost = config.estimate_cost_usd(
            "claude-sonnet-5", input_tokens=1_000_000, output_tokens=0, cache_read_tokens=400_000,
        )
        # 600k regular + 400k cached
        expected = (600_000 * 2.00 / 1_000_000) + (400_000 * 2.00 * 0.10 / 1_000_000)
        assert cost == pytest.approx(expected)

    def test_unknown_model_returns_zero(self):
        cost = config.estimate_cost_usd("not-a-real-model", input_tokens=1000, output_tokens=1000)
        assert cost == 0.0

    def test_zero_tokens_zero_cost(self):
        cost = config.estimate_cost_usd("claude-sonnet-5", input_tokens=0, output_tokens=0)
        assert cost == 0.0

    def test_result_rounded_to_six_decimals(self):
        cost = config.estimate_cost_usd("claude-haiku-4-5-20251001", input_tokens=1, output_tokens=1)
        assert cost == round(cost, 6)


class TestEnvVarOverrides:
    def test_output_dir_overridable_via_env(self, monkeypatch):
        monkeypatch.setenv("OUTPUT_DIR", "/tmp/custom_output")
        reloaded = importlib.reload(config)
        try:
            assert reloaded.OUTPUT_DIR == "/tmp/custom_output"
        finally:
            monkeypatch.delenv("OUTPUT_DIR", raising=False)
            importlib.reload(config)

    def test_db_path_overridable_via_env(self, monkeypatch):
        monkeypatch.setenv("DB_PATH", "/tmp/custom.db")
        reloaded = importlib.reload(config)
        try:
            assert reloaded.DB_PATH == "/tmp/custom.db"
        finally:
            monkeypatch.delenv("DB_PATH", raising=False)
            importlib.reload(config)

    def test_output_dir_defaults_to_output_folder_next_to_config(self, monkeypatch):
        monkeypatch.delenv("OUTPUT_DIR", raising=False)
        reloaded = importlib.reload(config)
        assert reloaded.OUTPUT_DIR.endswith(os.path.join("StockLLM", "output")) or reloaded.OUTPUT_DIR.endswith("output")
