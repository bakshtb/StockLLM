"""
Tests for dashboard/generate_dashboard.py's ECharts-backed chart functions.

These used to hand-generate raw SVG with manually computed pixel geometry --
an endless source of mobile/responsive bugs (see CHANGELOG.md 0.8.1-0.8.8 for
the full history). Charts now build a plain-dict ECharts "option" and hand it
to register_chart(), which returns an HTML placeholder div and stashes the
option in a thread-local registry (see generate_dashboard.py's own comments
on why thread-local: webapp/app.py serves via a multi-threaded server).
Two things every function still gets checked for:
  1. Empty/all-None input returns (None, empty_state()) -- no chart div, no
     registry entry -- instead of crashing or emitting an empty chart.
  2. The registered option dict actually has the right shape: the right
     ECharts series `type`, the right values/colors/`fmt` strings made it
     into `series[].data`, and the container div carries `role="img"
     aria-label="..."` (ECharts options have no native aria concept -- this
     is set directly on the wrapping div by Python).
"""

import re

import pytest

import dashboard.generate_dashboard as gd
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


@pytest.fixture(autouse=True)
def _reset_chart_registry():
    """The chart registry is thread-local and normally reset once per
    build_dashboard() call -- reset it before every test too, so each test's
    chart ids/lookups don't accumulate across the whole test session."""
    gd._reset_chart_registry()
    yield


def get_chart_option(chart_html: str) -> dict:
    """Given the div HTML register_chart() returned, look up the actual
    registered ECharts option dict it's paired with."""
    m = re.search(r'id="(chart-\d+)"', chart_html)
    assert m, f"expected a chart div with an id, got: {chart_html[:120]!r}"
    return dict(gd._chart_state.charts)[m.group(1)]


def assert_chart_has_dimensions(chart_html: str):
    """A real (non-empty-state) chart div must carry an explicit height
    (ECharts can't infer height from content the way a plain element can)
    and an accessible role/label."""
    assert chart_html is not None
    assert 'class="echarts-container"' in chart_html
    assert re.search(r'style="height:\d+px"', chart_html), "missing explicit height"
    assert 'role="img"' in chart_html
    assert re.search(r'aria-label="[^"]+"', chart_html)


class TestBarChartHorizontal:
    def test_empty_items_returns_empty_state(self):
        chart, table = bar_chart_horizontal([])
        assert chart is None
        assert "empty" in table

    def test_all_none_values_returns_empty_state(self):
        chart, table = bar_chart_horizontal([("a", None), ("b", None)])
        assert chart is None

    def test_real_data_has_dimensions_and_right_series_type(self):
        chart, table = bar_chart_horizontal([("Low", 100), ("High", 200)], value_fmt=lambda v: f"{v}!")
        assert_chart_has_dimensions(chart)
        assert "Low" in table and "High" in table
        option = get_chart_option(chart)
        assert option["series"][0]["type"] == "bar"
        assert option["yAxis"]["data"] == ["Low", "High"]
        assert [d["value"] for d in option["series"][0]["data"]] == [100, 200]
        assert [d["fmt"] for d in option["series"][0]["data"]] == ["100!", "200!"]

    def test_none_values_are_filtered_not_crashed_on(self):
        # A mix of real and missing values (common: some quarters have
        # data, others don't) shouldn't raise.
        chart, table = bar_chart_horizontal([("a", 10), ("b", None), ("c", 30)])
        assert_chart_has_dimensions(chart)
        option = get_chart_option(chart)
        assert option["yAxis"]["data"] == ["a", "c"]


