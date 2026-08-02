"""
Generates a single self-contained, offline HTML dashboard from a StockLLM
research bundle JSON file (the same JSON produced by `data/bundle.py`, or
written to disk via `python main.py check TICKER --dry-run -o file.json`).

No external dependencies, no CDN, no build step -- the output is one .html
file with embedded CSS/SVG/JS. Open it directly in a browser.

Usage:
    python -m dashboard.generate_dashboard mobileye.json
    python -m dashboard.generate_dashboard mobileye.json -o report.html

This is a pure rendering layer: it only formats what's already in the bundle
JSON (see data/bundle.py for what's in there and why) and makes no network
calls and no judgment calls of its own about the data.
"""

import argparse
import html
import json
import sys

# ============================================================================
# Color roles -- verbatim from the dataviz skill's reference palette
# (bundled-skills/.../dataviz/references/palette.md). Do not hand-tune a hex
# here; if the brand palette ever changes, swap the values in CSS_STYLE only.
# ============================================================================

CSS_STYLE = """
:root, .viz-root {
  color-scheme: light;
  --surface-1:      #fcfcfb;
  --page-plane:     #f9f9f7;
  --text-primary:   #0b0b0b;
  --text-secondary: #52514e;
  --text-muted:     #898781;
  --gridline:       #e1e0d9;
  --baseline:       #c3c2b7;
  --border:         rgba(11,11,11,0.10);
  --success-text:   #006300;

  --series-1: #2a78d6; /* blue */
  --series-2: #eb6834; /* orange */
  --series-3: #1baf7a; /* aqua */
  --series-4: #eda100; /* yellow */
  --series-5: #e87ba4; /* magenta */
  --series-6: #008300; /* green */
  --series-7: #4a3aa7; /* violet */
  --series-8: #e34948; /* red */

  /* Diverging pairs here mean "good news vs. bad news" (beat/miss, bullish/
     bearish), not neutral polarity/identity -- so they intentionally reuse
     the status colors (green/red) rather than the dataviz skill's default
     blue/red diverging pair, per explicit request for a green/red = good/bad
     convention throughout this dashboard. */
  --diverge-pos: #0ca30c;
  --diverge-neg: #d03b3b;
  --diverge-mid: #f0efec;

  --status-good:     #0ca30c;
  --status-warning:  #fab219;
  --status-serious:  #ec835a;
  --status-critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --surface-1:      #1a1a19;
    --page-plane:     #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted:     #898781;
    --gridline:       #2c2c2a;
    --baseline:       #383835;
    --border:         rgba(255,255,255,0.10);
    --success-text:   #0ca30c;

    --series-1: #3987e5;
    --series-2: #d95926;
    --series-3: #199e70;
    --series-4: #c98500;
    --series-5: #d55181;
    --series-6: #008300;
    --series-7: #9085e9;
    --series-8: #e66767;

    --diverge-pos: #0ca30c;
    --diverge-neg: #e66767;
    --diverge-mid: #383835;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --surface-1:      #1a1a19;
  --page-plane:     #0d0d0d;
  --text-primary:   #ffffff;
  --text-secondary: #c3c2b7;
  --text-muted:     #898781;
  --gridline:       #2c2c2a;
  --baseline:       #383835;
  --border:         rgba(255,255,255,0.10);
  --success-text:   #0ca30c;

  --series-1: #3987e5;
  --series-2: #d95926;
  --series-3: #199e70;
  --series-4: #c98500;
  --series-5: #d55181;
  --series-6: #008300;
  --series-7: #9085e9;
  --series-8: #e66767;

  --diverge-pos: #0ca30c;
  --diverge-neg: #e66767;
  --diverge-mid: #383835;
}

* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  background: var(--page-plane);
  color: var(--text-primary);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
}
body { padding: 0 0 64px 0; }

/* Topbar and the section nav below it stick together as one unit -- see
   .sticky-top, the wrapper that actually holds position: sticky (putting
   sticky on each separately would need the nav to know the topbar's exact
   rendered height, which varies with content/wrapping). */
.sticky-top { position: sticky; top: 0; z-index: 20; }
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 16px; padding: 16px 24px;
  background: var(--surface-1);
  border-bottom: 1px solid var(--border);
}
.topbar h1 { font-size: 20px; margin: 0; font-weight: 600; }
.topbar .meta { color: var(--text-secondary); font-size: 13px; margin-top: 2px; }

.section-nav {
  display: flex; gap: 6px; overflow-x: auto; -webkit-overflow-scrolling: touch;
  padding: 8px 24px; background: var(--surface-1); border-bottom: 1px solid var(--border);
  scrollbar-width: none;
}
.section-nav::-webkit-scrollbar { display: none; }
.section-nav a {
  flex-shrink: 0; font-size: 12.5px; font-weight: 600; color: var(--text-secondary);
  text-decoration: none; background: var(--page-plane); border: 1px solid var(--border);
  border-radius: 999px; padding: 6px 13px; white-space: nowrap;
  transition: color 0.15s ease, border-color 0.15s ease;
}
.section-nav a:hover, .section-nav a:focus { color: var(--text-primary); border-color: var(--text-secondary); outline: none; }
@media (min-width: 900px) { .section-nav { display: none; } }
.topbar-actions { display: flex; align-items: center; gap: 10px; }
button.chip {
  font: inherit; font-size: 13px; cursor: pointer;
  background: var(--surface-1); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: 8px;
  padding: 7px 12px;
  transition: background-color 0.15s ease;
}
button.chip:hover { background: var(--gridline); }

.wrap { max-width: 1180px; margin: 0 auto; padding: 20px 24px; }

/* Hero: the one focal point the page leads with, before any scrolling --
   see dataviz skill's figure spec (>=48px, same sans, exactly one per view). */
.hero { max-width: 1180px; margin: 0 auto; padding: 22px 24px 6px 24px; }
.hero-price-row { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
.hero-price { font-size: 48px; font-weight: 650; line-height: 1; letter-spacing: -0.5px; }
.hero-price-row .delta { font-size: 17px; }
.hero-delta-label { font-size: 12px; color: var(--text-muted); font-weight: 500; margin-left: 4px; }
.hero-rec { display: flex; align-items: center; gap: 10px; margin-top: 12px; }
.hero-rec-badge { font-size: 15px; font-weight: 700; letter-spacing: 0.3px; padding: 5px 14px; border-radius: 8px; }
.hero-rec-badge.good { background: rgba(12,163,12,0.14); color: var(--status-good); }
.hero-rec-badge.critical { background: rgba(208,59,59,0.14); color: var(--status-critical); }
.hero-rec-badge.warning { background: rgba(250,178,25,0.18); color: #7a5200; }
.hero-rec-badge.neutral { background: var(--gridline); color: var(--text-secondary); }
.hero-rec-conf { font-size: 13px; color: var(--text-secondary); }

.kpi-row {
  display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  margin-bottom: 20px;
}
/* Fixed-column-count variants (used where auto-fit's column count would
   otherwise vary awkwardly, e.g. a 3-tile MACD row). Named classes instead
   of inline styles so the mobile media query below can collapse them. */
.kpi-row.cols-2 { grid-template-columns: repeat(2, 1fr); }
.kpi-row.cols-3 { grid-template-columns: repeat(3, 1fr); }
.kpi-row.cols-4 { grid-template-columns: repeat(4, 1fr); }
/* Two sub-panels side by side within one section (distinct from the
   page-level .grid below, which arranges whole section cards). */
.split-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
.split-2col > div { min-width: 0; } /* same grid-item auto-min-width fix, its direct children wrap SVG charts too */
.stat-tile {
  min-width: 0; /* same grid-item auto-min-width fix as .card, see there */
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px 16px;
  box-shadow: 0 1px 2px rgba(11,11,11,0.03);
}
.stat-tile .label { font-size: 12px; color: var(--text-secondary); display: flex; align-items: center; gap: 5px; }
.stat-tile .value { font-size: 24px; font-weight: 650; margin-top: 4px; line-height: 1.15; letter-spacing: -0.2px; }
.stat-tile .value.good { color: var(--status-good); }
.stat-tile .value.critical { color: var(--status-critical); }
.stat-tile .sub { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
.delta { font-weight: 600; }
.delta.good { color: var(--success-text); }
.delta.critical { color: var(--status-critical); }
.delta.neutral { color: var(--text-secondary); }

/* Info icon + popover: a plain-language explainer on every metric */
.info-ic {
  display: inline-flex; align-items: center; justify-content: center;
  width: 15px; height: 15px; border-radius: 50%;
  background: var(--gridline); color: var(--text-secondary);
  font-size: 10px; font-weight: 700; font-style: normal;
  border: none; cursor: pointer; flex-shrink: 0; padding: 0; line-height: 1;
  position: relative; transition: background-color 0.15s ease, color 0.15s ease;
}
.info-ic:hover, .info-ic:focus { background: var(--series-1); color: #fff; outline: none; }
.info-pop {
  display: none; position: absolute; z-index: 100; left: 0; top: 22px;
  width: 240px; max-width: min(240px, calc(100vw - 32px)); background: var(--text-primary); color: var(--surface-1);
  font-size: 12px; font-weight: 400; line-height: 1.5; padding: 10px 12px;
  border-radius: 8px; box-shadow: 0 6px 20px rgba(0,0,0,0.3); text-align: left;
  white-space: normal;
}
.info-ic.is-open .info-pop { display: block; }
h2 .info-ic, .viz-title .info-ic { margin-left: 2px; }

/* At-a-glance plain-language summary */
.glance-list { display: flex; flex-direction: column; gap: 10px; margin: 4px 0 0 0; padding: 0; list-style: none; }
.glance-item {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 12px 14px; border-radius: 10px; background: var(--page-plane);
  border: 1px solid var(--border); font-size: 13.5px; line-height: 1.5;
}
.glance-icon {
  flex-shrink: 0; width: 26px; height: 26px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px; font-weight: 700;
}
.glance-icon.good { background: rgba(12,163,12,0.16); color: var(--status-good); }
.glance-icon.critical { background: rgba(208,59,59,0.16); color: var(--status-critical); }
.glance-icon.neutral { background: var(--gridline); color: var(--text-secondary); }
.glance-item b { font-weight: 700; }

.rec-card {
  background: var(--surface-1); border: 2px solid var(--border);
  border-radius: 14px; padding: 20px 22px; margin-bottom: 20px;
}
.rec-card.rec-good { border-color: var(--status-good); }
.rec-card.rec-critical { border-color: var(--status-critical); }
.rec-card.rec-warning { border-color: var(--status-warning); }
.rec-top { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 16px; }
.rec-badge-big { font-size: 28px; font-weight: 700; letter-spacing: 0.3px; }
.rec-badge-big.good { color: var(--status-good); }
.rec-badge-big.critical { color: var(--status-critical); }
.rec-badge-big.warning { color: #7a5200; }
.rec-badge-big.neutral { color: var(--text-secondary); }
.rec-meta { font-size: 12px; color: var(--text-muted); }
.rec-body { margin-top: 14px; font-size: 14px; line-height: 1.6; }
.rec-risks { margin: 10px 0 0 0; padding-left: 20px; }
.rec-risks li { margin-bottom: 4px; }
.rec-thesis-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 14px; }
.rec-thesis { min-width: 0; background: var(--page-plane); border-radius: 10px; padding: 12px 14px; font-size: 13px; }
.rec-thesis .who { font-weight: 700; font-size: 12px; margin-bottom: 4px; }
.rec-thesis.bull .who { color: var(--status-good); }
.rec-thesis.bear .who { color: var(--status-critical); }
.rec-skeptic { margin-top: 14px; font-size: 13px; }

.rec-trend-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.rec-trend-row:last-child { margin-bottom: 0; }
.rec-trend-period { width: 76px; flex-shrink: 0; font-size: 12px; color: var(--text-secondary); font-variant-numeric: tabular-nums; }
.rec-trend-chart { flex: 1; min-width: 0; }

.grid {
  display: grid; gap: 18px;
  grid-template-columns: repeat(auto-fit, minmax(460px, 1fr));
  align-items: start;
}
.card {
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 14px; padding: 20px 22px;
  /* A quiet, considered look -- a near-invisible shadow for depth, not a
     heavy drop shadow (see dataviz skill: "the data is the only thing
     allowed to be loud"). */
  box-shadow: 0 1px 2px rgba(11,11,11,0.03), 0 1px 10px rgba(11,11,11,0.025);
  /* Grid items default to min-width: auto, meaning a track won't shrink
     below the largest intrinsic content size of anything inside it -- an
     SVG chart with explicit width/height attributes (added for mobile
     Safari's benefit, see .viz-svg below) can set exactly that floor,
     silently forcing this card (and its whole grid track) wider than the
     viewport regardless of any width:100% override further down. This is
     what actually still overflowed on a phone after that fix. */
  min-width: 0;
}
.card.full { grid-column: 1 / -1; }
.card h2 { font-size: 16px; margin: 0 0 4px 0; font-weight: 650; letter-spacing: -0.1px; }
.card .card-sub { font-size: 12.5px; color: var(--text-secondary); margin-bottom: 14px; }

.viz-card { margin-top: 6px; }
.viz-card-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 6px;
}
.viz-card-head .viz-title { font-size: 13px; color: var(--text-secondary); font-weight: 600; }
.viz-toggle {
  font-size: 11px; color: var(--text-secondary); background: none;
  border: 1px solid var(--border); border-radius: 6px; padding: 3px 8px; cursor: pointer;
  transition: background-color 0.15s ease;
}
.viz-toggle:hover { background: var(--gridline); }
.viz-card.is-table-view .viz-chart { display: none; }
.viz-card:not(.is-table-view) .viz-table { display: none; }
.viz-svg { width: 100%; max-width: 100%; height: auto; display: block; }
.viz-legend { display: flex; flex-wrap: wrap; gap: 12px; margin: 8px 0 2px 0; font-size: 12px; color: var(--text-secondary); }
.viz-legend .key { display: inline-flex; align-items: center; gap: 6px; }
.viz-legend .swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.viz-note { font-size: 11.5px; color: var(--text-muted); margin-top: 8px; line-height: 1.5; }

.mark { cursor: pointer; }
.mark:hover, .mark.is-hover { filter: brightness(1.12); }
.mark:focus { outline: 2px solid var(--text-secondary); outline-offset: 2px; }

table.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
table.data-table th, table.data-table td {
  text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--gridline);
  font-variant-numeric: tabular-nums;
}
table.data-table th { color: var(--text-secondary); font-weight: 600; font-size: 12px; }
table.data-table tr:last-child td { border-bottom: none; }
.table-scroll { overflow-x: auto; }

.badge {
  display: inline-block; font-size: 11px; font-weight: 600; padding: 2px 8px;
  border-radius: 999px; white-space: nowrap;
}
.badge.good { background: rgba(12,163,12,0.14); color: var(--status-good); }
.badge.warning { background: rgba(250,178,25,0.18); color: #7a5200; }
.badge.serious { background: rgba(236,131,90,0.18); color: #8a3311; }
.badge.critical { background: rgba(208,59,59,0.14); color: var(--status-critical); }
.badge.neutral { background: var(--gridline); color: var(--text-secondary); }
.badge.info { background: rgba(42,120,214,0.14); color: var(--series-1); }
:root[data-theme="dark"] .badge.warning,
@media (prefers-color-scheme: dark) { .badge.warning { color: #fab219; } .badge.serious { color: #ec835a; } }

.news-item { padding: 10px 0; border-bottom: 1px solid var(--gridline); }
.news-item:last-child { border-bottom: none; }
.news-item .headline { font-weight: 600; font-size: 13.5px; }
.news-item .meta { font-size: 12px; color: var(--text-muted); margin: 2px 0 4px 0; }
.news-item .snippet { font-size: 13px; color: var(--text-secondary); }
.news-item a { color: var(--series-1); text-decoration: none; }
.news-item a:hover { text-decoration: underline; }

.filing-row { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--gridline); }
.filing-row:last-child { border-bottom: none; }
.filing-row .name { width: 130px; font-weight: 600; font-size: 13px; }
.filing-row .info { font-size: 12.5px; color: var(--text-secondary); }

.notes-list { margin: 0; padding: 0; list-style: none; }
.notes-list li { display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--gridline); font-size: 13px; color: var(--text-secondary); }
.notes-list li:last-child { border-bottom: none; }

.empty { color: var(--text-muted); font-size: 13px; font-style: italic; }

.viz-tooltip {
  position: fixed; display: none; z-index: 999; pointer-events: none;
  background: var(--text-primary); color: var(--surface-1);
  font-size: 12px; padding: 6px 10px; border-radius: 6px; max-width: 260px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.25);
}

footer.disclaimer {
  max-width: 1180px; margin: 24px auto 0 auto; padding: 0 24px;
  font-size: 12px; color: var(--text-muted); line-height: 1.6;
}

/* Phones: every fixed-column grid on this page was sized for desktop --
   the page-level .grid's 460px column floor in particular forces the
   whole page to scroll horizontally on any phone screen (observed live on
   an iPhone: page rendered wider than the viewport, content clipped on
   the right). Collapse all of them well before that point. */
@media (max-width: 700px) {
  .wrap { padding: 14px 14px; }
  .topbar { padding: 12px 14px; flex-wrap: wrap; }
  .hero { padding: 16px 14px 4px 14px; }
  .hero-price { font-size: 36px; }
  .grid { grid-template-columns: 1fr !important; }
  .kpi-row { grid-template-columns: repeat(2, 1fr) !important; }
  .kpi-row.cols-4 { grid-template-columns: repeat(2, 1fr) !important; }
  .split-2col, .rec-thesis-grid { grid-template-columns: 1fr !important; }
  .rec-top { flex-direction: column; align-items: flex-start; }

  /* Dense multi-column tables (5-7 columns is common here -- rating
     actions, insider transactions, institutional holders) are cramped or
     horizontal-scrolling on a phone even full-width. Turn each row into a
     small stacked card instead: no JS, data_table() already emits a
     data-label on every <td> for exactly this. */
  table.data-table thead { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0,0,0,0); }
  table.data-table, table.data-table tbody, table.data-table tr, table.data-table td { display: block; width: 100%; }
  table.data-table tr {
    border: 1px solid var(--border); border-radius: 10px;
    padding: 4px 12px; margin-bottom: 10px; background: var(--page-plane);
  }
  table.data-table tr:last-child { margin-bottom: 0; }
  table.data-table td {
    display: flex; justify-content: space-between; align-items: center;
    gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--gridline);
    text-align: right; white-space: normal;
  }
  table.data-table td:last-child { border-bottom: none; }
  table.data-table td::before {
    content: attr(data-label);
    font-size: 11.5px; font-weight: 600; color: var(--text-secondary);
    text-align: left; flex-shrink: 0; padding-right: 12px;
  }
  .table-scroll { overflow-x: visible; }
}
@media (max-width: 420px) {
  .kpi-row, .kpi-row.cols-2, .kpi-row.cols-3, .kpi-row.cols-4 { grid-template-columns: 1fr !important; }
}
"""

