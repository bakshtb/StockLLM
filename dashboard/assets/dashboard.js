/*
 * Renders every chart registered in window.__CHARTS__ (emitted by
 * dashboard/generate_dashboard.py's register_chart()) via Apache ECharts.
 *
 * Design notes (see /root/.claude/plans -- or just CHANGELOG.md -- for the
 * full rationale of why this file exists at all):
 *
 * - Every option dict coming from Python is data-only JSON: no colors are
 *   ever baked to hex, and no formatter is ever a JS function. Colors are
 *   left as literal "var(--xxx)" strings (the exact CSS custom property
 *   names already used everywhere else on the page) and formatters are left
 *   as one of a small set of string tokens. hydrateOption() below is the one
 *   place that walks an option tree and turns both into real values/
 *   functions, right before every setOption() call. This means a chart's
 *   colors can never drift from the CSS palette (single source of truth),
 *   and re-theming on a dark-mode toggle is just "run hydrateOption again
 *   and setOption with notMerge:true" -- no per-chart-type special casing.
 *
 * - Every datapoint that needs a human-readable display string carries its
 *   own pre-formatted `fmt` field (set in Python via fmt_usd/fmt_pct/
 *   fmt_price/fmt_num) -- genericTooltipFormatter/genericLabelFormatter just
 *   read it. JS never re-derives display text from a raw number.
 */