class TestDivergingBarHorizontal:
    def test_empty_returns_empty_state(self):
        chart, table, legend = diverging_bar_horizontal([])
        assert chart is None

    def test_positive_and_negative_values_both_render(self):
        chart, table, legend = diverging_bar_horizontal([("beat", 10.0), ("miss", -5.0)])
        assert_chart_has_dimensions(chart)
        option = get_chart_option(chart)
        colors = [d["itemStyle"]["color"] for d in option["series"][0]["data"]]
        assert colors == ["var(--diverge-pos)", "var(--diverge-neg)"]

    def test_long_bar_gets_inside_label_short_bar_gets_outside(self):
        # A bar at/above INSIDE_LABEL_FRACTION of max_v gets its label
        # placed inside (light text) rather than past its tip -- otherwise
        # a long negative bar's label lands on top of that row's own name
        # label (found live: MBLY's -42.6% 1-year return).
        chart, table, legend = diverging_bar_horizontal([("long", 100.0), ("short", 5.0)])
        option = get_chart_option(chart)
        long_label, short_label = (d["label"] for d in option["series"][0]["data"])
        assert long_label["position"] == "insideRight"
        assert short_label["position"] == "right"

    def test_negative_long_bar_labels_inside_left(self):
        chart, table, legend = diverging_bar_horizontal([("long_neg", -100.0), ("short_pos", 5.0)])
        option = get_chart_option(chart)
        neg_label, pos_label = (d["label"] for d in option["series"][0]["data"])
        assert neg_label["position"] == "insideLeft"
        assert pos_label["position"] == "right"


class TestGroupedBarHorizontal:
    def test_empty_groups_returns_empty_state(self):
        chart, table, legend = grouped_bar_horizontal([])
        assert chart is None

    def test_all_none_values_returns_empty_state(self):
        chart, table, legend = grouped_bar_horizontal([
            ("20d", [("Stock", "var(--series-1)", None)]),
        ])
        assert chart is None

    def test_negative_values_grow_the_correct_direction(self):
        # Real bug (HANDOFF.md #26): negative values used to render as if
        # positive, sized by magnitude only, with no visual sign at all.
        # ECharts' value axis handles the sign natively -- what's left to
        # check is that both series keep their own distinct color.
        groups = [("1y return", [
            ("Stock", "var(--series-1)", -42.58),
            ("S&P 500", "var(--series-2)", 16.25),
        ])]
        chart, table, legend = grouped_bar_horizontal(groups)
        assert_chart_has_dimensions(chart)
        option = get_chart_option(chart)
        colors = {s["name"]: s["itemStyle"]["color"] for s in option["series"]}
        assert colors == {"Stock": "var(--series-1)", "S&P 500": "var(--series-2)"}
        stock_series = next(s for s in option["series"] if s["name"] == "Stock")
        assert stock_series["data"][0]["value"] == -42.58

    def test_missing_series_value_skipped_not_crashed(self):
        groups = [("20d", [("Stock", "var(--series-1)", 5.0), ("Sector", "var(--series-3)", None)])]
        chart, table, legend = grouped_bar_horizontal(groups)
        assert_chart_has_dimensions(chart)
        option = get_chart_option(chart)
        sector_series = next(s for s in option["series"] if s["name"] == "Sector")
        assert sector_series["data"][0] is None  # missing value -> gap, not a crash or a zero


class TestGroupedColumnChart:
    def test_empty_categories_returns_empty_state(self):
        chart, table, legend = grouped_column_chart([], [])
        assert chart is None

    def test_real_data_has_dimensions_and_right_series(self):
        categories = ["Q1", "Q2"]
        series = [("Revenue", "var(--series-1)", [100, 200]), ("Net income", "var(--series-2)", [10, 20])]
        chart, table, legend = grouped_column_chart(categories, series)
        assert_chart_has_dimensions(chart)
        option = get_chart_option(chart)
        assert option["xAxis"]["data"] == categories
        assert [s["type"] for s in option["series"]] == ["bar", "bar"]
        assert [s["data"][1]["value"] for s in option["series"]] == [200, 20]

    def test_negative_values_handled(self):
        # Net income can be negative (a loss quarter) -- must not crash the
        # min/max axis math.
        categories = ["Q1"]
        series = [("Net income", "var(--series-2)", [-50])]
        chart, table, legend = grouped_column_chart(categories, series)
        assert_chart_has_dimensions(chart)
        option = get_chart_option(chart)
        assert option["yAxis"]["min"] == -50

    def test_last_category_gets_a_value_label_others_dont(self):
        categories = ["Q1", "Q2"]
        series = [("Revenue", "var(--series-1)", [100, 119.8]), ("Net income", "var(--series-2)", [90, 112.2])]
        chart, table, legend = grouped_column_chart(categories, series)
        option = get_chart_option(chart)
        for s in option["series"]:
            assert "label" not in s["data"][0]  # Q1 (not the last category): no label
            assert s["data"][1]["label"]["show"] is True  # Q2 (last category): labeled

    def test_label_collision_stagger_is_wired_up(self):
        # Regression: found on real data (Revenue vs. Net income close in
        # value for the most recent quarter) -- both series' value labels
        # landed at nearly the same height, overlapping. ECharts' own
        # declarative labelLayout ({"moveOverlap": "shiftY"}) was tried
        # first and does NOT reliably move labels with an explicit position
        # (confirmed via direct browser testing, not assumed) -- a real
        # working greedy stagger lives in webui/src/js/hydrate.js instead
        # (makeVerticalBarLabelStagger), referenced here by name.
        chart, table, legend = grouped_column_chart(
            ["Q1", "Q2"], [("Revenue", "var(--series-1)", [100, 119.8]), ("Net income", "var(--series-2)", [90, 112.2])]
        )
        option = get_chart_option(chart)
        assert option["labelLayout"] == "__verticalBarLabelStagger__"


