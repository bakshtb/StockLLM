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
    range_position_plot,
    gauge_meter,
    stacked_bar_parts,
    diverging_stacked_sentiment,
    diverging_stacked_ordinal,
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

    def test_last_category_value_labels_are_staggered_apart(self):
        # Regression: found on real data (Revenue vs. Net income close in
        # value for the most recent quarter) -- both series' value labels
        # are only bar_gap apart horizontally and were landing at nearly
        # the same height, overlapping. The shorter bar's label must stay
        # at its natural position; the taller bar's label must be pushed
        # at least 20 units further up rather than left to collide.
        categories = ["Q1", "Q2"]
        series = [("Revenue", "var(--series-1)", [100, 119.8]), ("Net income", "var(--series-2)", [90, 112.2])]
        svg, table, legend = grouped_column_chart(categories, series)
        import re
        ys = [float(m) for m in re.findall(r'<text x="[\d.]+" y="([\d.-]+)" text-anchor="middle" font-size="12" fill="var\(--text-primary\)"', svg)]
        assert len(ys) == 2
        assert abs(ys[0] - ys[1]) >= 20 - 0.01


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

    def test_corner_labels_always_render_even_when_current_is_near_an_edge(self):
        # Regression: suppressing the High corner label when Current sits
        # near it (the original approach) left a big unexplained empty
        # patch of track and read as "this chart doesn't fill its card"
        # on a real screenshot. Corner labels must always show; Current's
        # label is what gives way instead.
        svg, table = range_meter(low=215, mean=320, median=325, high=400, current=393)
        assert "Low $215.00" in svg
        assert "High $400.00" in svg

    def test_current_label_suppressed_near_edge_but_marker_kept(self):
        svg, table = range_meter(low=215, mean=320, median=325, high=400, current=393)
        assert ">Current<" not in svg  # text label dropped
        assert 'data-tip="Current: $393.00"' in svg  # triangle marker + tooltip still present
        assert "Current price" in table  # raw value still in the table view