JS_SCRIPT = """
(function () {
  var tip = document.createElement('div');
  tip.className = 'viz-tooltip';
  document.body.appendChild(tip);

  function showTip(x, y, text) {
    tip.textContent = text;
    tip.style.display = 'block';
    tip.style.left = (x + 14) + 'px';
    tip.style.top = (y + 14) + 'px';
  }
  function hideTip() { tip.style.display = 'none'; }

  document.addEventListener('mousemove', function (e) {
    var t = e.target.closest && e.target.closest('.mark');
    if (t && t.dataset.tip) {
      showTip(e.clientX, e.clientY, t.dataset.tip);
    } else {
      hideTip();
    }
  });
  document.addEventListener('mouseout', function (e) {
    var t = e.target.closest && e.target.closest('.mark');
    if (t) hideTip();
  });
  document.addEventListener('focusin', function (e) {
    var t = e.target.closest && e.target.closest('.mark');
    if (t && t.dataset.tip) {
      var r = t.getBoundingClientRect();
      showTip(r.left + r.width / 2, r.top, t.dataset.tip);
    }
  });
  document.addEventListener('focusout', function (e) {
    var t = e.target.closest && e.target.closest('.mark');
    if (t) hideTip();
  });

  document.querySelectorAll('.viz-toggle').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var card = btn.closest('.viz-card');
      var nowTable = card.classList.toggle('is-table-view');
      btn.textContent = nowTable ? 'View chart' : 'View as table';
      btn.setAttribute('aria-pressed', String(nowTable));
    });
  });

  var themeBtn = document.getElementById('theme-toggle');
  if (themeBtn) {
    themeBtn.addEventListener('click', function () {
      var root = document.documentElement;
      var current = root.getAttribute('data-theme') ||
        (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      var next = current === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      themeBtn.textContent = next === 'dark' ? 'Light mode' : 'Dark mode';
      try { localStorage.setItem('stockllm-theme', next); } catch (e) {}
    });
  }

  // Info-icon popovers: click/Enter to toggle, click outside or Escape to close,
  // only one open at a time so they never stack up on a long page.
  function closeAllInfo(except) {
    document.querySelectorAll('.info-ic.is-open').forEach(function (el) {
      if (el !== except) el.classList.remove('is-open');
    });
  }
  document.querySelectorAll('.info-ic').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      var wasOpen = btn.classList.contains('is-open');
      closeAllInfo(btn);
      btn.classList.toggle('is-open', !wasOpen);
    });
  });
  document.addEventListener('click', function () { closeAllInfo(null); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeAllInfo(null);
  });
})();
"""

THEME_INIT_SCRIPT = """
(function () {
  try {
    var saved = localStorage.getItem('stockllm-theme');
    if (saved) { document.documentElement.setAttribute('data-theme', saved); }
  } catch (e) {}
})();
"""

SERIES_ROLE = {
    1: "var(--series-1)", 2: "var(--series-2)", 3: "var(--series-3)",
    4: "var(--series-4)", 5: "var(--series-5)", 6: "var(--series-6)",
    7: "var(--series-7)", 8: "var(--series-8)",
}

# ============================================================================
# Plain-language explanations, one per metric/section, written for someone
# with no finance background. Attached via info_icon() -- click the small
# "i" next to any label to read it. Keep these jargon-free and short (2-3
# sentences); anything genuinely ambiguous should say so honestly rather
# than pretend there's a simple good/bad answer.
# ============================================================================

GLOSSARY = {
    "current_price": "The price of one share right now, the last time the market updated.",
    "1y_return": "How much the share price has gone up or down over the past year, if you'd bought it then. Green means it's worth more now, red means less.",
    "pe_ratio": "Price-to-Earnings ratio: how many dollars investors are paying for every $1 of the company's yearly profit. Higher usually means investors expect faster growth ahead; it can also mean the stock is expensive relative to what it currently earns. Shows — if the company lost money, since the math doesn't work with a loss.",
    "market_cap": "The total value of every share of the company added up — shares outstanding × share price. This is what it would cost to buy the whole company at today's price.",
    "rsi": "Relative Strength Index: a 0-100 score for whether a stock has been bought or sold a lot recently, based only on price movement (not the company's actual business). Above 70 is traditionally called \"overbought,\" below 30 \"oversold.\" This is a short-term trading signal, not a verdict on whether the company is good — a strong stock can stay \"overbought\" for a long time.",
    "vix": "The market's \"fear gauge\" — how much price swings investors expect across the whole stock market in the next 30 days, not just this company. Higher means more nervousness/volatility expected market-wide; lower means calmer conditions. This number is the same for every stock, since it's about the whole market, not this company.",
    "treasury_10y": "The interest rate the U.S. government pays to borrow money for 10 years. It matters here because when this rate rises, investors often demand more from stocks too, which tends to hurt expensive/high-growth stocks the most. Same for every stock — it's not about this company.",
    "macd_histogram": "A momentum signal: positive means the stock's short-term trend is strengthening upward, negative means it's weakening or turning down. It reacts to recent price moves, not to news about the business.",
    "price_vs_ma": "Compares today's price to its own average price over the last 20, 50, and 200 trading days (\"moving averages\"), plus the highest/lowest price in the past year. If today's price is above its longer averages, the stock has been in an uptrend recently.",
    "rsi_gauge": "Same RSI number as above, shown on its 0-100 scale so you can see how close it is to the traditional \"oversold\" (below 30) and \"overbought\" (above 70) lines.",
    "analyst_target_range": "Wall Street analysts each publish a 12-month price target for the stock. This shows the lowest, average, and highest of those targets, plus where today's price sits inside that range. A wide range means analysts disagree a lot about where this is headed.",
    "analyst_actions": "Recent individual decisions by analyst firms: upgrading or downgrading their rating, or raising/lowering their price target. This is more detailed than a single \"buy/hold/sell\" consensus — it shows who moved, and when.",
    "eps_surprise": "Each quarter, Wall Street predicts what the company's profit-per-share will be before it's reported. This compares the actual number to that prediction. Green/above the line means the company beat expectations; red/below means it missed.",
    "eps_trend": "How Wall Street's profit predictions for this quarter/year have changed over the last few months. If the \"current\" estimate is higher than it was 90 days ago, analysts have been getting more optimistic — and vice versa.",
    "relative_performance": "The stock's own price return compared to two benchmarks: the S&P 500 (the broad U.S. stock market) and an ETF representing this company's industry sector. This answers \"did this stock actually do better than just owning the market, or did everything go up together?\"",
    "pe_premium": "Compares this company's P/E ratio (see above) to the S&P 500's and to its own sector's. A positive number means investors are paying more per dollar of profit than they would for the average stock in that group — which isn't automatically good or bad, it can mean \"expensive\" or \"expected to grow faster,\" depending on why.",
    "ownership_breakdown": "Who owns the company's shares: big institutions (mutual funds, pension funds, etc.), company insiders (executives/directors), or everyone else (individual retail investors). This is a snapshot today, not a trend.",
    "top_holders": "The five largest institutional shareholders (mutual funds, index funds, etc.) and how many shares each owns.",
    "insider_transactions": "Recent stock activity by the company's own executives and directors, reported to regulators. The \"Nature\" column matters: an \"open market purchase\" is the executive spending their own cash, genuinely read as a vote of confidence. A \"grant or award\" or \"option exercise\" is routine stock-based pay — it also increases how many shares they hold, but it isn't a purchase decision and isn't a confidence signal. \"Open market sale\" is common and often routine (e.g. diversifying, paying taxes on stock awards), so it's less automatically meaningful either.",
    "form144": "Formal notices that a company insider *plans* to sell shares soon (filed before the sale happens). It's an early heads-up, not a confirmation the sale actually went through.",
    "beneficial_ownership": "Filings required when any single investor or firm owns more than 5% of the company. A \"13D\" filer says they may try to influence the company (e.g. an activist investor); a \"13G\" filer is just a passive, along-for-the-ride investor.",
    "balance_sheet": "The company's financial cushion: how much debt it owes, how much cash it has on hand, and whether it generates more cash than it spends (free cash flow). More cash and less debt generally means more room to survive a bad year.",
    "quarterly_financials": "Revenue (total sales) and net income (actual profit after all costs) for each of the last several quarters, so you can see the trend rather than just one snapshot.",
    "dividend_yield": "If the company pays a dividend, this is the yearly payout per share as a percentage of the share price — like a savings-account interest rate, but not guaranteed and can be cut. Shows \"None\" if this company doesn't currently pay one (common for younger/growth-focused companies that reinvest profits instead).",
    "payout_ratio": "What percentage of the company's profit is paid out as dividends rather than kept/reinvested. A very high number can mean the dividend is at risk if profits dip.",
    "buybacks": "Money the company spent buying back its own shares from the stock market. This shrinks the number of shares outstanding, which can boost per-share profit numbers even if total profit doesn't grow.",
    "put_call_ratio": "In the options market, \"puts\" are bets a stock will fall and \"calls\" are bets it will rise. This ratio compares how much of each is being traded — a lot more puts than calls can indicate traders are hedging against or betting on a drop, though it's an imperfect read on sentiment.",
    "iv_skew": "Meant to show whether option traders are paying more for downside protection than upside bets. Flagged unreliable for this data source — see the note below the chart before drawing any conclusion from it.",
    "social_sentiment": "A quick read of recent public posts about this stock on StockTwits (a trading-focused social site), split into self-tagged \"bullish\" (expect it to rise) vs. \"bearish\" (expect it to fall). This is unmoderated public chatter, not analysis — useful as a mood gauge, not as fact.",
    "vix_macro": "See the VIX explanation above — the market-wide fear gauge, shown again here alongside the interest-rate context.",
    "section_price": "Where the price has been and simple technical signals derived purely from price/volume history (not the business itself).",
    "section_analyst": "What professional Wall Street analysts think this stock is worth, and whether their profit estimates have been rising or falling.",
    "section_relative": "How this stock's price and valuation compare to the broader market and its own industry — context that a single number can't give you.",
    "section_financials": "The actual business results: how much money is coming in, how much is profit, and how healthy the balance sheet is.",
    "section_ownership": "Who holds the stock and what company insiders have been doing with their own shares.",
    "section_extras": "A grab-bag of other signals: whether the company returns cash to shareholders, what the options market is pricing in, the broader economic backdrop, and what retail investors are saying online.",
    "ai_recommendation": "The output of StockLLM's own 6-agent pipeline: a Bull agent argues the case to buy, a Bear agent argues the case against, two independent Skeptics (different AI models) critique both for unsupported claims, a Quant Checker verifies the specific numbers cited, and a Judge weighs everything (including all the data below) into one final call. This is the one section that's an AI-generated opinion, not raw data — read the reasoning and key risks, not just the verdict, and remember this is a research aid, not financial advice.",
    "fair_value": "The Judge's estimate of what this stock is worth TODAY, based on the bull/bear cases and the data below — not a prediction of where the price will be at some future date. If the current price is below this range, the AI sees it as undervalued; above the range, overvalued. Treat this the same as the recommendation above: an AI-generated opinion, not a guarantee.",
    "cpi_yoy": "How much prices for everyday goods have risen over the past 12 months, economy-wide — not specific to this company. High inflation tends to pressure the Federal Reserve to keep interest rates higher, which (like the 10Y Treasury yield above) tends to weigh more on expensive/high-growth stocks. Only shown if a free FRED API key is configured.",
    "unemployment_rate": "The percentage of the U.S. workforce currently without a job and looking for one. A rising rate often signals a slowing economy; a falling rate often signals a strong one. Not specific to this company. Only shown if a free FRED API key is configured.",
    "fed_funds_rate": "The interest rate the Federal Reserve sets for banks lending to each other overnight — the actual lever the Fed uses to fight inflation (raise it) or support growth (lower it). Higher rates generally make borrowing more expensive economy-wide, including for this company. Only shown if a free FRED API key is configured.",
    "yield_curve": "The gap between the 10-year and 2-year U.S. Treasury yields. Normally longer loans pay more interest, so this is usually positive. When it goes negative (\"inverted\"), it means investors expect the economy to weaken — historically a widely-watched recession warning sign. Not specific to this company. Only shown if a free FRED API key is configured.",
    "dcf_valuation": "An independent \"discounted cash flow\" fair-value estimate from Financial Modeling Prep — a different valuation method than analyst price targets, estimating what the stock is worth based on projecting the company's future cash flows. A second opinion to compare against the analyst target range and the AI's own fair-value estimate above. Only shown if a free FMP API key is configured.",
    "peg_ratio": "P/E ratio adjusted for the company's growth rate. A P/E of 30 looks expensive on its own, but if earnings are growing 30%/year, a PEG near 1.0 suggests that growth may justify the price. Below 1.0 is traditionally read as potentially undervalued relative to growth; above 2.0 as potentially overvalued. Only shown if a free FMP API key is configured.",
    "insider_sentiment_mspr": "Finnhub's own monthly score for whether company insiders (executives, directors) were net buying or net selling their own stock recently — positive means more buying, negative means more selling. A different, summarized view on top of the individual insider trades listed below. Only shown if the same Finnhub key used for news is configured.",
    "recommendation_trend": "How many analysts rated this stock Strong Buy/Buy/Hold/Sell/Strong Sell in recent months, and whether that mix is improving or deteriorating over time — a trend, not just a single snapshot. A different view than the individual rating actions listed elsewhere. Only shown if a Finnhub key is configured.",
}