class TestRangeMeter:
    def test_missing_low_high_returns_empty_state(self):
        chart, table, legend = range_meter(None, 10, 10, None, 5)
        assert chart is None

    def test_real_range_has_dimensions_and_right_series_types(self):
        chart, table, legend = range_meter(low=100, mean=150, median=140, high=200, current=160)
        assert_chart_has_dimensions(chart)
        option = get_chart_option(chart)
        assert option["series"][0]["type"] == "line"  # the track
        assert option["series"][1]["type"] == "scatter"  # named point markers
        names = [d["name"] for d in option["series"][1]["data"]]
        assert names == ["Low", "High", "Mean", "Median"]

    def test_marker_dots_are_visibly_bigger_than_the_track(self):
        # Regression: symbolSize 12 on a 10px-thick track left only 1px of
        # dot poking out per side -- read as an invisible sliver, not a
        # marker (found live from a screenshot). Must stay clearly bigger
        # than the track's own lineStyle width, with a border so it reads
        # as a distinct dot even when its fill color is close to the
        # track's own muted fill.
        chart, table, legend = range_meter(low=100, mean=150, median=140, high=200, current=160)
        option = get_chart_option(chart)
        track_width = option["series"][0]["lineStyle"]["width"]
        mean_point = next(d for d in option["series"][1]["data"] if d["name"] == "Mean")
        assert mean_point["symbol"] == "rect"
        assert mean_point["symbolSize"][0] > track_width and mean_point["symbolSize"][1] > track_width
        assert mean_point["itemStyle"]["borderWidth"] > 0

    def test_low_high_visible_and_painted_above_track(self):
        # Both flagged directly by the user on this exact chart ("Analyst
        # target price range"): Low/High had no dot at all (symbolSize: 0),
        # and every marker's dot was painted UNDER the opaque track instead
        # of on top of it. Shared root cause with range_position_plot,
        # fixed in the shared _range_track_option() both call. Low/High are
        # now thin end-stop ticks (rect, [2, 20]) rather than round dots.
        chart, table, legend = range_meter(low=100, mean=150, median=140, high=200, current=160)
        option = get_chart_option(chart)
        low_point, high_point = option["series"][1]["data"][0], option["series"][1]["data"][1]
        assert low_point["symbol"] == "rect" and low_point["symbolSize"][1] > 0
        assert high_point["symbol"] == "rect" and high_point["symbolSize"][1] > 0
        assert option["series"][1]["z"] > option["series"][0]["z"]

    def test_current_outside_range_is_clamped_not_crashed_on(self):
        # Current price can legitimately fall outside the analyst range
        # (e.g. today's price above every analyst's target). The xAxis is
        # fixed to [low, high], so the marker must be visually clamped to
        # whichever edge it overshot -- while still showing its real,
        # unclamped value in the label/tooltip.
        chart, table, legend = range_meter(low=100, mean=150, median=140, high=200, current=250)
        option = get_chart_option(chart)
        mark_point = option["series"][0]["markPoint"]["data"][0]
        assert mark_point["coord"][0] == 200  # clamped to the high edge
        assert mark_point["fmt"] == "$250.00"  # but the real value is still shown

    def test_labellayout_collision_avoidance_is_turned_on(self):
        # Mean and median frequently land close together in real data, and
        # "Current" can crowd a Low/High corner label near an edge -- both
        # used to need hand-rolled stagger/suppression logic. ECharts'
        # declarative labelLayout ({"moveOverlap": "shiftY"}) was tried
        # first and does NOT reliably move labels with an explicit position
        # (confirmed via direct browser testing, not assumed) -- a real
        # working greedy stagger lives in webui/src/js/hydrate.js instead
        # (makeRangeTrackLabelLayout), referenced here by name.
        chart, table, legend = range_meter(low=215, mean=320, median=325, high=400, current=393)
        option = get_chart_option(chart)
        assert option["labelLayout"] == "__rangeTrackLabelLayout__"

    def test_current_marker_present_with_real_value_when_near_an_edge(self):
        chart, table, legend = range_meter(low=215, mean=320, median=325, high=400, current=393)
        option = get_chart_option(chart)
        assert option["series"][0]["markPoint"]["data"][0]["fmt"] == "$393.00"
        assert "Current price" in table  # raw value still in the table view

    def test_legend_names_the_marker_colors(self):
        # Regression: Mean/Median render as bare-price dots with no name in
        # the chart itself -- a user couldn't tell which colored dot was
        # which (found live, same gap as range_position_plot below).
        chart, table, legend = range_meter(low=100, mean=150, median=140, high=200, current=160)
        assert "Mean" in legend and "Median" in legend
        assert "var(--accent)" in legend  # Mean's color
        assert "var(--accent-300)" in legend  # Median's color

    def test_no_markers_means_no_legend(self):
        # The AI fair-value block calls range_meter with mean=median=None
        # (just a Low/High/Current track) -- no ambiguous dots exist, so no
        # legend should render (an empty one would just be dead markup).
        chart, table, legend = range_meter(low=200, mean=None, median=None, high=250, current=220)
        assert legend == ""