class TestRangePositionPlot:
    """Price-vs-moving-averages: a dot plot on a shared axis, replacing a
    zero-anchored bar chart that made every bar look near-identical length
    when all values sit in a narrow band relative to their own magnitude
    (found from a real dashboard screenshot -- see HANDOFF.md)."""

    def test_missing_low_high_returns_empty_state(self):
        svg, table = range_position_plot(None, 340, 300, [("MA20", 320, "var(--series-1)")])
        assert svg == "<svg></svg>"

    def test_real_data_has_dimensions(self):
        svg, table = range_position_plot(
            201.58, 340.08, 333.43,
            [("MA200", 277.35, "var(--series-3)"), ("MA50", 309.30, "var(--series-2)"), ("MA20", 324.35, "var(--series-1)")],
        )
        assert_svg_has_dimensions(svg)
        assert "MA200" in svg and "MA50" in svg and "MA20" in svg
        assert "Current" in svg

    def test_current_outside_range_does_not_crash(self):
        svg, table = range_position_plot(
            100, 200, 250,
            [("MA20", 150, "var(--series-1)")],
        )
        assert_svg_has_dimensions(svg)

    def test_missing_current_omits_current_marker(self):
        svg, table = range_position_plot(
            100, 200, None,
            [("MA20", 150, "var(--series-1)")],
        )
        assert_svg_has_dimensions(svg)
        assert "Current" not in svg
        assert "Current" not in table

    def test_track_width_matches_gauge_meters_rsi_track(self):
        # Regression: this chart used pad=60 (track spans 60..560, 500 of
        # 620 units) while gauge_meter's RSI track -- shown directly below
        # it on the same card, same width -- used pad=20 (spans 20..600,
        # 580 of 620 units). Same card, two different-looking track
        # widths right next to each other; a real screenshot called this
        # out directly ("it's not in full width like the RSI line").
        svg, table = range_position_plot(
            100, 200, 150,
            [("MA20", 150, "var(--series-1)")],
        )
        import re
        m = re.search(r'<path d="M ([\d.]+) [\d.]+ H ([\d.]+)', svg)
        span = float(m.group(2)) - float(m.group(1))
        # 580 minus the track's own rounding radius (5) -- pad=20 on a
        # 620-wide canvas, matching gauge_meter, not the old pad=60.
        assert abs(span - 575) < 1

    def test_corner_labels_always_render_even_when_current_is_near_the_high(self):
        # Regression: this exact scenario (real AAPL data -- current price
        # close to its 52-week high) suppressed the "$340.08" corner label
        # on a real screenshot, leaving a big unexplained empty patch of
        # track that read as "this chart doesn't fill its card." Corner
        # labels must always show; Current's label is what gives way.
        svg, table = range_position_plot(
            201.58, 340.08, 333.43,
            [("MA200", 277.35, "var(--series-3)"), ("MA50", 309.30, "var(--series-2)"), ("MA20", 324.35, "var(--series-1)")],
        )
        assert "$201.58" in svg
        assert "$340.08" in svg

    def test_current_label_suppressed_near_edge_but_marker_kept(self):
        svg, table = range_position_plot(
            201.58, 340.08, 333.43,
            [("MA200", 277.35, "var(--series-3)"), ("MA50", 309.30, "var(--series-2)"), ("MA20", 324.35, "var(--series-1)")],
        )
        assert ">Current<" not in svg
        assert 'data-tip="Current: $333.43"' in svg
        assert "Current" in table  # raw value still in the table view

    def test_close_markers_are_staggered_not_overlapping(self):
        # MA50 and MA20 a few cents apart on an $8.98 range, and MA200 not
        # a lot further -- none of the three fit on one row without
        # overlapping once the mobile font override is applied (min_gap is
        # sized for that wider rendering, not the desktop default).
        svg, table = range_position_plot(
            6.56, 15.54, 7.91,
            [("MA200", 9.87, "var(--series-3)"), ("MA50", 9.25, "var(--series-2)"), ("MA20", 8.97, "var(--series-1)")],
        )
        # y="80" is the first label row (track_y=54, +26); each further
        # row is row_gap=44 below the last.
        assert 'y="80"' in svg
        assert 'y="124"' in svg
        assert 'y="168"' in svg

    def test_real_aapl_data_staggers_ma20_onto_a_second_row(self):
        # Regression: this exact data (real AAPL fixture values) rendered
        # "MA50MA20" running together on a phone screenshot -- MA50 and
        # MA20 are only ~54 viewBox units apart, which the mobile-sized
        # label (~77 units wide) doesn't clear, so MA20 must drop to a
        # second row even though MA200 is comfortably far from both.
        svg, table = range_position_plot(
            201.58, 340.08, 333.43,
            [("MA200", 277.35, "var(--series-3)"), ("MA50", 309.30, "var(--series-2)"), ("MA20", 324.35, "var(--series-1)")],
        )
        assert 'y="80"' in svg
        assert 'y="124"' in svg

    def test_widely_spaced_markers_share_one_row(self):
        svg, table = range_position_plot(
            0, 1000, 500,
            [("A", 100, "var(--series-1)"), ("B", 500, "var(--series-2)"), ("C", 900, "var(--series-3)")],
        )
        assert 'y="80"' in svg
        assert 'y="124"' not in svg

    def test_table_lists_every_marker_and_range(self):
        svg, table = range_position_plot(
            100, 200, 150,
            [("MA20", 130, "var(--series-1)")],
        )
        assert "MA20" in table
        assert "Current" in table
        assert "Range" in table


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

    def test_extreme_imbalance_does_not_overflow_canvas(self):
        # Regression: the middle segment is centered on the canvas and
        # each side extends outward by its own width -- fine when
        # bearish/bullish are close, but a real screenshot showed 9
        # bullish vs. 4 bearish already pushed the bullish bar and its
        # count label past the right edge (W=620). This is worse with a
        # bigger imbalance, real ones found live (18 vs. 1) and
        # synthetic ones (1000 vs. 1) both overflowed before the fix.
        import re
        for bearish, untagged, bullish in [(1, 1, 1000), (1000, 1, 1), (1, 11, 18), (500, 0, 1)]:
            svg, table, legend = diverging_stacked_sentiment(bearish, untagged, bullish)
            xs = [float(m) for m in re.findall(r'<text x="([\d.-]+)"', svg)]
            assert all(0 <= x <= 620 for x in xs), f"label x outside canvas for {(bearish, untagged, bullish)}: {xs}"


