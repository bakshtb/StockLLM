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

  --diverge-pos: #2a78d6;
  --diverge-neg: #e34948;
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

    --diverge-pos: #3987e5;
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

  --diverge-pos: #3987e5;
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

.topbar {
  position: sticky; top: 0; z-index: 20;
  display: flex; align-items: center; justify-content: space-between;
  gap: 16px; padding: 16px 24px;
  background: var(--surface-1);
  border-bottom: 1px solid var(--border);
}
.topbar h1 { font-size: 20px; margin: 0; font-weight: 600; }
.topbar .meta { color: var(--text-secondary); font-size: 13px; margin-top: 2px; }
.topbar-actions { display: flex; align-items: center; gap: 10px; }
button.chip {
  font: inherit; font-size: 13px; cursor: pointer;
  background: var(--surface-1); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: 8px;
  padding: 7px 12px;
}
button.chip:hover { background: var(--gridline); }

.wrap { max-width: 1180px; margin: 0 auto; padding: 20px 24px; }

.kpi-row {
  display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  margin-bottom: 20px;
}
.stat-tile {
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px 16px;
}
.stat-tile .label { font-size: 12px; color: var(--text-secondary); }
.stat-tile .value { font-size: 24px; font-weight: 600; margin-top: 4px; line-height: 1.15; }
.stat-tile .sub { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
.delta { font-weight: 600; }
.delta.good { color: var(--success-text); }
.delta.critical { color: var(--status-critical); }
.delta.neutral { color: var(--text-secondary); }

.grid {
  display: grid; gap: 16px;
  grid-template-columns: repeat(auto-fit, minmax(460px, 1fr));
  align-items: start;
}
.card {
  background: var(--surface-1); border: 1px solid var(--border);
  border-radius: 12px; padding: 18px 20px;
}
.card.full { grid-column: 1 / -1; }
.card h2 { font-size: 15px; margin: 0 0 4px 0; font-weight: 600; }
.card .card-sub { font-size: 12px; color: var(--text-secondary); margin-bottom: 12px; }

.viz-card { margin-top: 6px; }
.viz-card-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 6px;
}
.viz-card-head .viz-title { font-size: 13px; color: var(--text-secondary); font-weight: 600; }
.viz-toggle {
  font-size: 11px; color: var(--text-secondary); background: none;
  border: 1px solid var(--border); border-radius: 6px; padding: 3px 8px; cursor: pointer;
}
.viz-toggle:hover { background: var(--gridline); }
.viz-card.is-table-view .viz-chart { display: none; }
.viz-card:not(.is-table-view) .viz-table { display: none; }
.viz-svg { width: 100%; height: auto; display: block; }
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
    return f"${fmt_compact(v, decimals)}"


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


def _mark(path_d, color, tip, extra_class=""):
    tip_attr = esc(tip)
    return (
        f'<g class="mark {extra_class}" tabindex="0" data-tip="{tip_attr}">'
        f'<title>{tip_attr}</title>'
        f'<path d="{path_d}" fill="{color}"/></g>'
    )


# ============================================================================
# Components
# ============================================================================

def stat_tile(label, value, sub=None, delta_text=None, delta_cls="neutral"):
    parts = [f'<div class="stat-tile"><div class="label">{esc(label)}</div>']
    parts.append(f'<div class="value">{esc(value)}</div>')
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
    if not rows:
        return empty_state()
    thead = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body_rows = []
    for r in rows:
        cells = "".join(f"<td>{c if isinstance(c, str) and c.startswith('<span') else esc(c)}</td>" for c in r)
        body_rows.append(f"<tr>{cells}</tr>")
    return (
        '<div class="table-scroll"><table class="data-table">'
        f"<thead><tr>{thead}</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"
    )