def info_icon(key: str) -> str:
    """A small clickable "i" that shows a plain-language explanation of the
    metric next to it. Falls back to nothing (not a broken icon) if the key
    isn't in the glossary, so a typo'd key fails quietly rather than showing
    an empty popover."""
    text = GLOSSARY.get(key)
    if not text:
        return ""
    return (
        f'<button type="button" class="info-ic" aria-label="What does this mean?" aria-haspopup="true">'
        f'i<span class="info-pop" role="tooltip">{esc(text)}</span></button>'
    )


# ============================================================================
# Formatting helpers
# ============================================================================

def esc(value) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def fmt_compact(v, decimals=2):
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return esc(v)
    av = abs(v)
    if av >= 1e12:
        return f"{v/1e12:.{decimals}f}T"
    if av >= 1e9:
        return f"{v/1e9:.{decimals}f}B"
    if av >= 1e6:
        return f"{v/1e6:.{decimals}f}M"
    if av >= 1e3:
        return f"{v/1e3:.1f}K"
    if float(v).is_integer():
        return f"{v:,.0f}"
    return f"{v:,.2f}"


def fmt_usd(v, decimals=2):
    if v is None:
        return "—"
    compact = fmt_compact(v, decimals)
    return f"-${compact[1:]}" if compact.startswith("-") else f"${compact}"


def fmt_price(v):
    if v is None:
        return "—"
    return f"${v:,.2f}"


def fmt_pct(v, signed=True, decimals=1):
    if v is None:
        return "—"
    sign = "+" if signed and v > 0 else ""
    return f"{sign}{v:.{decimals}f}%"


def fmt_num(v, decimals=0):
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{decimals}f}"
    except (TypeError, ValueError):
        return esc(v)


def delta_class(v, invert=False):
    if v is None:
        return "neutral"
    x = -v if invert else v
    if x > 0:
        return "good"
    if x < 0:
        return "critical"
    return "neutral"


def rsi_class(v):
    """Conventional RSI reading, colored for a quick glance: below 30
    ("oversold") green, above 70 ("overbought") red, the 30-70 middle
    neutral. Simplified on purpose for readers who just want a quick
    green/red signal -- the info tooltip on this metric spells out that
    it's a short-term momentum reading, not a verdict on the company."""
    if v is None:
        return None
    if v < 30:
        return "good"
    if v > 70:
        return "critical"
    return None


# ============================================================================
# SVG primitives -- rounded "data end", square at the baseline (see
# marks-and-anatomy.md). Built as explicit paths since a plain <rect rx>
# rounds all four corners.
# ============================================================================

def _hbar_path(x0, y0, w, h, r=4):
    """Horizontal bar growing rightward from baseline x0. Rounded right end,
    square left end (the baseline). If w is negative, grows leftward with
    the rounding mirrored (for diverging charts)."""
    if w == 0:
        return ""
    r = min(r, abs(w), h / 2)
    if w > 0:
        x1 = x0 + w
        return (
            f"M {x0} {y0} H {x1-r} Q {x1} {y0} {x1} {y0+r} "
            f"V {y0+h-r} Q {x1} {y0+h} {x1-r} {y0+h} H {x0} Z"
        )
    else:
        x1 = x0 + w  # to the left
        return (
            f"M {x0} {y0} H {x1+r} Q {x1} {y0} {x1} {y0+r} "
            f"V {y0+h-r} Q {x1} {y0+h} {x1+r} {y0+h} H {x0} Z"
        )


def _rect_path(x, y, w, h, rtl=0, rtr=0, rbr=0, rbl=0):
    """Rectangle with independently controllable corner radii (top-left,
    top-right, bottom-right, bottom-left) -- for stacked-bar segments, where
    only the outermost corners of the whole stack should be rounded."""
    x1, y1 = x + w, y + h
    return (
        f"M {x+rtl} {y} "
        f"H {x1-rtr} " + (f"Q {x1} {y} {x1} {y+rtr} " if rtr else f"L {x1} {y} ") +
        f"V {y1-rbr} " + (f"Q {x1} {y1} {x1-rbr} {y1} " if rbr else f"L {x1} {y1} ") +
        f"H {x+rbl} " + (f"Q {x} {y1} {x} {y1-rbl} " if rbl else f"L {x} {y1} ") +
        f"V {y+rtl} " + (f"Q {x} {y} {x+rtl} {y} " if rtl else f"L {x} {y} ") +
        "Z"
    )


def _vbar_path(x0, y_base, w, h, r=4):
    """Vertical column growing upward from baseline y_base. Rounded top,
    square bottom."""
    if h <= 0:
        return ""
    r = min(r, w / 2, h)
    y0 = y_base - h
    return (
        f"M {x0} {y_base} V {y0+r} Q {x0} {y0} {x0+r} {y0} "
        f"H {x0+w-r} Q {x0+w} {y0} {x0+w} {y0+r} V {y_base} Z"
    )


def _mark(path_d, color, tip, extra_class="", opacity=1.0):
    tip_attr = esc(tip)
    opacity_attr = f' opacity="{opacity:.2f}"' if opacity < 1.0 else ""
    return (
        f'<g class="mark {extra_class}" tabindex="0" data-tip="{tip_attr}">'
        f'<title>{tip_attr}</title>'
        f'<path d="{path_d}" fill="{color}"{opacity_attr}/></g>'
    )


# ============================================================================
# Components
# ============================================================================

def stat_tile(label, value, sub=None, delta_text=None, delta_cls="neutral", info=None, value_cls=None):
    icon = info_icon(info) if info else ""
    parts = [f'<div class="stat-tile"><div class="label">{esc(label)}{icon}</div>']
    value_class = f" {value_cls}" if value_cls else ""
    parts.append(f'<div class="value{value_class}">{esc(value)}</div>')
    if delta_text:
        parts.append(f'<div class="sub"><span class="delta {delta_cls}">{esc(delta_text)}</span></div>')
    elif sub:
        parts.append(f'<div class="sub">{esc(sub)}</div>')
    parts.append("</div>")
    return "".join(parts)


def badge(text, status="neutral"):
    return f'<span class="badge {status}">{esc(text)}</span>'


def empty_state(msg="No data available for this ticker."):
    return f'<div class="empty">{esc(msg)}</div>'


def data_table(headers, rows):
    """
    Renders a data table that also works as a mobile card-list: every <td>
    carries a data-label attribute (its column header), which a mobile media
    query uses to render each row as a small stacked "label: value" card
    instead of a cramped horizontally-scrolling table -- see .data-table's
    max-width: 640px rule in CSS_STYLE. No JS, pure CSS.
    """
    if not rows:
        return empty_state()
    thead = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body_rows = []
    for r in rows:
        cells = "".join(
            f'<td data-label="{esc(h)}">{c if isinstance(c, str) and c.startswith("<span") else esc(c)}</td>'
            for h, c in zip(headers, r)
        )
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        '<div class="table-scroll"><table class="data-table">'
        f"<thead><tr>{thead}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"
    )


def viz_card(title, chart_svg, table_html, legend_html="", note="", info=None):
    icon = info_icon(info) if info else ""
    return f"""
<div class="viz-card">
  <div class="viz-card-head">
    <span class="viz-title">{esc(title)}{icon}</span>
    <button type="button" class="viz-toggle" aria-pressed="false">View as table</button>
  </div>
  <div class="viz-chart">{chart_svg}{legend_html}</div>
  <div class="viz-table">{table_html}</div>
  {f'<div class="viz-note">{esc(note)}</div>' if note else ''}
</div>"""


def legend(items):
    """items: list of (label, color_css_var)"""
    keys = "".join(
        f'<span class="key"><span class="swatch" style="background:{color}"></span>{esc(label)}</span>'
        for label, color in items
    )
    return f'<div class="viz-legend">{keys}</div>'


# ============================================================================
# Charts
# ============================================================================

def bar_chart_horizontal(items, unit="", value_fmt=None):
    """items: list of (label, value). Single series, magnitude comparison."""
    items = [it for it in items if it[1] is not None]
    if not items:
        return "<svg></svg>", empty_state()
    value_fmt = value_fmt or (lambda v: fmt_num(v, 2))
    max_v = max(abs(v) for _, v in items) or 1
    row_h, gap, pad = 22, 12, 16
    label_w, tail_w = 150, 90
    W = 620
    bar_area = W - label_w - tail_w
    H = pad * 2 + len(items) * (row_h + gap) - gap

    parts = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" class="viz-svg" role="img" aria-label="{esc(unit or "bar chart")}">']
    y = pad
    for label, v in items:
        w = (abs(v) / max_v) * bar_area
        d = _hbar_path(label_w, y, w, row_h)
        tip = f"{label}: {value_fmt(v)}"
        parts.append(f'<text x="{label_w-8}" y="{y+row_h/2+4}" text-anchor="end" font-size="12" fill="var(--text-secondary)">{esc(label)}</text>')
        parts.append(_mark(d, "var(--series-1)", tip))
        parts.append(f'<text x="{label_w+w+8}" y="{y+row_h/2+4}" font-size="12" fill="var(--text-primary)">{esc(value_fmt(v))}</text>')
        y += row_h + gap
    parts.append("</svg>")

    rows = [[label, value_fmt(v)] for label, v in items]
    table = data_table(["Metric", "Value"], rows)
    return "".join(parts), table


MIN_BAR_WIDTH_FOR_INSIDE_LABEL = 46