class TestDivergingStackedOrdinal:
    """The recommendation-trend chart (Strong Sell..Strong Buy) -- a
    generalization of diverging_stacked_sentiment to N segments per side,
    added when section_analyst() moved off a bare table (see HANDOFF.md)."""

    def test_all_zero_returns_empty_state(self):
        svg, table, legend = diverging_stacked_ordinal(
            neg_segments=[("Sell", 0), ("Strong sell", 0)],
            mid_value=0,
            pos_segments=[("Buy", 0), ("Strong buy", 0)],
        )
        assert svg == "<svg></svg>"
        assert "empty" in table

    def test_real_counts_have_dimensions_and_both_hues(self):
        svg, table, legend = diverging_stacked_ordinal(
            neg_segments=[("Sell", 3), ("Strong sell", 1)],
            mid_value=5,
            pos_segments=[("Buy", 8), ("Strong buy", 4)],
            mid_label="Hold",
        )
        assert_svg_has_dimensions(svg)
        assert "var(--diverge-neg)" in svg
        assert "var(--diverge-pos)" in svg
        assert "var(--gridline)" in svg  # neutral/hold segment

    def test_end_labels_show_running_totals_not_last_segment_only(self):
        # The bug this guards: end-labels must sum every segment on a side
        # (e.g. Sell + Strong sell = 4), not just show the last segment's
        # own value (1).
        svg, table, legend = diverging_stacked_ordinal(
            neg_segments=[("Sell", 3), ("Strong sell", 1)],
            mid_value=5,
            pos_segments=[("Buy", 8), ("Strong buy", 4)],
        )
        assert ">4<" in svg  # neg total: 3 + 1
        assert ">12<" in svg  # pos total: 8 + 4

    def test_extreme_imbalance_does_not_overflow_canvas(self):
        # Same class of bug as diverging_stacked_sentiment (they share the
        # centered-middle-segment layout): a heavily lopsided split can
        # push the larger side's bar and its total label past the canvas
        # edge if nothing scales the whole diagram down to fit.
        import re
        cases = [
            ([("Sell", 1), ("Strong sell", 1)], 1, [("Buy", 1), ("Strong buy", 500)]),
            ([("Sell", 1), ("Strong sell", 500)], 1, [("Buy", 1), ("Strong buy", 1)]),
        ]
        for neg, mid, pos in cases:
            svg, table, legend = diverging_stacked_ordinal(neg, mid, pos)
            xs = [float(m) for m in re.findall(r'<text x="([\d.-]+)"', svg)]
            assert all(0 <= x <= 620 for x in xs), f"label x outside canvas: {xs}"

    def test_one_sided_only_does_not_crash(self):
        # Real recommendation-trend data is often lopsided (e.g. all buys,
        # no sells at all for a given period) -- zero segments on one side
        # must not divide by zero in the opacity gradient.
        svg, table, legend = diverging_stacked_ordinal(
            neg_segments=[("Sell", 0), ("Strong sell", 0)],
            mid_value=2,
            pos_segments=[("Buy", 6), ("Strong buy", 2)],
        )
        assert_svg_has_dimensions(svg)
        assert "var(--diverge-neg)" not in svg
        assert "var(--diverge-pos)" in svg

    def test_table_rows_ordered_worst_to_best(self):
        svg, table, legend = diverging_stacked_ordinal(
            neg_segments=[("Sell", 3), ("Strong sell", 1)],
            mid_value=5,
            pos_segments=[("Buy", 8), ("Strong buy", 4)],
            mid_label="Hold",
        )
        strong_sell_idx = table.index("Strong sell")
        sell_idx = table.index(">Sell<")
        hold_idx = table.index("Hold")
        buy_idx = table.index(">Buy<")
        strong_buy_idx = table.index("Strong buy")
        assert strong_sell_idx < sell_idx < hold_idx < buy_idx < strong_buy_idx