def viz_card(title, chart_svg, table_html, legend_html="", note=""):
    return f"""
<div class="viz-card">
  <div class="viz-card-head">
    <span class="viz-title">{esc(title)}</span>
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

    parts = [f'<svg viewBox="0 0 {W} {H}" class="viz-svg" role="img" aria-label="{esc(unit or "bar chart")}">']
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


def diverging_bar_horizontal(items, value_fmt=None):
    """items: list of (label, value) where value can be +/-. Baseline at center."""
    items = [it for it in items if it[1] is not None]
    if not items:
        return "<svg></svg>", empty_state()
    value_fmt = value_fmt or (lambda v: fmt_pct(v))
    max_v = max(abs(v) for _, v in items) or 1
    row_h, gap, pad = 22, 12, 16
    label_w = 110
    W = 620
    half = (W - label_w - 20) / 2
    center = label_w + half
    H = pad * 2 + len(items) * (row_h + gap) - gap

    parts = [f'<svg viewBox="0 0 {W} {H}" class="viz-svg" role="img" aria-label="values relative to baseline">']
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
        label_x = center + w + 6 if v >= 0 else center - w - 6
        anchor = "start" if v >= 0 else "end"
        parts.append(f'<text x="{label_x}" y="{y+row_h/2+4}" text-anchor="{anchor}" font-size="12" fill="var(--text-primary)">{esc(value_fmt(v))}</text>')
        y += row_h + gap
    parts.append("</svg>")

    rows = [[label, value_fmt(v)] for label, v in items]
    table = data_table(["Period", "Value"], rows)
    leg = legend([("Beat / above baseline", "var(--diverge-pos)"), ("Miss / below baseline", "var(--diverge-neg)")])
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
    parts = [f'<svg viewBox="0 0 {W} {H}" class="viz-svg" role="img" aria-label="grouped column chart">']
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

    parts = [f'<svg viewBox="0 0 {W} {H}" class="viz-svg" role="img" aria-label="analyst target price range">']
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

    parts = [f'<svg viewBox="0 0 {W} {H}" class="viz-svg" role="img" aria-label="{esc(label)} gauge">']
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

    parts = [f'<svg viewBox="0 0 {W} {H}" class="viz-svg" role="img" aria-label="ownership breakdown">']
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
    parts = [f'<svg viewBox="0 0 {W} {H}" class="viz-svg" role="img" aria-label="social sentiment split">']
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


def section_kpis(bundle):
    price = bundle.get("price", {}) or {}
    fundamentals = bundle.get("fundamentals", {}) or {}
    macro = bundle.get("macro_context", {}) or {}
    rp = bundle.get("relative_performance", {}) or {}

    tiles = []
    tiles.append(stat_tile("Current price", fmt_price(price.get("current_price")),
                            delta_text=f"{fmt_pct(price.get('pct_change_20d'))} (20d)",
                            delta_cls=delta_class(price.get("pct_change_20d"))))
    tiles.append(stat_tile("1-year return", fmt_pct(price.get("pct_change_1y")),
                            delta_text=f"vs S&P500 {fmt_pct(rp.get('relative_vs_benchmark_1y_pct'))}",
                            delta_cls=delta_class(rp.get("relative_vs_benchmark_1y_pct"))))
    tiles.append(stat_tile("P/E ratio", fmt_num(fundamentals.get("pe_ratio"), 1),
                            sub=f"Forward {fmt_num(fundamentals.get('forward_pe'), 1)}"))
    tiles.append(stat_tile("Market cap", esc(fundamentals.get("market_cap") or "—"),
                            sub=esc(fundamentals.get("sector") or "")))
    tiles.append(stat_tile("RSI (14d)", fmt_num(price.get("rsi_14"), 1),
                            sub="Overbought > 70, oversold < 30"))
    tiles.append(stat_tile("VIX", fmt_num(macro.get("vix_level"), 1),
                            delta_text=f"{fmt_num(macro.get('vix_change_20d'),1, )} (20d)" if macro.get("vix_change_20d") is not None else None,
                            delta_cls=delta_class(macro.get("vix_change_20d"), invert=True)))
    tiles.append(stat_tile("10Y Treasury yield", fmt_pct(macro.get("treasury_10y_yield_pct"), signed=False),
                            delta_text=f"{fmt_pct(macro.get('treasury_10y_yield_change_20d_pct'))} (20d)" if macro.get("treasury_10y_yield_change_20d_pct") is not None else None,
                            delta_cls=delta_class(macro.get("treasury_10y_yield_change_20d_pct"), invert=True)))
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
    price_card = viz_card("Price vs. moving averages", svg, table)

    rsi_svg, rsi_table = gauge_meter(
        price.get("rsi_14"), 0, 100,
        zones=[(30, "var(--gridline)", "below 30"), (70, "var(--baseline)", "30-70"), (100, "var(--gridline)", "above 70")],
        label="RSI (14d)",
    )
    rsi_card = viz_card("RSI (14-day)", rsi_svg, rsi_table,
                         note="Below 30 is conventionally read as oversold, above 70 as overbought.")

    macd = price.get("macd")
    macd_signal = price.get("macd_signal")
    macd_hist = price.get("macd_histogram")
    macd_status = "good" if (macd_hist or 0) > 0 else "critical" if (macd_hist or 0) < 0 else "neutral"
    macd_html = f"""
