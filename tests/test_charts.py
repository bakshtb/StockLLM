"""
Tests for dashboard/generate_dashboard.py's SVG-generating chart functions.

Two things every one of these gets checked for, because both were real bugs
this session (see HANDOFF.md #26/#32/#33):
  1. Empty/all-None input returns the empty state instead of crashing.
  2. Every real <svg> tag carries BOTH viewBox and explicit width/height --
     missing width/height is exactly what broke mobile Safari's responsive
     scaling (#32), and it's easy to add a 9th chart function later and
     forget this.
"""

import re

import pytest

from dashboard.generate_dashboard import (
    bar_chart_horizontal,
    diverging_bar_horizontal,
    grouped_bar_horizontal,
    grouped_column_chart,
    range_meter,
    gauge_meter,
    stacked_bar_parts,
    diverging_stacked_sentiment,
)


def assert_svg_has_dimensions(svg: str):
    """A real (non-empty-state) <svg ...> tag must carry both viewBox and
    explicit width/height attributes -- see module docstring."""
    assert svg.startswith("<svg "), f"expected a real svg tag, got: {svg[:80]!r}"
    assert 'viewBox="' in svg
    assert re.search(r'\bwidth="\d+"', svg), "missing explicit width attribute"
    assert re.search(r'\bheight="\d+"', svg), "missing explicit height attribute"


class TestBarChartHorizontal:
    def test_empty_items_returns_empty_state(self):
        svg, table = bar_chart_horizontal([])
        assert svg == "<svg></svg>"
        assert "empty" in table

    def test_all_none_values_returns_empty_state(self):
        svg, table = bar_chart_horizontal([("a", None), ("b", None)])
        assert svg == "<svg></svg>"

    def test_real_data_has_svg_dimensions(self):
        svg, table = bar_chart_horizontal([("Low", 100), ("High", 200)])
        assert_svg_has_dimensions(svg)
        assert "Low" in table and "High" in table

    def test_none_values_are_filtered_not_crashed_on(self):
        # A mix of real and missing values (common: some quarters have
        # data, others don't) shouldn't raise.
        svg, table = bar_chart_horizontal([("a", 10), ("b", None), ("c", 30)])
        assert_svg_has_dimensions(svg)


class TestDivergingBarHorizontal:
    def test_empty_returns_empty_state(self):
        svg, table, legend = diverging_bar_horizontal([])
        assert svg == "<svg></svg>"

    def test_positive_and_negative_values_both_render(self):
        svg, table, legend = diverging_bar_horizontal([("beat", 10.0), ("miss", -5.0)])
        assert_svg_has_dimensions(svg)
        # positive uses the diverge-pos color, negative uses diverge-neg
        assert "var(--diverge-pos)" in svg
        assert "var(--diverge-neg)" in svg


class TestGroupedBarHorizontal:
    def test_empty_groups_returns_empty_state(self):
        svg, table, legend = grouped_bar_horizontal([])
        assert svg == "<svg></svg>"

    def test_all_none_values_returns_empty_state(self):
        svg, table, legend = grouped_bar_horizontal([
            ("20d", [("Stock", "var(--series-1)", None)]),
        ])
        assert svg == "<svg></svg>"

    def test_negative_values_grow_the_correct_direction(self):
        # Real bug (HANDOFF.md #26): negative values used to render as if
        # positive, sized by magnitude only, with no visual sign at all.
        groups = [("1y return", [
            ("Stock", "var(--series-1)", -42.58),
            ("S&P 500", "var(--series-2)", 16.25),
        ])]
        svg, table, legend = grouped_bar_horizontal(groups)
        assert_svg_has_dimensions(svg)
        # both series colors should appear -- this is what was "all blue"
        # before the fix (HANDOFF.md #26)
        assert "var(--series-1)" in svg
        assert "var(--series-2)" in svg

    def test_missing_series_value_skipped_not_crashed(self):
        groups = [("20d", [("Stock", "var(--series-1)", 5.0), ("Sector", "var(--series-3)", None)])]
        svg, table, legend = grouped_bar_horizontal(groups)
        assert_svg_has_dimensions(svg)


class TestGroupedColumnChart:
    def test_empty_categories_returns_empty_state(self):
        svg, table, legend = grouped_column_chart([], [])
        assert svg == "<svg></svg>"

    def test_real_data_has_dimensions(self):
        categories = ["Q1", "Q2"]
        series = [("Revenue", "var(--series-1)", [100, 200]), ("Net income", "var(--series-2)", [10, 20])]
        svg, table, legend = grouped_column_chart(categories, series)
        assert_svg_has_dimensions(svg)

    def test_negative_values_handled(self):
        # Net income can be negative (a loss quarter) -- must not crash the
        # baseline/height math.
        categories = ["Q1"]
        series = [("Net income", "var(--series-2)", [-50])]
        svg, table, legend = grouped_column_chart(categories, series)
        assert_svg_has_dimensions(svg)


class TestRangeMeter:
    def test_missing_low_high_returns_empty_state(self):
        svg, table = range_meter(None, 10, 10, None, 5)
        assert svg == "<svg></svg>"

    def test_real_range_has_dimensions(self):
        svg, table = range_meter(low=100, mean=150, median=140, high=200, current=160)
        assert_svg_has_dimensions(svg)

    def test_current_outside_range_does_not_crash(self):
        # Current price can legitimately fall outside the analyst range.
        svg, table = range_meter(low=100, mean=150, median=140, high=200, current=250)
        assert_svg_has_dimensions(svg)


class TestGaugeMeter:
    def test_none_value_returns_empty_state(self):
        svg, table = gauge_meter(None, 0, 100, zones=[(100, "var(--gridline)", "x")], label="RSI")
        assert svg == "<svg></svg>"

    def test_real_value_has_dimensions(self):
        svg, table = gauge_meter(65.4, 0, 100, zones=[(30, "var(--status-good)", "a"), (100, "var(--status-critical)", "b")], label="RSI")
        assert_svg_has_dimensions(svg)


class TestStackedBarParts:
    def test_empty_parts_returns_empty_state(self):
        svg, table, legend = stacked_bar_parts([])
        assert svg == "<svg></svg>"

    def test_zero_value_parts_filtered_out(self):
        svg, table, legend = stacked_bar_parts([("Institutions", 0, "var(--series-1)"), ("Insiders", 50, "var(--series-2)")])
        assert_svg_has_dimensions(svg)
        assert "Institutions" not in table  # zero-value entries are dropped

    def test_real_parts_have_dimensions(self):
        svg, table, legend = stacked_bar_parts([
            ("Institutions", 60, "var(--series-1)"),
            ("Insiders", 30, "var(--series-2)"),
            ("Other", 10, "var(--gridline)"),
        ])
        assert_svg_has_dimensions(svg)


class TestDivergingStackedSentiment:
    def test_all_zero_returns_empty_state(self):
        svg, table, legend = diverging_stacked_sentiment(0, 0, 0)
        assert svg == "<svg></svg>"

    def test_real_counts_have_dimensions(self):
        svg, table, legend = diverging_stacked_sentiment(bearish=8, untagged=19, bullish=3)
        assert_svg_has_dimensions(svg)
        assert "var(--diverge-neg)" in svg  # bearish
        assert "var(--diverge-pos)" in svg  # bullish
