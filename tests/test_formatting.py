"""
Tests for dashboard/generate_dashboard.py's plain formatting helpers --
pure functions, no fixtures/mocking needed. Several of these cases are
real bugs found and fixed this session (see HANDOFF.md), written as tests
now so they can't silently come back.
"""

from dashboard.generate_dashboard import (
    fmt_compact,
    fmt_usd,
    fmt_price,
    fmt_pct,
    fmt_num,
    delta_class,
    rsi_class,
)


class TestFmtCompact:
    def test_none_is_em_dash(self):
        assert fmt_compact(None) == "—"

    def test_trillions(self):
        assert fmt_compact(5.04e12) == "5.04T"

    def test_billions(self):
        assert fmt_compact(392_000_000) == "392.00M"

    def test_small_integer_no_decimals(self):
        assert fmt_compact(42) == "42"

    def test_negative_value_keeps_sign(self):
        # fmt_usd (below) depends on this returning a value that STARTS
        # with "-" so it can move the sign before the "$" -- this is the
        # contract fmt_usd relies on, worth pinning explicitly.
        assert fmt_compact(-392_000_000).startswith("-")


class TestFmtUsd:
    def test_none_is_em_dash(self):
        assert fmt_usd(None) == "—"

    def test_positive_value(self):
        assert fmt_usd(392_000_000) == "$392.00M"

    def test_negative_value_sign_before_dollar(self):
        # Real bug (HANDOFF.md #25): this used to render "$-392.00M"
        # (sign landed after the currency symbol) instead of "-$392.00M".
        assert fmt_usd(-392_000_000) == "-$392.00M"

    def test_zero(self):
        assert fmt_usd(0) == "$0"


class TestFmtPrice:
    def test_none_is_em_dash(self):
        assert fmt_price(None) == "—"

    def test_formats_with_two_decimals_and_comma(self):
        assert fmt_price(1234.5) == "$1,234.50"


class TestFmtPct:
    def test_none_is_em_dash(self):
        assert fmt_pct(None) == "—"

    def test_positive_gets_plus_sign_by_default(self):
        assert fmt_pct(12.34) == "+12.3%"

    def test_negative_keeps_its_own_minus(self):
        assert fmt_pct(-12.34) == "-12.3%"

    def test_unsigned_mode_no_plus(self):
        assert fmt_pct(12.34, signed=False) == "12.3%"

    def test_custom_decimals(self):
        assert fmt_pct(12.345, decimals=2) == "+12.35%"


class TestFmtNum:
    def test_none_is_em_dash(self):
        assert fmt_num(None) == "—"

    def test_thousands_separator(self):
        assert fmt_num(1234567, decimals=0) == "1,234,567"

    def test_decimals(self):
        assert fmt_num(12.345, decimals=2) == "12.35"


class TestDeltaClass:
    def test_none_is_neutral(self):
        assert delta_class(None) == "neutral"

    def test_positive_is_good(self):
        assert delta_class(5) == "good"

    def test_negative_is_critical(self):
        assert delta_class(-5) == "critical"

    def test_zero_is_neutral(self):
        assert delta_class(0) == "neutral"

    def test_invert_flips_direction(self):
        # Used for e.g. VIX: a rising VIX (positive change) is "critical"
        # even though the raw number is positive, hence invert=True there.
        assert delta_class(5, invert=True) == "critical"
        assert delta_class(-5, invert=True) == "good"


class TestRsiClass:
    def test_none_returns_none(self):
        assert rsi_class(None) is None

    def test_below_30_is_good(self):
        assert rsi_class(29.9) == "good"
        assert rsi_class(0) == "good"

    def test_above_70_is_critical(self):
        assert rsi_class(70.1) == "critical"
        assert rsi_class(100) == "critical"

    def test_boundary_30_is_neutral_not_good(self):
        assert rsi_class(30) is None

    def test_boundary_70_is_neutral_not_critical(self):
        assert rsi_class(70) is None

    def test_middle_zone_is_neutral(self):
        assert rsi_class(50) is None