def _diverging_value_label(center, w, is_positive, y, row_h, text, mark_color):
    """Places a bar's value label just outside its tip -- UNLESS the bar is
    long enough to approach the row-label column on its own side, in which
    case the label goes inside the bar (light text on the fill) instead.
    Fixes a real overlap: outside-only placement put a long negative bar's
    label right on top of that row's own name label (observed live: MBLY's
    -42.6% 1-year return)."""
    long_enough = w >= MIN_BAR_WIDTH_FOR_INSIDE_LABEL
    if is_positive:
        x = (center + w - 6) if long_enough else (center + w + 6)
        anchor = "end" if long_enough else "start"
    else:
        x = (center - w + 6) if long_enough else (center - w - 6)
        anchor = "start" if long_enough else "end"
    fill = "#fff" if long_enough else "var(--text-primary)"
    return f'<text x="{x}" y="{y+row_h/2+4}" text-anchor="{anchor}" font-size="12" font-weight="{"600" if long_enough else "400"}" fill="{fill}">{esc(text)}</text>'


def diverging_bar_horizontal(items, value_fmt=None):
    """items: list of (label, value) where value can be +/-. Baseline at center."""
    items = [it for it in items if it[1] is not None]
    if not items:
        return "<svg></svg>", empty_state(), ""
    value_fmt = value_fmt or (lambda v: fmt_pct(v))
    max_v = max(abs(v) for _, v in items) or 1
    row_h, gap, pad = 22, 12, 16
    label_w = 110
    W = 620
    half = (W - label_w - 20) / 2
    center = label_w + half
    H = pad * 2 + len(items) * (row_h + gap) - gap

    parts = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" class="viz-svg" role="img" aria-label="values relative to baseline">']
    parts.append(f'<line x1="{center}" y1="{pad-6}" x2="{center}" y2="{H-pad+6}" stroke="var(--baseline)" stroke-width="1"/>')
    y = pad
    for label, v in items:
        w = (abs(v) / max_v) * (half - 10)
        color = "var(--diverge-pos)" if v >= 0 else "var(--diverge-neg)"
        x0 = center if v >= 0 else center
        d = _hbar_path(x0, y, w if v >= 0 else -w, row_h)
        tip = f"{label}: {value_fmt(v)}"
        parts.append(f'<text x="{label_w-8}" y="{y+row_h/2+4}" text-anchor="end" font-size="12" fill="var(--text-secondary)">{esc(label)}</text>')
        parts.append(_mark(d, color, tip))
        parts.append(_diverging_value_label(center, w, v >= 0, y, row_h, value_fmt(v), color))
        y += row_h + gap
    parts.append("</svg>")

    rows = [[label, value_fmt(v)] for label, v in items]
    table = data_table(["Period", "Value"], rows)
    leg = legend([("Beat / above baseline", "var(--diverge-pos)"), ("Miss / below baseline", "var(--diverge-neg)")])
    return "".join(parts), table, leg


def grouped_bar_horizontal(groups, value_fmt=None):
    """groups: list of (group_title, [(series_name, color_var, value), ...]) --
    e.g. one group per time window, each with one bar per series (stock vs.
    benchmark vs. sector), colored by series identity (categorical), not by
    sign. Bars grow from a shared center baseline in the correct direction
    for the value's sign -- unlike a plain magnitude bar, a negative value
    visibly grows the opposite way, not just via its text label. Use this
    whenever the job is "tell distinct series apart, AND the series can be
    positive or negative" (e.g. returns); use bar_chart_horizontal for a
    single-series magnitude comparison, diverging_bar_horizontal for one
    series against a baseline."""
    value_fmt = value_fmt or (lambda v: fmt_pct(v))
    all_vals = [v for _, items in groups for _, _, v in items if v is not None]
    if not all_vals:
        return "<svg></svg>", empty_state(), ""
    max_abs = max(abs(v) for v in all_vals) or 1

    row_h, gap, group_gap, header_h, pad = 20, 8, 22, 22, 16
    label_w = 130
    W = 620
    half = (W - label_w - 20) / 2
    center = label_w + half

    H = pad
    for _, items in groups:
        H += header_h + len(items) * (row_h + gap) - gap + group_gap
    H = H - group_gap + pad

    parts = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" class="viz-svg" role="img" aria-label="grouped comparison chart">']
    parts.append(f'<line x1="{center}" y1="{pad}" x2="{center}" y2="{H-pad}" stroke="var(--baseline)" stroke-width="1"/>')

    y = pad
    for group_title, items in groups:
        parts.append(f'<text x="{label_w}" y="{y+12}" font-size="12" font-weight="600" fill="var(--text-primary)">{esc(group_title)}</text>')
        y += header_h
        for name, color, v in items:
            if v is None:
                y += row_h + gap
                continue
            w = (abs(v) / max_abs) * (half - 10)
            d = _hbar_path(center, y, w if v >= 0 else -w, row_h)
            tip = f"{name} — {group_title}: {value_fmt(v)}"
            parts.append(f'<text x="{label_w-8}" y="{y+row_h/2+4}" text-anchor="end" font-size="12" fill="var(--text-secondary)">{esc(name)}</text>')
            parts.append(_mark(d, color, tip))
            parts.append(_diverging_value_label(center, w, v >= 0, y, row_h, value_fmt(v), color))
            y += row_h + gap
        y += group_gap - gap
    parts.append("</svg>")

    rows = []
    for group_title, items in groups:
        for name, _, v in items:
            rows.append([group_title, name, value_fmt(v) if v is not None else "—"])
    table = data_table(["Period", "Series", "Value"], rows)
    leg_items = groups[0][1] if groups else []
    leg = legend([(name, color) for name, color, _ in leg_items])
    return "".join(parts), table, leg


def grouped_column_chart(categories, series):
    """categories: list of str (x-axis). series: list of (name, color_var, [values])."""
    n_cat = len(categories)
    if n_cat == 0:
        return "<svg></svg>", empty_state(), ""
    all_vals = [v for _, _, vals in series for v in vals if v is not None]
    if not all_vals:
        return "<svg></svg>", empty_state(), ""
    max_v = max(all_vals)
    min_v = min(0, min(all_vals))
    span = (max_v - min_v) or 1

    W, H = 620, 260
    pad_l, pad_b, pad_t = 46, 30, 14
    plot_w = W - pad_l - 16
    plot_h = H - pad_b - pad_t
    slot_w = plot_w / n_cat
    n_series = len(series)
    bar_gap = 2
    bar_w = min(24, (slot_w - 16 - bar_gap * (n_series - 1)) / n_series)

    def y_for(v):
        return pad_t + plot_h - ((v - min_v) / span) * plot_h

    baseline_y = y_for(0)
    parts = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" class="viz-svg" role="img" aria-label="grouped column chart">']
    # gridlines at 0, mid, max
    for gv in [min_v, (min_v + max_v) / 2, max_v]:
        gy = y_for(gv)
        parts.append(f'<line x1="{pad_l}" y1="{gy}" x2="{W-16}" y2="{gy}" stroke="var(--gridline)" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l-6}" y="{gy+3}" text-anchor="end" font-size="10" fill="var(--text-muted)">{fmt_compact(gv,1)}</text>')

    for ci, cat in enumerate(categories):
        group_x0 = pad_l + ci * slot_w + (slot_w - (bar_w * n_series + bar_gap * (n_series - 1))) / 2
        for si, (name, color, vals) in enumerate(series):
            v = vals[ci] if ci < len(vals) else None
            if v is None:
                continue
            x = group_x0 + si * (bar_w + bar_gap)
            h = abs(y_for(v) - baseline_y)
            y0 = min(y_for(v), baseline_y)
            d = _vbar_path(x, y0 + h, bar_w, h)
            tip = f"{cat} — {name}: {fmt_usd(v)}"
            parts.append(_mark(d, color, tip))
            if ci == n_cat - 1:  # direct label on the last/most-recent category only
                parts.append(f'<text x="{x+bar_w/2}" y="{y0-6}" text-anchor="middle" font-size="10" fill="var(--text-primary)">{fmt_usd(v,1)}</text>')
        parts.append(f'<text x="{group_x0 + (bar_w*n_series+bar_gap*(n_series-1))/2}" y="{H-8}" text-anchor="middle" font-size="11" fill="var(--text-secondary)">{esc(cat)}</text>')
    parts.append(f'<line x1="{pad_l}" y1="{baseline_y}" x2="{W-16}" y2="{baseline_y}" stroke="var(--baseline)" stroke-width="1"/>')
    parts.append("</svg>")

    headers = ["Quarter"] + [name for name, _, _ in series]
    rows = []
    for ci, cat in enumerate(categories):
        row = [cat] + [fmt_usd(vals[ci]) if ci < len(vals) and vals[ci] is not None else "—" for _, _, vals in series]
        rows.append(row)
    table = data_table(headers, rows)
    leg = legend([(name, color) for name, color, _ in series])
    return "".join(parts), table, leg


def range_meter(low, mean, median, high, current, label_fmt=fmt_price):
    """Analyst target range: a track from low to high with mean/median/current markers."""
    if low is None or high is None or high <= low:
        return "<svg></svg>", empty_state()
    W, H = 620, 90
    pad = 60
    track_x0, track_x1 = pad, W - pad
    track_w = track_x1 - track_x0
    track_y = 46

    def x_for(v):
        v = max(low, min(high, v))
        return track_x0 + (v - low) / (high - low) * track_w

    parts = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" class="viz-svg" role="img" aria-label="analyst target price range">']
    parts.append(f'<text x="{track_x0}" y="20" font-size="12" fill="var(--text-secondary)">Low {label_fmt(low)}</text>')
    parts.append(f'<text x="{track_x1}" y="20" text-anchor="end" font-size="12" fill="var(--text-secondary)">High {label_fmt(high)}</text>')
    d = _hbar_path(track_x0, track_y - 5, track_w, 10, r=5)
    parts.append(f'<path d="{d}" fill="var(--gridline)"/>')

    markers = []
    if mean is not None:
        markers.append(("Mean", mean, "var(--series-1)"))
    if median is not None and median != mean:
        markers.append(("Median", median, "var(--series-3)"))
    for name, v, color in markers:
        x = x_for(v)
        parts.append(f'<g class="mark" tabindex="0" data-tip="{esc(name)}: {esc(label_fmt(v))}"><title>{esc(name)}: {esc(label_fmt(v))}</title>'
                      f'<circle cx="{x}" cy="{track_y}" r="6" fill="{color}" stroke="var(--surface-1)" stroke-width="2"/></g>')
        parts.append(f'<text x="{x}" y="{track_y+26}" text-anchor="middle" font-size="10.5" fill="var(--text-secondary)">{esc(name)}</text>')

    if current is not None:
        x = x_for(current)
        parts.append(f'<g class="mark" tabindex="0" data-tip="Current: {esc(label_fmt(current))}"><title>Current: {esc(label_fmt(current))}</title>'
                      f'<path d="M {x-6} {track_y-16} L {x+6} {track_y-16} L {x} {track_y-6} Z" fill="var(--text-primary)"/></g>')
        parts.append(f'<text x="{x}" y="{track_y-20}" text-anchor="middle" font-size="10.5" font-weight="600" fill="var(--text-primary)">Current</text>')
    parts.append("</svg>")

    rows = [["Low", label_fmt(low)], ["Mean", label_fmt(mean)], ["Median", label_fmt(median)],
            ["High", label_fmt(high)], ["Current price", label_fmt(current)]]
    table = data_table(["Point", "Price"], rows)
    return "".join(parts), table


def gauge_meter(value, min_v, max_v, zones, label=""):
    """zones: list of (threshold_upto, color_var, status_name) covering min_v..max_v in order."""
    if value is None:
        return "<svg></svg>", empty_state()
    W, H = 620, 70
    pad = 20
    track_x0, track_x1 = pad, W - pad
    track_w = track_x1 - track_x0
    track_y = 30

    def x_for(v):
        v = max(min_v, min(max_v, v))
        return track_x0 + (v - min_v) / (max_v - min_v) * track_w

    parts = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" class="viz-svg" role="img" aria-label="{esc(label)} gauge">']
    prev = min_v
    for upto, color, _ in zones:
        x0, x1 = x_for(prev), x_for(upto)
        w = max(x1 - x0, 0)
        if w > 0:
            parts.append(f'<rect x="{x0}" y="{track_y-6}" width="{w}" height="12" fill="{color}" opacity="0.85"/>')
        prev = upto
    x = x_for(value)
    parts.append(f'<g class="mark" tabindex="0" data-tip="{esc(label)}: {esc(fmt_num(value,1))}"><title>{esc(label)}: {esc(fmt_num(value,1))}</title>'
                  f'<circle cx="{x}" cy="{track_y}" r="7" fill="var(--text-primary)" stroke="var(--surface-1)" stroke-width="2"/></g>')
    parts.append(f'<text x="{x}" y="{track_y-14}" text-anchor="middle" font-size="12" font-weight="600" fill="var(--text-primary)">{esc(fmt_num(value,1))}</text>')
    parts.append(f'<text x="{track_x0}" y="{track_y+28}" font-size="11" fill="var(--text-muted)">{esc(fmt_num(min_v))}</text>')
    parts.append(f'<text x="{track_x1}" y="{track_y+28}" text-anchor="end" font-size="11" fill="var(--text-muted)">{esc(fmt_num(max_v))}</text>')
    parts.append("</svg>")

    table = data_table(["Metric", "Value"], [[label, fmt_num(value, 1)]])
    return "".join(parts), table


def stacked_bar_parts(parts_data, total=100.0):
    """parts_data: list of (label, value, color_var). Renders one horizontal stacked bar."""
    parts_data = [(l, v, c) for l, v, c in parts_data if v is not None and v > 0]
    if not parts_data:
        return "<svg></svg>", empty_state(), ""
    W, H = 620, 60
    pad = 8
    bar_y, bar_h = 20, 24
    bar_w = W - pad * 2
    gap = 2

    parts = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" class="viz-svg" role="img" aria-label="ownership breakdown">']
    x = pad
    n = len(parts_data)
    r = 4
    for i, (label, v, color) in enumerate(parts_data):
        seg_w = max((v / total) * bar_w - (gap if i < n - 1 else 0), 0)
        is_first, is_last = i == 0, i == n - 1
        d = _rect_path(
            x, bar_y, seg_w, bar_h,
            rtl=r if is_first else 0, rbl=r if is_first else 0,
            rtr=r if is_last else 0, rbr=r if is_last else 0,
        )
        tip = f"{label}: {fmt_pct(v, signed=False)}"
        parts.append(_mark(d, color, tip))
        x += seg_w + gap
    parts.append("</svg>")

    rows = [[label, fmt_pct(v, signed=False)] for label, v, _ in parts_data]
    table = data_table(["Holder type", "% of shares"], rows)
    leg = legend([(label, color) for label, _, color in parts_data])
    return "".join(parts), table, leg