class TestRangePositionPlot:
    """Price-vs-moving-averages: a dot plot on a shared axis, replacing a
    zero-anchored bar chart that made every bar look near-identical length
    when all values sit in a narrow band relative to their own magnitude
    (found from a real dashboard screenshot -- see HANDOFF.md)."""

    def test_missing_low_high_returns_empty_state(self):
        chart, table, legend = range_position_plot(None, 340, 300, [("MA20", 320, "var(--series-1)")])
        assert chart is None

    def test_real_data_has_dimensions_and_every_marker_present(self):
        chart, table, legend = range_position_plot(
            201.58, 340.08, 333.43,
            [("MA200", 277.35, "var(--series-3)"), ("MA50", 309.30, "var(--series-2)"), ("MA20", 324.35, "var(--series-1)")],
        )
        assert_chart_has_dimensions(chart)
        option = get_chart_option(chart)
        names = [d["name"] for d in option["series"][1]["data"]]
        assert names == ["Low", "High", "MA200", "MA50", "MA20"]
        assert option["series"][0]["markPoint"]["data"][0]["name"] == "Current"

    def test_current_outside_range_is_clamped_not_crashed_on(self):
        chart, table, legend = range_position_plot(100, 200, 250, [("MA20", 150, "var(--series-1)")])
        option = get_chart_option(chart)
        mark_point = option["series"][0]["markPoint"]["data"][0]
        assert mark_point["coord"][0] == 200
        assert mark_point["fmt"] == "$250.00"

    def test_missing_current_omits_current_marker(self):
        chart, table, legend = range_position_plot(100, 200, None, [("MA20", 150, "var(--series-1)")])
        assert_chart_has_dimensions(chart)
        option = get_chart_option(chart)
        assert "markPoint" not in option["series"][0]
        assert "Current" not in table

    def test_track_width_matches_gauge_meters_rsi_track(self):
        # Regression: this chart used pad=60 (track spans 60..560, 500 of
        # 620 units) while gauge_meter's RSI track -- shown directly below
        # it on the same card, same width -- used pad=20 (spans 20..600,
        # 580 of 620 units). Same card, two different-looking track
        # widths right next to each other; a real screenshot called this
        # out directly ("it's not in full width like the RSI line"). Both
        # now share the exact same xAxis min/max = low/high approach (no
        # separate internal pixel padding at all), so there's no longer a
        # pad constant to drift out of sync between the two chart types.
        chart, table, legend = range_position_plot(100, 200, 150, [("MA20", 150, "var(--series-1)")])
        option = get_chart_option(chart)
        assert option["xAxis"]["min"] == 100
        assert option["xAxis"]["max"] == 200

    def test_corner_labels_always_present_even_when_current_is_near_the_high(self):
        # Regression: suppressing the "$340.08" corner label when Current
        # sits near it (the original approach) left a big unexplained empty
        # patch of track that read as "this chart doesn't fill its card" on
        # a real screenshot. Corner labels must always render; ECharts'
        # labelLayout (not a Python-side suppression decision) is what
        # keeps Current's own label legible if it crowds one.
        chart, table, legend = range_position_plot(
            201.58, 340.08, 333.43,
            [("MA200", 277.35, "var(--series-3)"), ("MA50", 309.30, "var(--series-2)"), ("MA20", 324.35, "var(--series-1)")],
        )
        option = get_chart_option(chart)
        low_label, high_label = option["series"][1]["data"][0], option["series"][1]["data"][1]
        assert low_label["fmt"] == "$201.58" and low_label["label"]["show"] is True
        assert high_label["fmt"] == "$340.08" and high_label["label"]["show"] is True

    def test_low_high_corner_labels_are_left_right_aligned(self):
        # The Industry restyle's two-line kicker/value corner label aligns
        # inward from each end (left at the low end, right at the high
        # end) rather than centering on the tick -- position stays the
        # string keyword "top" (not a raw [dx, dy] offset, which is
        # measured from the symbol's top-left corner rather than its
        # center and would visibly shift with a non-square tick symbol).
        chart, table, legend = range_position_plot(
            100, 200, 150, [("MA20", 150, "var(--series-1)")],
        )
        option = get_chart_option(chart)
        low_label, high_label = option["series"][1]["data"][0]["label"], option["series"][1]["data"][1]["label"]
        assert low_label["position"] == "top" and low_label["align"] == "left"
        assert high_label["position"] == "top" and high_label["align"] == "right"

    def test_table_lists_every_marker_and_range(self):
        chart, table, legend = range_position_plot(100, 200, 150, [("MA20", 130, "var(--series-1)")])
        assert "MA20" in table
        assert "Current" in table
        assert "Range" in table

    def test_legend_names_every_marker_color(self):
        # Regression: MA20/MA50/MA200 render as bare-price dots with no name
        # anywhere in the chart -- found live from a real screenshot, a user
        # had no way to tell which colored marker was which moving average.
        chart, table, legend = range_position_plot(
            201.58, 340.08, 308.91,
            [("MA200", 277.66, "var(--series-3)"), ("MA50", 309.50, "var(--series-2)"), ("MA20", 324.37, "var(--series-1)")],
        )
        assert "MA200" in legend and "MA50" in legend and "MA20" in legend
        assert "var(--series-3)" in legend and "var(--series-2)" in legend and "var(--series-1)" in legend

    def test_track_paints_below_markers_not_above(self):
        # Regression: ECharts does NOT paint cartesian series strictly in
        # array order -- confirmed live by reading the actual rendered
        # SVG's element order, the scatter series painted BEFORE the line
        # regardless of its later position in this option's series list, so
        # the opaque 10px track drew right on top of every marker dot,
        # hiding most of each one (found live: "the circles are still
        # behind the bar"). Explicit z is what actually controls paint
        # order; the track must stay below every marker.
        chart, table, legend = range_position_plot(
            100, 200, 150, [("MA20", 150, "var(--series-1)")],
        )
        option = get_chart_option(chart)
        track_z = option["series"][0]["z"]
        marker_z = option["series"][1]["z"]
        assert marker_z > track_z

    def test_low_high_have_visible_marker_dots(self):
        # Low/High used to be symbolSize: 0 (invisible) -- given a real,
        # visible end-stop tick here too (rect, [2, 20]), after a user
        # asked for one directly ("the low key ... need a circle too").
        chart, table, legend = range_position_plot(
            100, 200, 150, [("MA20", 150, "var(--series-1)")],
        )
        option = get_chart_option(chart)
        low_point, high_point = option["series"][1]["data"][0], option["series"][1]["data"][1]
        assert low_point["symbolSize"][1] > 0
        assert high_point["symbolSize"][1] > 0

    def test_no_markers_means_no_legend(self):
        chart, table, legend = range_position_plot(100, 200, 150, [])
        assert legend == ""