<div class="kpi-row" style="margin-top:6px;grid-template-columns:repeat(3,1fr);">
  {stat_tile("MACD", fmt_num(macd,3))}
  {stat_tile("Signal", fmt_num(macd_signal,3))}
  {stat_tile("Histogram", fmt_num(macd_hist,3), delta_text=("Bullish momentum" if macd_status=="good" else "Bearish momentum" if macd_status=="critical" else "Flat"), delta_cls=macd_status)}
</div>"""

    return f"""
<div class="card">
  <h2>Price & Technicals</h2>
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

    range_svg, range_table = range_meter(
        fundamentals.get("target_low_price"), fundamentals.get("target_mean_price"),
        fundamentals.get("target_median_price"), fundamentals.get("target_high_price"),
        bundle.get("price", {}).get("current_price"),
    )
    range_card = viz_card(
        f"Analyst target price range ({fundamentals.get('number_of_analyst_opinions') or 0} analysts)",
        range_svg, range_table,
    )

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

    surprises = earnings_est.get("earnings_surprise_history", []) or []
    surprise_items = [(s.get("quarter_end"), s.get("surprise_pct")) for s in surprises]
    if surprise_items:
        s_svg, s_table, s_legend = diverging_bar_horizontal(surprise_items, value_fmt=lambda v: fmt_pct(v))
        surprise_card = viz_card("EPS surprise history (actual vs. estimate)", s_svg, s_table, s_legend)
    else:
        surprise_card = viz_card("EPS surprise history", "<svg></svg>", empty_state())

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
<div class="card full">
  <h2>Analyst Ratings & Estimates</h2>
  <div class="card-sub">Recommendation: {esc(fundamentals.get('analyst_recommendation') or '—')} · last {analyst_ratings.get('lookback_days', 60)} days of rating actions</div>
  <div class="grid" style="grid-template-columns:1fr 1fr;">
    <div>{range_card}{surprise_card}</div>
    <div>
      <div class="viz-card"><div class="viz-card-head"><span class="viz-title">Recent rating actions</span></div>{actions_table}</div>
      <div class="viz-card" style="margin-top:16px;"><div class="viz-card-head"><span class="viz-title">EPS estimate trend (Street consensus)</span></div>{trend_table}</div>
    </div>
  </div>
</div>"""


def section_relative_performance(bundle):
    rp = bundle.get("relative_performance", {}) or {}
    cats = ["20-day return", "1-year return"]
    series = [
        ("Stock", "var(--series-1)", [rp.get("stock_pct_change_20d"), rp.get("stock_pct_change_1y")]),
        ("S&P 500", "var(--series-2)", [rp.get("benchmark_pct_change_20d"), rp.get("benchmark_pct_change_1y")]),
    ]
    if rp.get("sector_etf"):
        series.append((f"Sector ({rp.get('sector_etf')})", "var(--series-3)",
                        [rp.get("sector_pct_change_20d"), rp.get("sector_pct_change_1y")]))

    items = []
    for i, cat in enumerate(cats):
        for name, _, vals in series:
            items.append((f"{name} — {cat}", vals[i]))
    svg, table = bar_chart_horizontal(items, value_fmt=lambda v: fmt_pct(v))
    leg = legend([(name, color) for name, color, _ in series])
    perf_card = viz_card("Return vs. benchmark & sector", svg, table, leg)

    pe_tiles = f"""
<div class="kpi-row" style="grid-template-columns:repeat(3,1fr);margin-top:12px;">
  {stat_tile("Stock P/E", fmt_num(rp.get('stock_pe_ratio'),1))}
  {stat_tile("P/E vs S&P 500", fmt_pct(rp.get('pe_premium_vs_benchmark_pct')), sub=f"S&P 500 P/E {fmt_num(rp.get('benchmark_pe_ratio'),1)}")}
  {stat_tile("P/E vs sector", fmt_pct(rp.get('pe_premium_vs_sector_pct')), sub=f"Sector P/E {fmt_num(rp.get('sector_pe_ratio'),1)}")}
</div>"""

    return f"""