def diverging_stacked_sentiment(bearish, untagged, bullish):
    """Diverging stacked bar centered on the neutral/untagged middle segment."""
    total = (bearish or 0) + (untagged or 0) + (bullish or 0)
    if total == 0:
        return "<svg></svg>", empty_state(), ""
    W, H = 620, 70
    bar_y, bar_h = 24, 26
    center_x = W / 2
    mid_w = (untagged / total) * (W - 40)
    left_w = (bearish / total) * (W - 40)
    right_w = (bullish / total) * (W - 40)

    mid_x0 = center_x - mid_w / 2
    parts = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" class="viz-svg" role="img" aria-label="social sentiment split">']
    parts.append(f'<line x1="{center_x}" y1="{bar_y-6}" x2="{center_x}" y2="{bar_y+bar_h+6}" stroke="var(--baseline)" stroke-width="1"/>')

    if mid_w > 0:
        d = _hbar_path(mid_x0, bar_y, mid_w, bar_h, r=0)
        parts.append(_mark(d, "var(--gridline)", f"Untagged: {untagged} messages"))
    if left_w > 0:
        d = _hbar_path(mid_x0 - 2, bar_y, -left_w, bar_h)
        parts.append(_mark(d, "var(--diverge-neg)", f"Bearish: {bearish} messages"))
    if right_w > 0:
        d = _hbar_path(mid_x0 + mid_w + 2, bar_y, right_w, bar_h)
        parts.append(_mark(d, "var(--diverge-pos)", f"Bullish: {bullish} messages"))

    parts.append(f'<text x="{mid_x0-left_w-8}" y="{bar_y+bar_h/2+4}" text-anchor="end" font-size="12" fill="var(--text-primary)">{bearish}</text>')
    parts.append(f'<text x="{mid_x0+mid_w+right_w+10}" y="{bar_y+bar_h/2+4}" font-size="12" fill="var(--text-primary)">{bullish}</text>')
    parts.append("</svg>")

    table = data_table(["Sentiment", "Messages"], [["Bearish", bearish], ["Untagged", untagged], ["Bullish", bullish]])
    leg = legend([("Bearish", "var(--diverge-neg)"), ("Untagged", "var(--gridline)"), ("Bullish", "var(--diverge-pos)")])
    return "".join(parts), table, leg


def diverging_stacked_ordinal(neg_segments, mid_value, pos_segments, mid_label="Neutral", aria_label="distribution"):
    """
    Diverging stacked bar for an ordered categorical scale (Likert-style --
    e.g. Strong Sell/Sell/Hold/Buy/Strong Buy), centered on the neutral
    middle segment. This is the skill's recommended form for "ordered-scale
    share" (see dataviz skill's choosing-a-form.md) -- a generalization of
    diverging_stacked_sentiment above to more than one segment per side.

    neg_segments / pos_segments: ordered list of (label, value), closest-to-
    neutral first, most extreme last -- stacked outward from the center.
    Same 2-hue-plus-neutral-gray convention as diverging_stacked_sentiment:
    graduated opacity (not a new hue) distinguishes "strong" from "regular"
    within a side, so this stays colorblind-safe -- only diverge-pos,
    diverge-neg, and gridline are ever used as actual hues.
    """
    total = (mid_value or 0) + sum(v or 0 for _, v in neg_segments) + sum(v or 0 for _, v in pos_segments)
    if total == 0:
        return "<svg></svg>", empty_state(), ""

    W, H = 620, 70
    bar_y, bar_h = 24, 26
    center_x = W / 2
    usable_w = W - 40
    mid_w = ((mid_value or 0) / total) * usable_w
    mid_x0 = center_x - mid_w / 2

    parts = [f'<svg viewBox="0 0 {W} {H}" width="{W}" height="{H}" class="viz-svg" role="img" aria-label="{esc(aria_label)}">']
    parts.append(f'<line x1="{center_x}" y1="{bar_y-6}" x2="{center_x}" y2="{bar_y+bar_h+6}" stroke="var(--baseline)" stroke-width="1"/>')

    if mid_w > 0:
        d = _hbar_path(mid_x0, bar_y, mid_w, bar_h, r=0)
        parts.append(_mark(d, "var(--gridline)", f"{mid_label}: {fmt_num(mid_value)}"))

    # Direct-label selectively (skill guidance: the endpoint/extreme, not
    # every segment) -- each side's outer edge gets its running total,
    # matching diverging_stacked_sentiment's convention above.
    n_neg = len([1 for _, v in neg_segments if v])
    x = mid_x0 - 2
    neg_total = 0
    for i, (label, v) in enumerate(seg for seg in neg_segments if seg[1]):
        seg_w = (v / total) * usable_w
        opacity = 0.55 + 0.45 * ((i + 1) / n_neg)
        d = _hbar_path(x, bar_y, -seg_w, bar_h)
        parts.append(_mark(d, "var(--diverge-neg)", f"{label}: {fmt_num(v)}", opacity=opacity))
        x -= seg_w + 2
        neg_total += v
    if neg_total:
        parts.append(f'<text x="{x+2-6}" y="{bar_y+bar_h/2+4}" text-anchor="end" font-size="12" fill="var(--text-primary)">{fmt_num(neg_total)}</text>')

    n_pos = len([1 for _, v in pos_segments if v])
    x = mid_x0 + mid_w + 2
    pos_total = 0
    for i, (label, v) in enumerate(seg for seg in pos_segments if seg[1]):
        seg_w = (v / total) * usable_w
        opacity = 0.55 + 0.45 * ((i + 1) / n_pos)
        d = _hbar_path(x, bar_y, seg_w, bar_h)
        parts.append(_mark(d, "var(--diverge-pos)", f"{label}: {fmt_num(v)}", opacity=opacity))
        x += seg_w + 2
        pos_total += v
    if pos_total:
        parts.append(f'<text x="{x-2+8}" y="{bar_y+bar_h/2+4}" font-size="12" fill="var(--text-primary)">{fmt_num(pos_total)}</text>')

    parts.append("</svg>")

    rows = (
        [[label, fmt_num(v)] for label, v in reversed(neg_segments)]
        + [[mid_label, fmt_num(mid_value)]]
        + [[label, fmt_num(v)] for label, v in pos_segments]
    )
    table = data_table(["Category", "Count"], rows)
    leg_items = (
        [(label, "var(--diverge-neg)") for label, _ in neg_segments]
        + [(mid_label, "var(--gridline)")]
        + [(label, "var(--diverge-pos)") for label, _ in pos_segments]
    )
    leg = legend(leg_items)
    return "".join(parts), table, leg


# ============================================================================
# Sections
# ============================================================================

def section_header(bundle):
    ticker = bundle.get("ticker", "?")
    fetched_at = bundle.get("fetched_at", "")
    return f"""
<div class="topbar">
  <div>
    <h1>{esc(ticker)} — Research Dashboard</h1>
    <div class="meta">Bundle fetched {esc(fetched_at)} · StockLLM (research/decision-support only, not financial advice)</div>
  </div>
  <div class="topbar-actions">
    <button type="button" class="chip" id="theme-toggle">Dark mode</button>
  </div>
</div>"""


_NAV_ITEMS = [
    ("sec-price", "Price"),
    ("sec-analyst", "Analyst"),
    ("sec-relative", "Performance"),
    ("sec-ownership", "Ownership"),
    ("sec-financials", "Financials"),
    ("sec-extras", "Dividends"),
    ("sec-news", "News"),
    ("sec-filings", "Filings"),
]


def section_nav(bundle):
    """
    A jump-to-section pill bar, primarily a mobile affordance (hidden on
    wide desktop viewports where the eye can already scan the whole page --
    see the min-width: 900px rule in CSS_STYLE) so a phone reader isn't
    stuck scrolling through 9 sections to find the one they want.
    """
    links = "".join(f'<a href="#{anchor}">{esc(label)}</a>' for anchor, label in _NAV_ITEMS)
    return f'<nav class="section-nav" aria-label="Jump to section">{links}</nav>'


def section_hero(bundle, pipeline_result=None):
    """
    The one focal point the page leads with -- current price at true hero
    size (dataviz skill spec: >=48px, same sans as everything else, exactly
    one per view) plus its 20-day move, and the AI verdict badge if a full
    (non-dry-run) run was made. Everything else (KPIs, at-a-glance, the 9
    section cards) follows below -- this is what's visible before any
    scrolling on a phone.
    """
    price = bundle.get("price", {}) or {}
    current_price = price.get("current_price")
    pct_20d = price.get("pct_change_20d")

    rec_html = ""
    if pipeline_result:
        judge = pipeline_result.get("judge", {}) or {}
        rec_key = (judge.get("recommendation") or "hold").lower()
        rec_cls, rec_label = _REC_STYLE.get(rec_key, ("neutral", rec_key.upper()))
        confidence = judge.get("confidence")
        conf_html = f'<span class="hero-rec-conf">{esc(confidence)}% confidence</span>' if confidence is not None else ""
        rec_html = f"""
  <div class="hero-rec">
    <span class="hero-rec-badge {rec_cls}">{esc(rec_label)}</span>
    {conf_html}
  </div>"""

    return f"""
<div class="hero">
  <div class="hero-price-row">
    <span class="hero-price">{fmt_price(current_price)}</span>
    <span class="delta {delta_class(pct_20d)}">{fmt_pct(pct_20d)}<span class="hero-delta-label">20d</span></span>
  </div>{rec_html}
</div>"""


def _glance_item(icon_cls, icon_char, html_text):
    return f'<li class="glance-item"><span class="glance-icon {icon_cls}">{icon_char}</span><span>{html_text}</span></li>'


_REC_STYLE = {
    "buy": ("good", "BUY"),
    "sell": ("critical", "SELL"),
    "hold": ("neutral", "HOLD"),
    "insufficient_data": ("warning", "INSUFFICIENT DATA"),
}


def section_ai_recommendation(bundle, pipeline_result):
    """
    Renders the 6-agent pipeline's actual output (only present for a full,
    non-dry-run check) -- the one section of this dashboard that's an AI
    opinion rather than raw data. See GLOSSARY['ai_recommendation'] for the
    user-facing framing; this function just lays it out.
    """
    judge = pipeline_result.get("judge", {}) or {}
    bull = pipeline_result.get("bull", {}) or {}
    bear = pipeline_result.get("bear", {}) or {}
    skeptic = pipeline_result.get("skeptic", {}) or {}
    skeptic_qwen = pipeline_result.get("skeptic_qwen", {}) or {}
    quant_check = pipeline_result.get("quant_check", {}) or {}

    rec_key = (judge.get("recommendation") or "hold").lower()
    rec_cls, rec_label = _REC_STYLE.get(rec_key, ("neutral", rec_key.upper()))
    confidence = judge.get("confidence")

    risks_html = "".join(f"<li>{esc(r)}</li>" for r in judge.get("key_risks", []) or []) or "<li>None flagged.</li>"

    fv_low, fv_high = judge.get("fair_value_low"), judge.get("fair_value_high")
    fv_html = ""
    if fv_low is not None and fv_high is not None:
        current_price = (bundle.get("price") or {}).get("current_price")
        fv_svg, fv_table = range_meter(fv_low, None, None, fv_high, current_price)
        fv_html = f"""
  <div class="rec-fair-value" style="margin-top:14px;">
    <div style="font-size:13px;margin-bottom:4px;"><b>Fair value estimate (today, not a price forecast)</b> {info_icon('fair_value')}</div>
    {fv_svg}
    <div class="viz-note">{esc(judge.get('fair_value_basis') or '')}</div>
  </div>"""

    def _skeptic_block(label, review):
        unsupported = review.get("unsupported_claims") or []
        gaps = review.get("data_gaps") or []
        if not unsupported and not gaps:
            return ""
        parts = ['<div class="rec-skeptic">', f'<b>{esc(label)}</b> (data quality: {esc(review.get("overall_data_quality") or "unknown")}):']
        if unsupported:
            parts.append("<div>Unsupported claims flagged: " + "; ".join(esc(c) for c in unsupported) + "</div>")
        if gaps:
            parts.append("<div>Data gaps noted: " + "; ".join(esc(g) for g in gaps) + "</div>")
        parts.append("</div>")
        return "".join(parts)

    skeptic_html = _skeptic_block("Skeptic review (Claude)", skeptic)
    skeptic_qwen_html = _skeptic_block("Skeptic review (Qwen, independent second opinion)", skeptic_qwen)
    if skeptic_html or skeptic_qwen_html:
        agree_note = ""
        if unsupported_overlap := set(skeptic.get("unsupported_claims") or []) & set(skeptic_qwen.get("unsupported_claims") or []):
            agree_note = f'<div class="viz-note" style="margin-top:6px;">Both independent skeptics flagged the same claim(s): {esc("; ".join(unsupported_overlap))} — treat this as a stronger signal.</div>'
        skeptic_html = f'<div style="margin-top:12px;">{skeptic_html}{skeptic_qwen_html}{agree_note}</div>'

    quant_html = ""
    flagged = quant_check.get("flagged_claims") or []
    if flagged:
        rows = "".join(
            f'<li><b>{esc(f.get("claim") or "—")}</b> — {esc(f.get("issue") or "—")} '
            f'<span class="meta">(checked against: {esc(f.get("bundle_figures_checked") or "—")})</span></li>'
            for f in flagged
        )
        quant_html = f"""
  <div class="rec-skeptic" style="margin-top:12px;">
    <b>Quant Checker</b> — numeric claims that didn't check out:
    <ul class="rec-risks">{rows}</ul>
  </div>"""
    elif quant_check.get("verified_claims"):
        quant_html = f"""
  <div class="viz-note" style="margin-top:12px;">Quant Checker verified {len(quant_check['verified_claims'])} numeric claim(s) against the bundle's own figures — none flagged.</div>"""

    return f"""
<div class="card full rec-card rec-{rec_cls}">
  <div class="rec-top">
    <div>
      <span class="rec-badge-big {rec_cls}">{esc(rec_label)}</span>
      {info_icon('ai_recommendation')}
    </div>
    <div class="rec-meta">Confidence {esc(confidence)}/100 · run #{esc(pipeline_result.get('run_id'))} · cost ${pipeline_result.get('total_cost_usd', 0):.4f}</div>
  </div>
  <div class="rec-body">{esc(judge.get('reasoning_summary') or 'No reasoning provided.')}</div>
  <div style="margin-top:12px;font-size:13px;"><b>Key risks:</b></div>
  <ul class="rec-risks">{risks_html}</ul>
  <div class="viz-note" style="margin-top:10px;">{esc(judge.get('data_quality_caveat') or '')}</div>
  <div class="rec-thesis-grid">
    <div class="rec-thesis bull"><div class="who">Bull case ({esc(bull.get('confidence', '—'))}/100{f", fair value {fmt_price(bull.get('fair_value_estimate'))}" if bull.get('fair_value_estimate') is not None else ""})</div>{esc(bull.get('thesis') or '—')}</div>
    <div class="rec-thesis bear"><div class="who">Bear case ({esc(bear.get('confidence', '—'))}/100{f", fair value {fmt_price(bear.get('fair_value_estimate'))}" if bear.get('fair_value_estimate') is not None else ""})</div>{esc(bear.get('thesis') or '—')}</div>
  </div>
  {fv_html}
  {skeptic_html}
  {quant_html}
</div>"""