class TestGaugeMeter:
    """RSI's gauge: a flat zone-band bar (frame series + one stacked "bar"
    series per zone) with a triangle marker above it -- the same track/
    marker idiom range_meter()/range_position_plot() use via
    _range_track_option(), rather than ECharts' native type:"gauge"
    semicircular dial, so every value+context figure on the page shares one
    visual grammar (see the Industry design-system handoff)."""

    def test_none_value_returns_empty_state(self):
        chart, table = gauge_meter(None, 0, 100, zones=[(100, "var(--gridline)", "x")], label="RSI")
        assert chart is None

    def test_real_value_has_dimensions_and_a_needle_marker(self):
        chart, table = gauge_meter(65.4, 0, 100, zones=[(30, "var(--status-good)", "a"), (100, "var(--status-critical)", "b")], label="RSI")
        assert_chart_has_dimensions(chart)
        option = get_chart_option(chart)
        needle = option["series"][-1]
        assert needle["type"] == "line"
        assert needle["markPoint"]["data"][0]["coord"] == [65.4, ""]
        assert needle["markPoint"]["data"][0]["fmt"] == "65.4"

    def test_zones_render_as_stacked_bar_segments_with_correct_widths(self):
        # Zones are absolute-width bar segments stacked left-to-right, not
        # fractions of [min, max] the way ECharts' native gauge zones are.
        chart, table = gauge_meter(45, 0, 100, zones=[(30, "var(--status-good)", "a"), (70, "var(--gridline)", "b"), (100, "var(--status-critical)", "c")], label="RSI")
        option = get_chart_option(chart)
        zone_series = option["series"][1:-1]  # series[0] is the frame, series[-1] is the needle
        assert [z["itemStyle"]["color"] for z in zone_series] == ["var(--status-good)", "var(--gridline)", "var(--status-critical)"]
        assert [z["data"][0]["value"] for z in zone_series] == [30, 40, 30]
        assert all(z["stack"] == "zones" for z in zone_series)

    def test_frame_series_draws_a_bordered_background_bar(self):
        chart, table = gauge_meter(45, 0, 100, zones=[(100, "var(--gridline)", "x")], label="RSI")
        option = get_chart_option(chart)
        frame = option["series"][0]
        assert frame["itemStyle"]["color"] == "transparent"
        assert frame["itemStyle"]["borderColor"] == "var(--border)"
        assert frame["data"] == [100]

    def test_value_rounded_for_display_fmt_kept_for_marker_position(self):
        chart, table = gauge_meter(45.06, 0, 100, zones=[(100, "var(--gridline)", "x")], label="RSI")
        option = get_chart_option(chart)
        needle = option["series"][-1]
        assert needle["markPoint"]["data"][0]["coord"][0] == 45.06
        assert needle["markPoint"]["data"][0]["fmt"] == "45.1"

    def test_needle_is_a_triangle_marker_above_the_track(self):
        chart, table = gauge_meter(45.1, 0, 100, zones=[(100, "var(--gridline)", "x")], label="RSI")
        option = get_chart_option(chart)
        needle = option["series"][-1]
        assert needle["markPoint"]["symbol"].startswith("path://")