<div class="card full">
  <h2>Relative Performance & Valuation</h2>
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
    stack_card = viz_card("Institutional vs. insider ownership", stack_svg, stack_table, stack_legend)

    holders = inst.get("top_institutional_holders", []) or []
    holders_rows = [[h.get("holder"), fmt_num(h.get("shares")), fmt_pct(h.get("pct_out"), signed=False, decimals=2), fmt_usd(h.get("value"))] for h in holders]
    holders_table = data_table(["Holder", "Shares", "% out", "Value"], holders_rows)

    insiders = (bundle.get("insider_transactions", {}) or {}).get("transactions", []) or []
    insider_rows = []
    for t in insiders[:12]:
        direction_badge = badge(t.get("direction") or "—", "good" if t.get("direction") == "buy" else "neutral")
        insider_rows.append([t.get("date") or "—", t.get("owner") or "—", t.get("title") or "—",
                              direction_badge, fmt_num(t.get("shares")), fmt_price(t.get("price_per_share")) if t.get("price_per_share") else "—"])
    insider_table = data_table(["Date", "Owner", "Title", "Direction", "Shares", "Price"], insider_rows)

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
<div class="card full">
  <h2>Ownership</h2>
  <div class="card-sub">Snapshot of current holders — not a quarter-over-quarter 13F change (see data notes).</div>
  <div class="grid" style="grid-template-columns:1fr 1fr;">
    <div>
      {stack_card}
      <div class="viz-card" style="margin-top:16px;"><div class="viz-card-head"><span class="viz-title">Top institutional holders</span></div>{holders_table}</div>
      <div class="viz-card" style="margin-top:16px;"><div class="viz-card-head"><span class="viz-title">Schedule 13D/13G (&gt;5% stakes)</span></div>{ben_table if ben_rows else empty_state()}</div>
    </div>
    <div>
      <div class="viz-card"><div class="viz-card-head"><span class="viz-title">Insider transactions (Form 4)</span></div>{insider_table if insider_rows else empty_state()}</div>
      <div class="viz-card" style="margin-top:16px;"><div class="viz-card-head"><span class="viz-title">Form 144 proposed sales</span></div>{f144_table if f144_rows else empty_state()}</div>
    </div>
  </div>
</div>"""


def section_financials(bundle):
    bs = bundle.get("balance_sheet_health", {}) or {}
    inc = bundle.get("income_statement", {}) or {}
    annual = inc.get("annual") or {}
    quarterly = list(reversed(inc.get("quarterly") or []))  # oldest -> newest for chart

    bs_tiles = f"""
<div class="kpi-row" style="grid-template-columns:repeat(4,1fr);">
  {stat_tile("Total debt", fmt_usd(bs.get('total_debt')))}
  {stat_tile("Total cash", fmt_usd(bs.get('total_cash')))}
  {stat_tile("Debt / equity", fmt_num(bs.get('debt_to_equity'),1))}
  {stat_tile("Current ratio", fmt_num(bs.get('current_ratio'),2))}
  {stat_tile("Free cash flow", fmt_usd(bs.get('free_cash_flow')))}
  {stat_tile("Operating cash flow", fmt_usd(bs.get('operating_cash_flow')))}
  {stat_tile("Annual revenue", fmt_usd(annual.get('total_revenue')), sub=f"Period end {annual.get('period_end','—')}")}
  {stat_tile("Annual net income", fmt_usd(annual.get('net_income')), sub=f"Net margin {fmt_pct(annual.get('net_margin_pct'), signed=False)}")}
</div>"""

    cats = [q.get("period_end", "—") for q in quarterly]
    series = [
        ("Revenue", "var(--series-1)", [q.get("total_revenue") for q in quarterly]),
        ("Net income", "var(--series-2)", [q.get("net_income") for q in quarterly]),
    ]
    if cats:
        q_svg, q_table, q_legend = grouped_column_chart(cats, series)
        q_card = viz_card("Quarterly revenue & net income", q_svg, q_table, q_legend)
    else:
        q_card = viz_card("Quarterly revenue & net income", "<svg></svg>", empty_state())

    return f"""
<div class="card full">
  <h2>Financials</h2>
  {bs_tiles}
  {q_card}
</div>"""


def section_dividends_options_macro_social(bundle):
    div = bundle.get("dividends_buybacks", {}) or {}
    opt = bundle.get("options_sentiment", {}) or {}
    macro = bundle.get("macro_context", {}) or {}
    soc = bundle.get("social_sentiment", {}) or {}

    div_tiles = f"""