def section_at_a_glance(bundle):
    """
    Plain-English translation of the numbers below, for a reader with no
    finance background. Every sentence here is mechanically derived from a
    field already in the bundle plus a fixed, documented threshold (e.g.
    "P/E premium > 15% counts as 'trading at a premium'") -- nothing is
    invented or inferred beyond simple arithmetic/thresholds on real data,
    matching this project's "stay grounded in the data" principle applied to
    prose instead of numbers.
    """
    ticker = esc(bundle.get("ticker", "This stock"))
    price = bundle.get("price", {}) or {}
    fundamentals = bundle.get("fundamentals", {}) or {}
    rp = bundle.get("relative_performance", {}) or {}
    analyst_ratings = bundle.get("analyst_ratings", {}) or {}
    inc = bundle.get("income_statement", {}) or {}
    annual = inc.get("annual") or {}
    insider = bundle.get("insider_transactions", {}) or {}
    soc = bundle.get("social_sentiment", {}) or {}
    macro = bundle.get("macro_context", {}) or {}

    items = []

    # 1. Price performance vs. the market
    pct_1y = price.get("pct_change_1y")
    rel_1y = rp.get("relative_vs_benchmark_1y_pct")
    if pct_1y is not None:
        direction = "up" if pct_1y >= 0 else "down"
        cls = "good" if pct_1y >= 0 else "critical"
        sentence = f"<b>{ticker} is {direction} {fmt_pct(abs(pct_1y), signed=False)} over the past year.</b>"
        if rel_1y is not None:
            if rel_1y > 5:
                sentence += f" That's beating the S&P 500 by {fmt_pct(abs(rel_1y), signed=False)} — it outperformed the broader market, not just \"stocks went up in general.\""
            elif rel_1y < -5:
                sentence += f" That's trailing the S&P 500 by {fmt_pct(abs(rel_1y), signed=False)} — the broader market did better over the same period."
                cls = "critical"
            else:
                sentence += " That's roughly in line with the S&P 500 over the same period."
                cls = "neutral"
        items.append(_glance_item(cls, "↑" if cls == "good" else ("↓" if cls == "critical" else "•"), sentence))

    # 2. Valuation
    stock_pe = rp.get("stock_pe_ratio")
    pe_prem_bench = rp.get("pe_premium_vs_benchmark_pct")
    if stock_pe is not None and pe_prem_bench is not None:
        if pe_prem_bench > 15:
            sentence = f"<b>Trading at a premium valuation</b> — its P/E ratio ({fmt_num(stock_pe,1)}) is {fmt_pct(pe_prem_bench, signed=False)} higher than the S&P 500's, meaning investors are paying more per dollar of profit than for an average stock."
            items.append(_glance_item("neutral", "$", sentence))
        elif pe_prem_bench < -15:
            sentence = f"<b>Trading at a discount valuation</b> — its P/E ratio ({fmt_num(stock_pe,1)}) is {fmt_pct(abs(pe_prem_bench), signed=False)} lower than the S&P 500's, meaning investors are paying less per dollar of profit than for an average stock."
            items.append(_glance_item("neutral", "$", sentence))
    elif stock_pe is None and annual.get("net_income") is not None and annual.get("net_income") < 0:
        items.append(_glance_item("critical", "!", "<b>No P/E ratio to show</b> — the company lost money over the past year, so this common valuation measure doesn't apply."))

    # 3. Analyst view
    n_analysts = fundamentals.get("number_of_analyst_opinions")
    mean_target = fundamentals.get("target_mean_price")
    current_price = price.get("current_price")
    if n_analysts and mean_target and current_price:
        upside = (mean_target / current_price - 1) * 100
        rec = fundamentals.get("analyst_recommendation") or "no consensus"
        cls = "good" if upside > 5 else ("critical" if upside < -5 else "neutral")
        sentence = (
            f"<b>{n_analysts} Wall Street analysts</b> have an average 12-month price target of {fmt_price(mean_target)}, "
            f"{fmt_pct(abs(upside), signed=False)} {'above' if upside >= 0 else 'below'} today's price "
            f"— their overall rating is <b>\"{esc(rec)}\"</b>."
        )
        items.append(_glance_item(cls, "↑" if cls == "good" else ("↓" if cls == "critical" else "•"), sentence))

    # 4. Momentum (RSI)
    rsi = price.get("rsi_14")
    if rsi is not None:
        if rsi > 70:
            items.append(_glance_item("critical", "!", f"<b>Short-term momentum looks stretched</b> — its RSI of {fmt_num(rsi,1)} is above 70, conventionally read as \"overbought\" (a lot of recent buying pressure)."))
        elif rsi < 30:
            items.append(_glance_item("good", "•", f"<b>Short-term momentum looks beaten-down</b> — its RSI of {fmt_num(rsi,1)} is below 30, conventionally read as \"oversold\" (a lot of recent selling pressure)."))

    # 5. Financial health
    net_income = annual.get("net_income")
    if net_income is not None:
        if net_income > 0:
            items.append(_glance_item("good", "$", f"<b>Profitable</b> — net income of {fmt_usd(net_income)} over the last full year."))
        else:
            items.append(_glance_item("critical", "!", f"<b>Lost money</b> — net loss of {fmt_usd(abs(net_income))} over the last full year."))

    # 6. Insider activity -- only genuine open-market purchases (real cash,
    # their own choice) count as "buying" here. Stock grants/awards and
    # option exercises also show up with direction == "buy" (their holdings
    # went up), but that's routine compensation, not a vote of confidence --
    # conflating the two was a real bug, see HANDOFF.md.
    txns = insider.get("transactions", []) or []
    if txns:
        open_market_buys = sum(1 for t in txns if t.get("direction") == "buy" and t.get("is_open_market"))
        open_market_sells = sum(1 for t in txns if t.get("direction") == "sell" and t.get("is_open_market"))
        grants_or_exercises = sum(1 for t in txns if t.get("direction") == "buy" and not t.get("is_open_market"))
        if open_market_buys and not open_market_sells:
            items.append(_glance_item("good", "•", f"<b>Company insiders have been buying</b> — {open_market_buys} recent open-market purchase(s) with their own money and no open-market sales in this list, often read as a vote of confidence."))
        elif open_market_buys and open_market_sells:
            items.append(_glance_item("neutral", "•", f"<b>Mixed insider activity</b> — {open_market_buys} recent open-market buy(s) and {open_market_sells} open-market sale(s) by company insiders; sales are common and often routine, not necessarily a bad sign."))
        elif not open_market_buys and not open_market_sells and grants_or_exercises:
            items.append(_glance_item("neutral", "•", f"<b>No open-market insider buying or selling</b> — the {grants_or_exercises} insider transaction(s) in this list are stock grants/awards or option exercises (routine compensation), not purchases with their own money, so they're not read as a confidence signal either way."))

    # 7. Social sentiment (only worth a mention with enough tagged posts to mean something)
    bull, bear = soc.get("bullish_count", 0), soc.get("bearish_count", 0)
    if bull + bear >= 5:
        pct_bull = soc.get("bullish_pct_of_tagged")
        if pct_bull is not None and pct_bull > 65:
            items.append(_glance_item("good", "•", f"<b>Retail chatter leans bullish</b> — {fmt_pct(pct_bull, signed=False)} of tagged posts on StockTwits are bullish. This is unmoderated public opinion, not analysis."))
        elif pct_bull is not None and pct_bull < 35:
            items.append(_glance_item("critical", "•", f"<b>Retail chatter leans bearish</b> — only {fmt_pct(pct_bull, signed=False)} of tagged posts on StockTwits are bullish. This is unmoderated public opinion, not analysis."))

    # 8. Market backdrop
    vix = macro.get("vix_level")
    if vix is not None:
        if vix > 25:
            items.append(_glance_item("critical", "!", f"<b>The broader market is jittery right now</b> — VIX is at {fmt_num(vix,1)}, an elevated level, meaning investors expect bigger price swings across stocks in general (not specific to {ticker})."))
        elif vix < 15:
            items.append(_glance_item("good", "•", f"<b>The broader market is calm right now</b> — VIX is at {fmt_num(vix,1)}, a low level, meaning investors expect fairly steady conditions across stocks in general (not specific to {ticker})."))

    if not items:
        items.append(_glance_item("neutral", "•", "Not enough data was available to generate a plain-language summary for this ticker."))

    return f"""
<div class="card full">
  <h2>At a Glance <span style="font-weight:400;color:var(--text-secondary);font-size:12px;">— plain-language summary, auto-generated from the data below</span></h2>
  <ul class="glance-list">{''.join(items)}</ul>
</div>"""


def section_kpis(bundle):
    price = bundle.get("price", {}) or {}
    fundamentals = bundle.get("fundamentals", {}) or {}
    macro = bundle.get("macro_context", {}) or {}
    rp = bundle.get("relative_performance", {}) or {}

    tiles = []
    tiles.append(stat_tile("Current price", fmt_price(price.get("current_price")),
                            delta_text=f"{fmt_pct(price.get('pct_change_20d'))} (20d)",
                            delta_cls=delta_class(price.get("pct_change_20d")),
                            info="current_price"))
    tiles.append(stat_tile("1-year return", fmt_pct(price.get("pct_change_1y")),
                            delta_text=f"vs S&P500 {fmt_pct(rp.get('relative_vs_benchmark_1y_pct'))}",
                            delta_cls=delta_class(rp.get("relative_vs_benchmark_1y_pct")),
                            value_cls=delta_class(price.get("pct_change_1y")), info="1y_return"))
    tiles.append(stat_tile("P/E ratio", fmt_num(fundamentals.get("pe_ratio"), 1),
                            sub=f"Forward {fmt_num(fundamentals.get('forward_pe'), 1)}", info="pe_ratio"))
    tiles.append(stat_tile("Market cap", esc(fundamentals.get("market_cap") or "—"),
                            sub=esc(fundamentals.get("sector") or ""), info="market_cap"))
    tiles.append(stat_tile("RSI (14d)", fmt_num(price.get("rsi_14"), 1),
                            sub="Overbought > 70, oversold < 30",
                            value_cls=rsi_class(price.get("rsi_14")), info="rsi"))
    tiles.append(stat_tile("VIX", fmt_num(macro.get("vix_level"), 1),
                            delta_text=f"{fmt_num(macro.get('vix_change_20d'),1, )} (20d)" if macro.get("vix_change_20d") is not None else None,
                            delta_cls=delta_class(macro.get("vix_change_20d"), invert=True), info="vix"))
    tiles.append(stat_tile("10Y Treasury yield", fmt_pct(macro.get("treasury_10y_yield_pct"), signed=False),
                            delta_text=f"{fmt_pct(macro.get('treasury_10y_yield_change_20d_pct'))} (20d)" if macro.get("treasury_10y_yield_change_20d_pct") is not None else None,
                            delta_cls=delta_class(macro.get("treasury_10y_yield_change_20d_pct"), invert=True), info="treasury_10y"))
    return f'<div class="kpi-row">{"".join(tiles)}</div>'


def section_price_technicals(bundle):
    price = bundle.get("price", {}) or {}
    items = [
        ("52w Low", price.get("52w_low")),
        ("MA200", price.get("ma200")),
        ("MA50", price.get("ma50")),
        ("MA20", price.get("ma20")),
        ("Current", price.get("current_price")),
        ("52w High", price.get("52w_high")),
    ]
    svg, table = bar_chart_horizontal(items, value_fmt=fmt_price)
    price_card = viz_card("Price vs. moving averages", svg, table, info="price_vs_ma")

    rsi_svg, rsi_table = gauge_meter(
        price.get("rsi_14"), 0, 100,
        zones=[(30, "var(--status-good)", "below 30 (oversold)"), (70, "var(--gridline)", "30-70 (neutral)"), (100, "var(--status-critical)", "above 70 (overbought)")],
        label="RSI (14d)",
    )
    rsi_card = viz_card("RSI (14-day)", rsi_svg, rsi_table, info="rsi_gauge",
                         note="Green zone (below 30) is conventionally read as oversold, red zone (above 70) as overbought -- a short-term momentum signal, not a verdict on the company. Click the \"i\" above for more.")

    macd = price.get("macd")
    macd_signal = price.get("macd_signal")
    macd_hist = price.get("macd_histogram")
    macd_status = "good" if (macd_hist or 0) > 0 else "critical" if (macd_hist or 0) < 0 else "neutral"
    macd_html = f"""
<div class="kpi-row cols-3" style="margin-top:6px;">
  {stat_tile("MACD", fmt_num(macd,3))}
  {stat_tile("Signal", fmt_num(macd_signal,3))}
  {stat_tile("Histogram", fmt_num(macd_hist,3), delta_text=("Bullish momentum" if macd_status=="good" else "Bearish momentum" if macd_status=="critical" else "Flat"), delta_cls=macd_status, value_cls=macd_status if macd_status != "neutral" else None, info="macd_histogram")}
</div>"""

    return f"""
<div class="card" id="sec-price">
  <h2>Price & Technicals {info_icon('section_price')}</h2>
  <div class="card-sub">20d volatility {fmt_pct(price.get('volatility_20d'), signed=False, decimals=2)} · volume trend: {esc(price.get('volume_trend') or '—')}</div>
  {price_card}
  {rsi_card}
  {macd_html}
</div>"""