class TestStackedBarParts:
    def test_empty_parts_returns_empty_state(self):
        chart, table, legend = stacked_bar_parts([])
        assert chart is None

    def test_zero_value_parts_filtered_out(self):
        chart, table, legend = stacked_bar_parts([("Institutions", 0, "var(--series-1)"), ("Insiders", 50, "var(--series-2)")])
        assert_chart_has_dimensions(chart)
        assert "Institutions" not in table  # zero-value entries are dropped

    def test_real_parts_have_dimensions_and_right_stack(self):
        chart, table, legend = stacked_bar_parts([
            ("Institutions", 60, "var(--series-1)"),
            ("Insiders", 30, "var(--series-2)"),
            ("Other", 10, "var(--gridline)"),
        ])
        assert_chart_has_dimensions(chart)
        option = get_chart_option(chart)
        segments = option["series"][1:]  # series[0] is the frame series
        assert all(s["stack"] == "total" for s in segments)
        assert [s["data"][0]["value"] for s in segments] == [60, 30, 10]

    def test_frame_series_draws_a_bordered_background_bar(self):
        # Square, not rounded (Industry's system has no rounded bars) --
        # framed with a 1px border instead, drawn as a background bar under
        # the stack via the same barGap:"-100%" trick gauge_meter() uses.
        chart, table, legend = stacked_bar_parts([
            ("Institutions", 60, "var(--series-1)"),
            ("Insiders", 30, "var(--series-2)"),
            ("Other", 10, "var(--gridline)"),
        ])
        option = get_chart_option(chart)
        frame = option["series"][0]
        assert frame["itemStyle"]["color"] == "transparent"
        assert frame["itemStyle"]["borderColor"] == "var(--border)"
        assert frame["data"] == [100.0]
        assert all("borderRadius" not in s["itemStyle"] for s in option["series"][1:])