<div class="kpi-row" style="grid-template-columns:repeat(3,1fr);">
  {stat_tile("Dividend yield", fmt_pct(div.get('dividend_yield_pct'), signed=False) if div.get('dividend_yield_pct') is not None else "None")}
  {stat_tile("Payout ratio", fmt_pct(div.get('payout_ratio_pct'), signed=False))}
  {stat_tile("5y avg yield", fmt_pct(div.get('five_year_avg_dividend_yield_pct'), signed=False) if div.get('five_year_avg_dividend_yield_pct') is not None else "—")}
</div>"""
    buybacks = div.get("buybacks_recent_quarters", []) or []
    bb_items = [(b.get("quarter_end"), b.get("buyback_usd")) for b in buybacks]
    if bb_items:
        bb_svg, bb_table = bar_chart_horizontal(bb_items, value_fmt=fmt_usd)
        bb_card = viz_card("Quarterly buyback spend", bb_svg, bb_table)
    else:
        bb_card = viz_card("Quarterly buyback spend", "<svg></svg>", empty_state("No buyback activity found."))

    opt_reliable = opt.get("put_call_volume_ratio") is not None
    opt_html = f"""
<div class="kpi-row" style="grid-template-columns:repeat(2,1fr);">
  {stat_tile("Put/call volume ratio", fmt_num(opt.get('put_call_volume_ratio'),3) if opt_reliable else "—")}
  {stat_tile("Put/call open interest ratio", fmt_num(opt.get('put_call_open_interest_ratio'),3) if opt_reliable else "—")}
</div>
<div style="margin-top:10px;">{badge("IV/skew fields unreliable — see note", "warning")}</div>
<div class="viz-note" style="margin-top:8px;">{esc(opt.get('note') or '')}</div>"""

    macro_tiles = f"""
<div class="kpi-row" style="grid-template-columns:repeat(2,1fr);">
  {stat_tile("VIX level", fmt_num(macro.get('vix_level'),1), delta_text=fmt_num(macro.get('vix_change_20d'),1)+" (20d)" if macro.get('vix_change_20d') is not None else None, delta_cls=delta_class(macro.get('vix_change_20d'), invert=True))}
  {stat_tile("10Y Treasury yield", fmt_pct(macro.get('treasury_10y_yield_pct'), signed=False), delta_text=fmt_pct(macro.get('treasury_10y_yield_change_20d_pct'))+" (20d)" if macro.get('treasury_10y_yield_change_20d_pct') is not None else None, delta_cls=delta_class(macro.get('treasury_10y_yield_change_20d_pct'), invert=True))}
</div>
<div class="viz-note">Not ticker-specific — same for every ticker checked the same day.</div>"""

    sent_svg, sent_table, sent_legend = diverging_stacked_sentiment(
        soc.get("bearish_count", 0), soc.get("untagged_count", 0), soc.get("bullish_count", 0)
    )
    sent_card = viz_card(f"Social sentiment — StockTwits ({soc.get('message_count', 0)} recent posts)",
                          sent_svg, sent_table, sent_legend,
                          note="Unmoderated public chatter — a crowd-mood gauge, not verified fact.")
    samples = soc.get("sample_messages_unverified", []) or []
    sample_html = "".join(
        f'<div class="news-item"><div class="meta">{esc(m.get("created_at"))} · {esc(m.get("sentiment") or "untagged")}</div>'
        f'<div class="snippet">{esc(m.get("body"))}</div></div>'
        for m in samples[:5]
    ) or empty_state()

    return f"""
<div class="card full">
  <h2>Dividends, Buybacks, Options & Sentiment</h2>
  <div class="grid" style="grid-template-columns:1fr 1fr;">
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
<div class="card full">
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
<div class="card full">
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

def build_dashboard(bundle: dict) -> str:
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
{section_header(bundle)}
<div class="wrap">
  {section_kpis(bundle)}
  <div class="grid">
    {''.join(sections)}
  </div>
</div>
<footer class="disclaimer">
  StockLLM is a research/decision-support tool. It is NOT financial advice and never places trades.
  This dashboard renders exactly what is in the underlying JSON research bundle — nothing here is
  re-derived, judged, or fact-checked beyond what the data-fetch layer already notes.
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