def _action_badge(action):
    m = {"upgrade": "good", "downgrade": "critical", "initiated": "info",
         "maintained": "neutral", "reiterated": "neutral"}
    return badge(action or "—", m.get(action, "neutral"))


def section_analyst(bundle):
    fundamentals = bundle.get("fundamentals", {}) or {}
    analyst_ratings = bundle.get("analyst_ratings", {}) or {}
    earnings_est = bundle.get("earnings_estimates", {}) or {}
    fmp = bundle.get("fmp_valuation", {}) or {}

    range_svg, range_table = range_meter(
        fundamentals.get("target_low_price"), fundamentals.get("target_mean_price"),
        fundamentals.get("target_median_price"), fundamentals.get("target_high_price"),
        bundle.get("price", {}).get("current_price"),
    )
    range_card = viz_card(
        f"Analyst target price range ({fundamentals.get('number_of_analyst_opinions') or 0} analysts)",
        range_svg, range_table, info="analyst_target_range",
    )

    dcf_html = ""
    if fmp.get("dcf_value") is not None or fmp.get("peg_ratio") is not None:
        dcf_html = f"""
<div class="kpi-row cols-2" style="margin-top:12px;">
  {stat_tile("DCF fair value (FMP)", fmt_price(fmp.get('dcf_value')), sub="independent of analyst targets above", info="dcf_valuation") if fmp.get('dcf_value') is not None else ""}
  {stat_tile("PEG ratio", fmt_num(fmp.get('peg_ratio'), 2), info="peg_ratio") if fmp.get('peg_ratio') is not None else ""}
</div>"""

    actions = analyst_ratings.get("actions", []) or []
    action_rows = []
    for a in actions[:12]:
        pt = ""
        if a.get("current_price_target") is not None:
            prior = a.get("prior_price_target")
            pt = f"{fmt_price(a.get('current_price_target'))}" + (f" (was {fmt_price(prior)})" if prior else "")
        action_rows.append([
            a.get("date") or "—", a.get("firm") or "—", _action_badge(a.get("action")),
            f"{a.get('from_grade') or '—'} → {a.get('to_grade') or '—'}", pt or "—",
        ])
    actions_table = data_table(["Date", "Firm", "Action", "Grade change", "Price target"], action_rows)

    # Buy/Hold/Sell across periods is an ordered-scale share (a Likert-style
    # distribution) -- the dataviz skill's recommended form is a diverging
    # stacked bar centered on neutral, not a bare table. One small bar per
    # period (small multiples, most recent first).
    rec_trend = (bundle.get("finnhub_signals", {}) or {}).get("recommendation_trend", []) or []
    rec_trend_html = ""
    if rec_trend:
        periods = rec_trend[:6]
        bars = []
        for r in periods:
            svg, _, _ = diverging_stacked_ordinal(
                neg_segments=[("Sell", r.get("sell")), ("Strong sell", r.get("strong_sell"))],
                mid_value=r.get("hold"),
                pos_segments=[("Buy", r.get("buy")), ("Strong buy", r.get("strong_buy"))],
                mid_label="Hold",
                aria_label=f"analyst recommendation mix, {r.get('period') or 'period'}",
            )
            bars.append(
                f'<div class="rec-trend-row"><div class="rec-trend-period">{esc(r.get("period") or "—")}</div>'
                f'<div class="rec-trend-chart">{svg}</div></div>'
            )
        leg_html = legend([("Strong sell / Sell", "var(--diverge-neg)"), ("Hold", "var(--gridline)"), ("Buy / Strong buy", "var(--diverge-pos)")])

        rec_trend_rows = [
            [r.get("period") or "—", fmt_num(r.get("strong_buy")), fmt_num(r.get("buy")),
             fmt_num(r.get("hold")), fmt_num(r.get("sell")), fmt_num(r.get("strong_sell"))]
            for r in periods
        ]
        rec_trend_table = data_table(["Period", "Strong buy", "Buy", "Hold", "Sell", "Strong sell"], rec_trend_rows)

        rec_trend_html = f"""
<div style="margin-top:16px;">{viz_card("Analyst recommendation trend", "".join(bars), rec_trend_table, leg_html, info="recommendation_trend")}</div>"""

    surprises = earnings_est.get("earnings_surprise_history", []) or []
    surprise_items = [(s.get("quarter_end"), s.get("surprise_pct")) for s in surprises]
    if surprise_items:
        s_svg, s_table, s_legend = diverging_bar_horizontal(surprise_items, value_fmt=lambda v: fmt_pct(v))
        surprise_card = viz_card("EPS surprise history (actual vs. estimate)", s_svg, s_table, s_legend, info="eps_surprise")
    else:
        surprise_card = viz_card("EPS surprise history", "<svg></svg>", empty_state(), info="eps_surprise")

    trend = earnings_est.get("eps_estimate_trend", {}) or {}
    trend_rows = []
    for period_label, key in [("Current quarter", "current_quarter"), ("Next quarter", "next_quarter"),
                               ("Current year", "current_year"), ("Next year", "next_year")]:
        p = trend.get(key)
        if not p:
            continue
        trend_rows.append([
            period_label, fmt_num(p.get("90daysAgo"), 2), fmt_num(p.get("30daysAgo"), 2),
            fmt_num(p.get("7daysAgo"), 2), fmt_num(p.get("current"), 2),
        ])
    trend_table = data_table(["Period", "90d ago", "30d ago", "7d ago", "Current est."], trend_rows)

    return f"""
<div class="card full" id="sec-analyst">
  <h2>Analyst Ratings & Estimates {info_icon('section_analyst')}</h2>
  <div class="card-sub">Recommendation: {esc(fundamentals.get('analyst_recommendation') or '—')} · last {analyst_ratings.get('lookback_days', 60)} days of rating actions</div>
  <div class="split-2col">
    <div>{range_card}{dcf_html}{surprise_card}</div>
    <div>
      <div class="viz-card"><div class="viz-card-head"><span class="viz-title">Recent rating actions {info_icon('analyst_actions')}</span></div>{actions_table}</div>
      {rec_trend_html}
      <div class="viz-card" style="margin-top:16px;"><div class="viz-card-head"><span class="viz-title">EPS estimate trend (Street consensus) {info_icon('eps_trend')}</span></div>{trend_table}</div>
    </div>
  </div>
</div>"""


def section_relative_performance(bundle):
    rp = bundle.get("relative_performance", {}) or {}
    fundamentals = bundle.get("fundamentals", {}) or {}

    # (series name, color, 20d field, 1y field)
    series_specs = [
        ("Stock", "var(--series-1)", "stock_pct_change_20d", "stock_pct_change_1y"),
        ("S&P 500", "var(--series-2)", "benchmark_pct_change_20d", "benchmark_pct_change_1y"),
    ]
    if rp.get("sector_etf"):
        series_specs.append((f"Sector ({rp.get('sector_etf')})", "var(--series-3)",
                              "sector_pct_change_20d", "sector_pct_change_1y"))

    groups = [
        ("20-day return", [(name, color, rp.get(k20)) for name, color, k20, _ in series_specs]),
        ("1-year return", [(name, color, rp.get(k1y)) for name, color, _, k1y in series_specs]),
    ]
    svg, table, leg = grouped_bar_horizontal(groups, value_fmt=lambda v: fmt_pct(v))
    perf_card = viz_card("Return vs. benchmark & sector", svg, table, leg, info="relative_performance")

    if rp.get("stock_pe_ratio") is not None:
        stock_pe_display = fmt_num(rp.get("stock_pe_ratio"), 1)
        stock_pe_sub = None
    else:
        forward_pe = fundamentals.get("forward_pe")
        stock_pe_display = "N/A"
        stock_pe_sub = (
            f"No trailing P/E (company had a loss) — forward P/E (based on next year's estimate): {fmt_num(forward_pe, 1)}"
            if forward_pe is not None else "No trailing P/E — company had a loss over the past year"
        )
    pe_tiles = f"""
<div class="kpi-row cols-3" style="margin-top:12px;">
  {stat_tile("Stock P/E", stock_pe_display, sub=stock_pe_sub, info="pe_ratio")}
  {stat_tile("P/E vs S&P 500", fmt_pct(rp.get('pe_premium_vs_benchmark_pct')), sub=f"S&P 500 P/E {fmt_num(rp.get('benchmark_pe_ratio'),1)}", info="pe_premium")}
  {stat_tile("P/E vs sector", fmt_pct(rp.get('pe_premium_vs_sector_pct')), sub=f"Sector P/E {fmt_num(rp.get('sector_pe_ratio'),1)}", info="pe_premium")}
</div>"""

    return f"""
<div class="card full" id="sec-relative">
  <h2>Relative Performance & Valuation {info_icon('section_relative')}</h2>
  <div class="card-sub">Returns and P/E vs. {esc(rp.get('benchmark','SPY'))} and sector ETF {esc(rp.get('sector_etf') or '—')} — two different questions, shown separately.</div>
  {perf_card}
  {pe_tiles}
</div>"""


def section_ownership(bundle):
    inst = bundle.get("institutional_ownership", {}) or {}
    pct_inst = (inst.get("pct_held_by_institutions") or 0) * 100
    pct_insider = (inst.get("pct_held_by_insiders") or 0) * 100
    pct_other = max(0, 100 - pct_inst - pct_insider)
    stack_svg, stack_table, stack_legend = stacked_bar_parts([
        ("Institutions", pct_inst, "var(--series-1)"),
        ("Insiders", pct_insider, "var(--series-2)"),
        ("Other / retail", pct_other, "var(--gridline)"),
    ])
    stack_card = viz_card("Institutional vs. insider ownership", stack_svg, stack_table, stack_legend, info="ownership_breakdown")

    holders = inst.get("top_institutional_holders", []) or []
    holders_rows = [[h.get("holder"), fmt_num(h.get("shares")), fmt_pct(h.get("pct_out"), signed=False, decimals=2), fmt_usd(h.get("value"))] for h in holders]
    holders_table = data_table(["Holder", "Shares", "% out", "Value"], holders_rows)

    insiders = (bundle.get("insider_transactions", {}) or {}).get("transactions", []) or []
    insider_rows = []
    for t in insiders[:12]:
        # Only a genuine open-market buy is a real "vote of confidence" --
        # a grant/award or option exercise also shows direction == "buy"
        # (holdings went up) but isn't the insider choosing to spend their
        # own money, so it doesn't get the same green badge.
        is_real_buy = t.get("direction") == "buy" and t.get("is_open_market")
        is_real_sell = t.get("direction") == "sell" and t.get("is_open_market")
        direction_badge = badge(t.get("direction") or "—", "good" if is_real_buy else "critical" if is_real_sell else "neutral")
        insider_rows.append([t.get("date") or "—", t.get("owner") or "—", t.get("title") or "—",
                              direction_badge, t.get("transaction_nature") or "—",
                              fmt_num(t.get("shares")), fmt_price(t.get("price_per_share")) if t.get("price_per_share") else "—"])
    insider_table = data_table(["Date", "Owner", "Title", "Direction", "Nature", "Shares", "Price"], insider_rows)

    finnhub = bundle.get("finnhub_signals", {}) or {}
    mspr_html = ""
    if finnhub.get("insider_sentiment_mspr") is not None:
        mspr = finnhub["insider_sentiment_mspr"]
        mspr_html = f"""
<div class="kpi-row" style="margin-bottom:12px;">
  {stat_tile("Insider sentiment (MSPR)", fmt_num(mspr, 2), value_cls=delta_class(mspr), info="insider_sentiment_mspr",
             sub="Positive = net buying, negative = net selling, over the past month")}
</div>"""

    f144 = (bundle.get("form144_notices", {}) or {}).get("notices", []) or []
    f144_rows = [[n.get("approx_sale_date") or "—", n.get("seller") or "—", n.get("relationship") or "—",
                  fmt_num(n.get("shares_proposed_to_sell")), fmt_usd(n.get("aggregate_market_value_usd"))] for n in f144]
    f144_table = data_table(["Approx. date", "Seller", "Relationship", "Shares proposed", "Value"], f144_rows)

    ben = (bundle.get("beneficial_ownership", {}) or {}).get("filings", []) or []
    ben_rows = []
    for b in ben:
        form_badge = badge(("13D" if b.get("form") == "13D" else "13G") + (" /A" if b.get("is_amendment") else ""),
                            "info" if b.get("form") == "13D" else "neutral")
        ben_rows.append([b.get("filing_date") or "—", b.get("reporting_person") or "—", form_badge,
                          fmt_pct(b.get("percent_of_class"), signed=False, decimals=2), b.get("type_of_reporting_person") or "—"])
    ben_table = data_table(["Filed", "Reporting person", "Schedule", "% of class", "Type"], ben_rows)

    return f"""
<div class="card full" id="sec-ownership">
  <h2>Ownership {info_icon('section_ownership')}</h2>
  <div class="card-sub">Snapshot of current holders — not a quarter-over-quarter 13F change (see data notes).</div>
  <div class="split-2col">
    <div>
      {stack_card}
      <div class="viz-card" style="margin-top:16px;"><div class="viz-card-head"><span class="viz-title">Top institutional holders {info_icon('top_holders')}</span></div>{holders_table}</div>
      <div class="viz-card" style="margin-top:16px;"><div class="viz-card-head"><span class="viz-title">Schedule 13D/13G (&gt;5% stakes) {info_icon('beneficial_ownership')}</span></div>{ben_table if ben_rows else empty_state()}</div>
    </div>
    <div>
      {mspr_html}
      <div class="viz-card"><div class="viz-card-head"><span class="viz-title">Insider transactions (Form 4) {info_icon('insider_transactions')}</span></div>{insider_table if insider_rows else empty_state()}</div>
      <div class="viz-card" style="margin-top:16px;"><div class="viz-card-head"><span class="viz-title">Form 144 proposed sales {info_icon('form144')}</span></div>{f144_table if f144_rows else empty_state()}</div>
    </div>
  </div>
</div>"""