class TestDivergingStackedSentiment:
    def test_all_zero_returns_empty_state(self):
        chart, table, legend = diverging_stacked_sentiment(0, 0, 0)
        assert chart is None

    def test_real_counts_have_dimensions_and_right_colors(self):
        chart, table, legend = diverging_stacked_sentiment(bearish=8, untagged=19, bullish=3)
        assert_chart_has_dimensions(chart)
        option = get_chart_option(chart)
        colors = [s["itemStyle"]["color"] for s in option["series"]]
        assert colors == ["var(--gridline)", "var(--diverge-neg)", "var(--gridline)", "var(--diverge-pos)"]

    def test_extreme_imbalance_cannot_overflow_the_fixed_axis(self):
        # Regression: the old SVG version centered its middle segment on
        # the canvas and let each side extend outward by its own width --
        # fine when bearish/bullish were close, but a real screenshot
        # showed 9 bullish vs. 4 bearish already pushed the bullish bar
        # and its count label past the right edge, worse with 18 vs. 1 and
        # synthetic 1000-vs-1 splits. ECharts' bidirectional stack is
        # self-centering by construction -- there's no axis range to
        # overflow at all here (unlike the old fixed-pixel canvas), so
        # what's actually worth checking is that every series' magnitude
        # still sums correctly regardless of skew.
        for bearish, untagged, bullish in [(1, 1, 1000), (1000, 1, 1), (1, 11, 18), (500, 0, 1)]:
            chart, table, legend = diverging_stacked_sentiment(bearish, untagged, bullish)
            option = get_chart_option(chart)
            neg_sum = -sum(s["data"][0]["value"] for s in option["series"] if s["data"][0]["value"] < 0)
            pos_sum = sum(s["data"][0]["value"] for s in option["series"] if s["data"][0]["value"] > 0)
            total = bearish + untagged + bullish
            assert abs(neg_sum + pos_sum - total) < 0.01

    def test_end_labels_show_bare_counts_not_the_tooltip_text(self):
        # The end-label ("4") and the tooltip ("4 messages") are two
        # different display strings for the same datapoint -- the label
        # must not accidentally show the tooltip's fuller text.
        chart, table, legend = diverging_stacked_sentiment(bearish=4, untagged=10, bullish=12)
        option = get_chart_option(chart)
        bearish_series = option["series"][1]
        bullish_series = option["series"][3]
        assert bearish_series["data"][0]["label"]["formatter"] == "4"
        assert bearish_series["data"][0]["fmt"] == "4 messages"
        assert bullish_series["data"][0]["label"]["formatter"] == "12"