(function () {
  'use strict';

  var TOKEN_TOOLTIP = '__tooltipFmt__';
  var TOKEN_LABEL = '__labelFmt__';
  var TOKEN_AXIS_COMPACT = '__compactAxis__';
  var TOKEN_RANGE_TRACK_LABEL_LAYOUT = '__rangeTrackLabelLayout__';
  var TOKEN_VBAR_LABEL_STAGGER = '__verticalBarLabelStagger__';
  var VAR_RE = /^var\((--[\w-]+)\)$/;

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  // Mirrors dashboard/generate_dashboard.py's fmt_compact() exactly (same
  // thresholds, same T/B/M/K suffixes, no currency sign -- only the
  // dedicated fmt_usd() adds "$", and that's already done server-side into
  // each datapoint's own `fmt` field, not here).
  function formatCompact(value) {
    var v = Number(value);
    if (!isFinite(v)) return String(value);
    var av = Math.abs(v);
    var sign = v < 0 ? '-' : '';
    if (av >= 1e12) return sign + (av / 1e12).toFixed(1) + 'T';
    if (av >= 1e9) return sign + (av / 1e9).toFixed(1) + 'B';
    if (av >= 1e6) return sign + (av / 1e6).toFixed(1) + 'M';
    if (av >= 1e3) return sign + (av / 1e3).toFixed(1) + 'K';
    return sign + av.toFixed(1);
  }

  function genericTooltipFormatter(params) {
    var list = Array.isArray(params) ? params : [params];
    var lines = list
      .filter(function (p) { return p.data !== null && p.data !== undefined; })
      .map(function (p) {
        var d = p.data;
        var name = (d && typeof d === 'object' && d.name) || p.seriesName || p.name || '';
        var val = (d && typeof d === 'object' && d.fmt !== undefined) ? d.fmt : p.value;
        return name ? (name + ': ' + val) : String(val);
      });
    return lines.join('<br/>');
  }

  function genericLabelFormatter(params) {
    var d = params.data;
    if (d && typeof d === 'object' && d.fmt !== undefined) return d.fmt;
    return params.value;
  }

  // ECharts' declarative `labelLayout: {moveOverlap: "shiftY"}` does not
  // reliably move labels that have an explicit `position` (e.g. a scatter
  // point's "bottom", or a corner label's [x,y] offset) -- confirmed by
  // direct testing (see CHANGELOG), not assumed. This is a real, working
  // greedy stagger instead, specific to range_meter/range_position_plot's
  // shared track layout: a chart-level `labelLayout` *callback* (ECharts
  // calls this once per label across every series, including markPoint
  // labels -- not scoped to a single series) using each label's actual
  // rendered pixel rect, more accurate than computing a stagger from data
  // coordinates server-side since it reacts to the label's true measured
  // size.
  //
  // Two independent groups, not one: corner (Low/High) and "Current"
  // labels sit ABOVE the track and must stagger upward (away from the
  // track) when they collide; named markers (MA200, Mean, etc.) sit BELOW
  // and must stagger downward. Pushing everything one direction would
  // shove an "above" label back down into the track itself. Identified by
  // dataIndex (the scatter series always lists Low, High first, then
  // named markers) or seriesIndex (the line/track series' markPoint is
  // always "Current", always above).
  //
  // Each call to this factory returns a fresh closure with its own private
  // state -- hydrateOption() re-walks the option tree (calling this
  // factory again) on every render, so state naturally starts empty once
  // per render with no explicit reset needed, and multiple chart instances
  // on the same page never share or interfere with each other's state.
  function makeRangeTrackLabelLayout() {
    var placedAbove = [];
    var placedBelow = [];
    return function (params) {
      var isAbove = params.seriesIndex === 0 || params.dataIndex < 2;
      var placed = isAbove ? placedAbove : placedBelow;
      // Defensive reset: ECharts can call labelLayout more than once per
      // render (e.g. a relayout pass) -- dataIndex 0 reliably means "a
      // fresh pass over this series just started", so treat that as a
      // signal to forget whatever was placed in a previous pass rather
      // than letting stale positions from an earlier pass keep
      // accumulating and influencing this one indefinitely.
      if (params.dataIndex === 0) placed.length = 0;
      var r = params.labelRect;
      var y = r.y;
      var moved = true;
      // Hard cap: each resolution provably converges (y moves strictly
      // one direction, so it must clear a finite placed list eventually)
      // under normal conditions, but this guarantees a single mis-sized
      // rect or an ECharts edge case this wasn't tested against can never
      // hang the tab -- worst case, a rare label lands imperfectly
      // instead of freezing the page.
      var guard = 0;
      while (moved && guard < 50) {
        moved = false;
        guard++;
        for (var i = 0; i < placed.length; i++) {
          var p = placed[i];
          var overlapX = r.x < p.x + p.width && r.x + r.width > p.x;
          var overlapY = y < p.y + p.height && y + r.height > p.y;
          if (overlapX && overlapY) {
            y = isAbove ? p.y - r.height - 2 : p.y + p.height + 2;
            moved = true;
          }
        }
      }
      placed.push({ x: r.x, y: y, width: r.width, height: r.height });
      return { x: r.x, y: y };
    };
  }

  // grouped_column_chart's last-category value labels (one per series,
  // e.g. Revenue vs. Net income for the most recent quarter): unlike the
  // range-track charts above, "always push the same direction" is wrong
  // here -- the label that must move is whichever series' bar is *taller*
  // (it has more empty space above it to move into); the shorter bar's
  // label should stay put, since pushing it down would shove it into its
  // own bar. Track each label's natural (pre-shift) position alongside its
  // shifted one so a later-processed label can tell, regardless of the
  // order ECharts happens to call this in, whether *it* is the taller one
  // (and should move) or the shorter one that arrived second (in which
  // case nudge the earlier, taller one instead -- rare, but two out of
  // order is still possible with more than 2 series).
  function makeVerticalBarLabelStagger() {
    var placed = [];
    return function (params) {
      // Defensive reset: this chart only ever shows a handful of labels
      // (one per series, all on the last category), so if `placed` has
      // grown past any plausible real count it means ECharts has looped
      // back for another relayout pass -- forget the previous pass's
      // (possibly now-stale) positions rather than letting them accumulate
      // without bound across passes.
      if (placed.length > 24) placed.length = 0;
      var r = params.labelRect;
      var naturalY = r.y;
      var y = naturalY;
      var moved = true;
      // Hard cap for the same reason as makeRangeTrackLabelLayout above:
      // guarantees this can never hang the tab regardless of how many
      // times ECharts ends up calling this or what edge case triggers it.
      var guard = 0;
      while (moved && guard < 50) {
        moved = false;
        guard++;
        for (var i = 0; i < placed.length; i++) {
          var p = placed[i];
          var overlapX = r.x < p.x + p.width && r.x + r.width > p.x;
          var overlapY = y < p.y + p.height && y + r.height > p.y;
          if (overlapX && overlapY) {
            y = naturalY <= p.naturalY ? p.y - r.height - 2 : p.y + p.height + 2;
            moved = true;
          }
        }
      }
      placed.push({ naturalY: naturalY, x: r.x, y: y, width: r.width, height: r.height });
      return { x: r.x, y: y };
    };
  }

  // Recursively walks an option tree, resolving "var(--x)" color strings
  // against the live CSS custom properties and swapping known token strings
  // for the real formatter functions above. Returns a new tree; never
  // mutates the original (window.__CHARTS__ stays the untouched source of
  // truth across theme toggles/resizes).
  function hydrateOption(node) {
    if (typeof node === 'string') {
      var m = VAR_RE.exec(node);
      if (m) return cssVar(m[1]);
      if (node === TOKEN_TOOLTIP) return genericTooltipFormatter;
      if (node === TOKEN_LABEL) return genericLabelFormatter;
      if (node === TOKEN_AXIS_COMPACT) return formatCompact;
      if (node === TOKEN_RANGE_TRACK_LABEL_LAYOUT) return makeRangeTrackLabelLayout();
      if (node === TOKEN_VBAR_LABEL_STAGGER) return makeVerticalBarLabelStagger();
      return node;
    }
    if (Array.isArray(node)) return node.map(hydrateOption);
    if (node && typeof node === 'object') {
      var out = {};
      for (var k in node) {
        if (Object.prototype.hasOwnProperty.call(node, k)) out[k] = hydrateOption(node[k]);
      }
      return out;
    }
    return node;
  }

  var registry = {}; // chart_id -> {instance, option}
  var resizeObserver = null;

  function initOne(id, rawOption) {
    var el = document.getElementById(id);
    if (!el) return;
    // SVG, not the default canvas: real DOM text (selectable, works with
    // screen readers, inspectable via getBBox for automated layout
    // verification -- canvas text is just pixels, none of that). These are
    // small, low-density charts; canvas's usual advantage (many thousands
    // of points, frequent animation) doesn't apply here.
    var instance = echarts.init(el, null, { renderer: "svg" });
    instance.setOption(hydrateOption(rawOption), true);
    registry[id] = { instance: instance, option: rawOption };
    if (resizeObserver) resizeObserver.observe(el);
  }

  function init() {
    if (!window.echarts) {
      // Vendored file failed to load/copy -- fall back to the always-
      // correct table view instead of showing empty chart boxes with no
      // explanation.
      document.querySelectorAll('.viz-card').forEach(function (card) {
        card.classList.add('is-table-view');
      });
      return;
    }

    var charts = window.__CHARTS__ || {};

    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(function (entries) {
        entries.forEach(function (entry) {
          var id = entry.target.id;
          if (registry[id]) registry[id].instance.resize();
        });
      });
    }

    Object.keys(charts).forEach(function (id) { initOne(id, charts[id]); });
  }

  function resizeAll() {
    Object.keys(registry).forEach(function (id) { registry[id].instance.resize(); });
  }

  function resizeWithin(cardEl) {
    if (!cardEl) return;
    cardEl.querySelectorAll('.echarts-container').forEach(function (el) {
      if (registry[el.id]) registry[el.id].instance.resize();
    });
  }

  function reapplyTheme() {
    Object.keys(registry).forEach(function (id) {
      var entry = registry[id];
      entry.instance.setOption(hydrateOption(entry.option), true);
    });
  }

  window.StockLLMCharts = {
    init: init,
    resizeAll: resizeAll,
    resizeWithin: resizeWithin,
    reapplyTheme: reapplyTheme,
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  window.addEventListener('resize', resizeAll);
})();