def section_financials(bundle):
    bs = bundle.get("balance_sheet_health", {}) or {}
    inc = bundle.get("income_statement", {}) or {}
    annual = inc.get("annual") or {}
    quarterly = list(reversed(inc.get("quarterly") or []))  # oldest -> newest for chart

    current_ratio = bs.get("current_ratio")
    current_ratio_cls = "critical" if current_ratio is not None and current_ratio < 1 else ("good" if current_ratio is not None and current_ratio >= 1.5 else None)
    net_income = annual.get("net_income")
    fcf = bs.get("free_cash_flow")

    bs_tiles = f"""
<div class="kpi-row cols-4">
  {stat_tile("Total debt", fmt_usd(bs.get('total_debt')), info="balance_sheet")}
  {stat_tile("Total cash", fmt_usd(bs.get('total_cash')), info="balance_sheet")}
  {stat_tile("Debt / equity", fmt_num(bs.get('debt_to_equity'),1), info="balance_sheet",
             sub="Lower generally means less financial risk")}
  {stat_tile("Current ratio", fmt_num(current_ratio,2), value_cls=current_ratio_cls, info="balance_sheet",
             sub="Below 1 can mean trouble paying short-term bills; above 1.5 is comfortable")}
  {stat_tile("Free cash flow", fmt_usd(fcf), value_cls=delta_class(fcf), info="balance_sheet")}
  {stat_tile("Operating cash flow", fmt_usd(bs.get('operating_cash_flow')), info="balance_sheet")}
  {stat_tile("Annual revenue", fmt_usd(annual.get('total_revenue')), sub=f"Period end {annual.get('period_end','—')}", info="quarterly_financials")}
  {stat_tile("Annual net income", fmt_usd(net_income), value_cls=delta_class(net_income),
             sub=f"Net margin {fmt_pct(annual.get('net_margin_pct'), signed=False)}", info="quarterly_financials")}
</div>"""

    cats = [q.get("period_end", "—") for q in quarterly]
    series = [
        ("Revenue", "var(--series-1)", [q.get("total_revenue") for q in quarterly]),
        ("Net income", "var(--series-2)", [q.get("net_income") for q in quarterly]),
    ]
    if cats:
        q_svg, q_table, q_legend = grouped_column_chart(cats, series)
        q_card = viz_card("Quarterly revenue & net income", q_svg, q_table, q_legend, info="quarterly_financials")
    else:
        q_card = viz_card("Quarterly revenue & net income", "<svg></svg>", empty_state(), info="quarterly_financials")

    return f"""
<div class="card full" id="sec-financials">
  <h2>Financials {info_icon('section_financials')}</h2>
  {bs_tiles}
  {q_card}
</div>"""


def section_dividends_options_macro_social(bundle):
    div = bundle.get("dividends_buybacks", {}) or {}
    opt = bundle.get("options_sentiment", {}) or {}
    macro = bundle.get("macro_context", {}) or {}
    soc = bundle.get("social_sentiment", {}) or {}

    div_tiles = f"""
<div class="kpi-row cols-3">
  {stat_tile("Dividend yield", fmt_pct(div.get('dividend_yield_pct'), signed=False) if div.get('dividend_yield_pct') is not None else "No dividend", info="dividend_yield")}
  {stat_tile("Payout ratio", fmt_pct(div.get('payout_ratio_pct'), signed=False), info="payout_ratio")}
  {stat_tile("5y avg yield", fmt_pct(div.get('five_year_avg_dividend_yield_pct'), signed=False) if div.get('five_year_avg_dividend_yield_pct') is not None else "—", info="dividend_yield")}
</div>"""
    buybacks = div.get("buybacks_recent_quarters", []) or []
    bb_items = [(b.get("quarter_end"), b.get("buyback_usd")) for b in buybacks]
    if bb_items:
        bb_svg, bb_table = bar_chart_horizontal(bb_items, value_fmt=fmt_usd)
        bb_card = viz_card("Quarterly buyback spend", bb_svg, bb_table, info="buybacks")
    else:
        bb_card = viz_card("Quarterly buyback spend", "<svg></svg>", empty_state("No buyback activity found."), info="buybacks")

    opt_reliable = opt.get("put_call_volume_ratio") is not None
    opt_html = f"""
<div class="kpi-row cols-2">
  {stat_tile("Put/call volume ratio", fmt_num(opt.get('put_call_volume_ratio'),3) if opt_reliable else "—", info="put_call_ratio")}
  {stat_tile("Put/call open interest ratio", fmt_num(opt.get('put_call_open_interest_ratio'),3) if opt_reliable else "—", info="put_call_ratio")}
</div>
<div style="margin-top:10px;">{badge("IV/skew fields unreliable — see note", "warning")} {info_icon('iv_skew')}</div>
<div class="viz-note" style="margin-top:8px;">{esc(opt.get('note') or '')}</div>"""

    fred_tiles = ""
    if any(macro.get(k) is not None for k in ("cpi_yoy_pct", "unemployment_rate_pct", "fed_funds_rate_pct", "yield_curve_10y_2y_pct")):
        fred_tiles = f"""
<div class="kpi-row cols-4" style="margin-top:10px;">
  {stat_tile("CPI inflation (YoY)", fmt_pct(macro.get('cpi_yoy_pct'), signed=False), info="cpi_yoy")}
  {stat_tile("Unemployment rate", fmt_pct(macro.get('unemployment_rate_pct'), signed=False), info="unemployment_rate")}
  {stat_tile("Fed funds rate", fmt_pct(macro.get('fed_funds_rate_pct'), signed=False), info="fed_funds_rate")}
  {stat_tile("10y-2y yield curve", fmt_pct(macro.get('yield_curve_10y_2y_pct')), delta_cls=delta_class(macro.get('yield_curve_10y_2y_pct')), info="yield_curve")}
</div>"""

    macro_tiles = f"""
<div class="kpi-row cols-2">
  {stat_tile("VIX level", fmt_num(macro.get('vix_level'),1), delta_text=fmt_num(macro.get('vix_change_20d'),1)+" (20d)" if macro.get('vix_change_20d') is not None else None, delta_cls=delta_class(macro.get('vix_change_20d'), invert=True), info="vix_macro")}
  {stat_tile("10Y Treasury yield", fmt_pct(macro.get('treasury_10y_yield_pct'), signed=False), delta_text=fmt_pct(macro.get('treasury_10y_yield_change_20d_pct'))+" (20d)" if macro.get('treasury_10y_yield_change_20d_pct') is not None else None, delta_cls=delta_class(macro.get('treasury_10y_yield_change_20d_pct'), invert=True), info="treasury_10y")}
</div>
{fred_tiles}
<div class="viz-note">Not ticker-specific — same for every ticker checked the same day.</div>"""

    sent_svg, sent_table, sent_legend = diverging_stacked_sentiment(
        soc.get("bearish_count", 0), soc.get("untagged_count", 0), soc.get("bullish_count", 0)
    )
    sent_card = viz_card(f"Social sentiment — StockTwits ({soc.get('message_count', 0)} recent posts)",
                          sent_svg, sent_table, sent_legend, info="social_sentiment",
                          note="Unmoderated public chatter — a crowd-mood gauge, not verified fact.")
    samples = soc.get("sample_messages_unverified", []) or []
    sample_html = "".join(
        f'<div class="news-item"><div class="meta">{esc(m.get("created_at"))} · {esc(m.get("sentiment") or "untagged")}</div>'
        f'<div class="snippet">{esc(m.get("body"))}</div></div>'
        for m in samples[:5]
    ) or empty_state()

    return f"""
<div class="card full" id="sec-extras">
  <h2>Dividends, Buybacks, Options & Sentiment {info_icon('section_extras')}</h2>
  <div class="split-2col">
    <div>
      {div_tiles}
      {bb_card}
      {macro_tiles}
    </div>
    <div>
      {opt_html}
      <div style="margin-top:16px;">{sent_card}</div>
      <div class="viz-card" style="margin-top:16px;">
        <div class="viz-card-head"><span class="viz-title">Sample posts (unverified)</span></div>
        {sample_html}
      </div>
    </div>
  </div>
</div>"""


def section_news(bundle):
    news = bundle.get("news_headlines", []) or []
    if not news:
        body = empty_state()
    else:
        items = []
        for n in news[:12]:
            url = n.get("url") or "#"
            items.append(f"""
<div class="news-item">
  <div class="headline"><a href="{esc(url)}" target="_blank" rel="noopener">{esc(n.get('headline'))}</a></div>
  <div class="meta">{esc(n.get('source'))} · {esc(n.get('date'))}</div>
  <div class="snippet">{esc(n.get('snippet'))}</div>
</div>""")
        body = "".join(items)
    digest = bundle.get("news_digest")
    digest_html = f'<div class="viz-note" style="margin-top:10px;"><strong>Digest:</strong> {esc(digest)}</div>' if digest else ""
    return f"""
<div class="card full" id="sec-news">
  <h2>News</h2>
  {body}
  {digest_html}
</div>"""


def section_filings(bundle):
    filings_raw = bundle.get("filings_raw", {}) or {}
    proxy = bundle.get("proxy_raw", {}) or {}
    rows = []
    for name in ["10-K", "10-Q", "8-K"]:
        f = filings_raw.get(name, {}) or {}
        if f.get("text"):
            rows.append(f'<div class="filing-row"><span class="name">{esc(name)}</span>{badge("Fetched","good")}<span class="info">Filed {esc(f.get("filing_date"))} · {len(f.get("text",""))} chars</span></div>')
        else:
            rows.append(f'<div class="filing-row"><span class="name">{esc(name)}</span>{badge("Not found","neutral")}<span class="info">{esc(f.get("note") or "")}</span></div>')
    if proxy.get("text"):
        rows.append(f'<div class="filing-row"><span class="name">DEF 14A</span>{badge("Fetched","good")}<span class="info">Filed {esc(proxy.get("filing_date"))} · {len(proxy.get("text",""))} chars</span></div>')
    else:
        rows.append(f'<div class="filing-row"><span class="name">DEF 14A</span>{badge("Not found","neutral")}<span class="info">{esc(proxy.get("note") or "")}</span></div>')

    digest = bundle.get("filings_digest")
    digest_html = f'<div class="viz-note" style="margin-top:10px;"><strong>Digest:</strong> {esc(digest)}</div>' if digest else '<div class="viz-note" style="margin-top:10px;">Filings digest not generated (dry run or no API key).</div>'

    return f"""
<div class="card full" id="sec-filings">
  <h2>Filings & Proxy</h2>
  {''.join(rows)}
  {digest_html}
</div>"""


def section_data_notes(bundle):
    notes = bundle.get("data_notes", []) or []
    if not notes:
        return ""
    items = "".join(f"<li>{badge('note','neutral')} <span>{esc(n)}</span></li>" for n in notes)
    return f"""
<div class="card full">
  <h2>Data Quality Notes</h2>
  <ul class="notes-list">{items}</ul>
</div>"""


# ============================================================================
# Assembly
# ============================================================================

def build_dashboard(bundle: dict, pipeline_result: dict | None = None) -> str:
    ticker = esc(bundle.get("ticker", "Ticker"))
    sections = [
        section_price_technicals(bundle),
        section_analyst(bundle),
        section_relative_performance(bundle),
        section_financials(bundle),
        section_ownership(bundle),
        section_dividends_options_macro_social(bundle),
        section_news(bundle),
        section_filings(bundle),
        section_data_notes(bundle),
    ]
    ai_section = section_ai_recommendation(bundle, pipeline_result) if pipeline_result else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{ticker} — StockLLM Research Dashboard</title>
<script>{THEME_INIT_SCRIPT}</script>
<style>{CSS_STYLE}</style>
</head>
<body>
<div class="sticky-top">
{section_header(bundle)}
{section_nav(bundle)}
</div>
{section_hero(bundle, pipeline_result)}
<div class="wrap">
  {ai_section}
  {section_at_a_glance(bundle)}
  {section_kpis(bundle)}
  <div class="grid">
    {''.join(sections)}
  </div>
</div>
<footer class="disclaimer">
  StockLLM is a research/decision-support tool. It is NOT financial advice and never places trades.
  This dashboard renders what is in the underlying JSON research bundle. The "At a Glance" panel
  turns numbers into sentences — every sentence there comes from a fixed, mechanical rule applied
  to a real field below (e.g. "P/E premium over 15% = trading at a premium"), not from any judgment
  call or outside opinion. The "AI Recommendation" panel, when present, is different: it is the
  actual output of StockLLM's own 6-agent LLM pipeline (Bull/Bear/two independent Skeptics/Quant
  Checker/Judge) — read it as one
  automated opinion informed by the data below, not as fact. Everything else on this page is
  unmodified data, not re-derived, judged, or fact-checked beyond what the data-fetch layer already notes.
</footer>
<script>{JS_SCRIPT}</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate an HTML dashboard from a StockLLM research bundle JSON file.")
    parser.add_argument("bundle_path", help="Path to a bundle JSON file (e.g. mobileye.json)")
    parser.add_argument("-o", "--output", help="Output HTML path (default: <bundle_name>_dashboard.html)")
    args = parser.parse_args()

    with open(args.bundle_path, "r", encoding="utf-8") as f:
        bundle = json.load(f)

    output_path = args.output
    if not output_path:
        base = args.bundle_path.rsplit(".", 1)[0]
        output_path = f"{base}_dashboard.html"

    html_out = build_dashboard(bundle)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_out)

    print(f"Dashboard written to: {output_path}")


if __name__ == "__main__":
    main()