class TestDivergingStackedOrdinal:
    """The recommendation-trend chart (Strong Sell..Strong Buy) -- a
    generalization of diverging_stacked_sentiment to N segments per side,
    added when section_analyst() moved off a bare table (see HANDOFF.md)."""

    def test_all_zero_returns_empty_state(self):
        chart, table, legend = diverging_stacked_ordinal(
            neg_segments=[("Sell", 0), ("Strong sell", 0)],
            mid_value=0,
            pos_segments=[("Buy", 0), ("Strong buy", 0)],
        )
        assert chart is None
        assert "empty" in table

    def test_real_counts_have_dimensions_and_both_hues(self):
        chart, table, legend = diverging_stacked_ordinal(
            neg_segments=[("Sell", 3), ("Strong sell", 1)],
            mid_value=5,
            pos_segments=[("Buy", 8), ("Strong buy", 4)],
            mid_label="Hold",
        )
        assert_chart_has_dimensions(chart)
        option = get_chart_option(chart)
        colors = {s["itemStyle"]["color"] for s in option["series"]}
        assert colors == {"var(--gridline)", "var(--diverge-neg)", "var(--diverge-pos)"}

    def test_end_labels_show_running_totals_not_last_segment_only(self):
        # The bug this guards: end-labels must sum every segment on a side
        # (e.g. Sell + Strong sell = 4), not just show the last segment's
        # own value (1).
        chart, table, legend = diverging_stacked_ordinal(
            neg_segments=[("Sell", 3), ("Strong sell", 1)],
            mid_value=5,
            pos_segments=[("Buy", 8), ("Strong buy", 4)],
        )
        option = get_chart_option(chart)
        neg_labels = [s["data"][0].get("label") for s in option["series"] if s["itemStyle"]["color"] == "var(--diverge-neg)"]
        pos_labels = [s["data"][0].get("label") for s in option["series"] if s["itemStyle"]["color"] == "var(--diverge-pos)"]
        assert [l for l in neg_labels if l][0]["formatter"] == "4"  # Sell(3) + Strong sell(1)
        assert [l for l in pos_labels if l][0]["formatter"] == "12"  # Buy(8) + Strong buy(4)

    def test_every_instance_uses_the_same_fixed_axis_range(self):
        # section_analyst() renders several of these as independent small
        # multiples, one per period -- periods must stay visually
        # comparable regardless of how many analysts covered each one, so
        # every instance pins the same [-100, 100] range rather than each
        # auto-scaling to its own data (which would also make differently-
        # skewed periods' bars different effective widths, not just
        # differently *positioned*).
        small_period = diverging_stacked_ordinal([("Sell", 1)], 1, [("Buy", 1)])
        large_period = diverging_stacked_ordinal([("Sell", 50)], 40, [("Buy", 60)])
        for chart, _, _ in (small_period, large_period):
            option = get_chart_option(chart)
            assert option["xAxis"]["min"] == -100
            assert option["xAxis"]["max"] == 100

    def test_one_sided_only_does_not_crash(self):
        # Real recommendation-trend data is often lopsided (e.g. all buys,
        # no sells at all for a given period) -- zero segments on one side
        # must not divide by zero in the opacity gradient.
        chart, table, legend = diverging_stacked_ordinal(
            neg_segments=[("Sell", 0), ("Strong sell", 0)],
            mid_value=2,
            pos_segments=[("Buy", 6), ("Strong buy", 2)],
        )
        assert_chart_has_dimensions(chart)
        option = get_chart_option(chart)
        colors = {s["itemStyle"]["color"] for s in option["series"]}
        assert "var(--diverge-neg)" not in colors
        assert "var(--diverge-pos)" in colors

    def test_table_rows_ordered_worst_to_best(self):
        chart, table, legend = diverging_stacked_ordinal(
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
