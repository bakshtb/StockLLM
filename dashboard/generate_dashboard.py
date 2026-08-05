"""
Generates an offline HTML dashboard from an ADELE research bundle JSON
file (the same JSON produced by `data/bundle.py`, or written to disk via
`python main.py check TICKER --dry-run -o file.json`).

No CDN at request time, works with no internet access once built -- but this
is no longer a single self-contained file: charts render client-side via
Apache ECharts, and CSS/JS live in webui/ (a Vite project -- see
webui/src/js/hydrate.js for the ECharts hydration logic and that file's own
comments for why a real charting library replaced hand-rolled SVG chart
geometry). load_built_assets() below reads webui's build output
(dashboard/assets/dist/, produced by `npm run build`); every function that
writes the generated HTML to disk must also call
dashboard.assets.ensure_vendored_assets() on that same output directory, or
the page will load with no charts (it degrades to table-only view
automatically in that case -- see hydrate.js -- but that's a fallback, not
the intended experience).

Usage:
    python -m dashboard.generate_dashboard mobileye.json
    python -m dashboard.generate_dashboard mobileye.json -o report.html

This is a pure rendering layer: it only formats what's already in the bundle
JSON (see data/bundle.py for what's in there and why) and makes no network
calls and no judgment calls of its own about the data.
"""

import argparse
import base64
import datetime as dt
import html
import json
import os
import sys
import threading

from dashboard.assets import ensure_vendored_assets
from dashboard.llm_export import build_llm_export_markdown

# ============================================================================
# CSS/JS used to live here as CSS_STYLE/JS_SCRIPT string constants, inlined
# directly into every generated page. They now live as real files under
# webui/ (a Vite project -- see webui/vite.config.js), built into
# dashboard/assets/dist/ by `npm run build` (or the Docker image's builder
# stage; see Dockerfile). load_built_assets() below reads Vite's own
# manifest.json to find the current hashed filenames and link them instead.
# Color roles specifically: verbatim from the dataviz skill's reference
# palette (bundled-skills/.../dataviz/references/palette.md) -- do not
# hand-tune a hex anywhere; if the brand palette ever changes, swap the
# values in webui/src/styles/tokens.css only.
# ============================================================================

_DIST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "dist")
_MANIFEST_PATH = os.path.join(_DIST_DIR, ".vite", "manifest.json")


def load_built_assets() -> dict:
    """Returns {"css": "assets/main-XXXX.css", "js": "assets/main-XXXX.js"}
    (paths relative to dashboard/assets/dist/) by reading webui's Vite build
    manifest. Raises loudly if it's missing/unreadable rather than silently
    shipping a dashboard with no styling or interactivity -- unlike a
    vendored asset (icon.png), there's no sensible fallback for a missing JS
    bundle, so this must fail at generation time, not render time."""
    try:
        with open(_MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        entry = manifest["src/main.js"]
        return {"css": entry["css"][0], "js": entry["file"]}
    except (OSError, KeyError, IndexError, json.JSONDecodeError) as e:
        raise RuntimeError(
            f"webui build output not found or invalid at {_MANIFEST_PATH} -- "
            "run `npm ci && npm run build` inside webui/ before generating a "
            "dashboard (see webui/package.json)."
        ) from e


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
    "ai_recommendation": "The output of ADELE's own 6-agent pipeline: a Bull agent argues the case to buy, a Bear agent argues the case against, two independent Skeptics (different AI models) critique both for unsupported claims, a Quant Checker verifies the specific numbers cited, and a Judge weighs everything (including all the data below) into one final call. This is the one section that's an AI-generated opinion, not raw data — read the reasoning and key risks, not just the verdict, and remember this is a research aid, not financial advice.",
    "fair_value": "The Judge's estimate of what this stock is worth TODAY, based on the bull/bear cases and the data below — not a prediction of where the price will be at some future date. If the current price is below this range, the AI sees it as undervalued; above the range, overvalued. Treat this the same as the recommendation above: an AI-generated opinion, not a guarantee.",
    "cpi_yoy": "How much prices for everyday goods have risen over the past 12 months, economy-wide — not specific to this company. High inflation tends to pressure the Federal Reserve to keep interest rates higher, which (like the 10Y Treasury yield above) tends to weigh more on expensive/high-growth stocks. Only shown if a free FRED API key is configured.",
    "unemployment_rate": "The percentage of the U.S. workforce currently without a job and looking for one. A rising rate often signals a slowing economy; a falling rate often signals a strong one. Not specific to this company. Only shown if a free FRED API key is configured.",
    "fed_funds_rate": "The interest rate the Federal Reserve sets for banks lending to each other overnight — the actual lever the Fed uses to fight inflation (raise it) or support growth (lower it). Higher rates generally make borrowing more expensive economy-wide, including for this company. Only shown if a free FRED API key is configured.",
    "yield_curve": "The gap between the 10-year and 2-year U.S. Treasury yields. Normally longer loans pay more interest, so this is usually positive. When it goes negative (\"inverted\"), it means investors expect the economy to weaken — historically a widely-watched recession warning sign. Not specific to this company. Only shown if a free FRED API key is configured.",
    "dcf_valuation": "An independent \"discounted cash flow\" fair-value estimate from Financial Modeling Prep — a different valuation method than analyst price targets, estimating what the stock is worth based on projecting the company's future cash flows. A second opinion to compare against the analyst target range and the AI's own fair-value estimate above. Only shown if a free FMP API key is configured.",
    "peg_ratio": "P/E ratio adjusted for the company's growth rate. A P/E of 30 looks expensive on its own, but if earnings are growing 30%/year, a PEG near 1.0 suggests that growth may justify the price. Below 1.0 is traditionally read as potentially undervalued relative to growth; above 2.0 as potentially overvalued. Only shown if a free FMP API key is configured.",
    "insider_sentiment_mspr": "Finnhub's own monthly score for whether company insiders (executives, directors) were net buying or net selling their own stock recently — positive means more buying, negative means more selling. A different, summarized view on top of the individual insider trades listed below. Only shown if the same Finnhub key used for news is configured.",
    "recommendation_trend": "How many analysts rated this stock Strong Buy/Buy/Hold/Sell/Strong Sell in recent months, and whether that mix is improving or deteriorating over time — a trend, not just a single snapshot. A different view than the individual rating actions listed elsewhere. Only shown if a Finnhub key is configured.",
    "section_backtests": "A \"backtest\" mechanically replays a fixed, well-known trading rule (e.g. \"buy when RSI is oversold\") against this stock's own past prices to see what would actually have happened -- no AI, no opinion, just a rule applied to real history. Past results never guarantee future ones, but they're real evidence instead of a guess. A small 0.1% trading cost is assumed per trade so results aren't overstated.",
    "backtest_win_rate": "Out of every trade this rule made, the percentage that ended in a profit. A low number here doesn't automatically mean a bad strategy: some rules (especially ones that ride a trend for as long as it lasts) lose money on most of their trades but make so much more on the rare big winners than they lose on the frequent small losers that they still come out far ahead overall -- check the Return above, not just this number alone, before judging a rule as good or bad.",
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
    max-width: 640px rule in webui/src/styles/responsive.css. No JS, pure CSS.
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


# ============================================================================
# ECharts chart registry
#
# Every chart function below builds a plain-dict ECharts "option" (data only
# -- colors are left as literal "var(--x)" strings, formatters as string
# tokens; see webui/src/js/hydrate.js's hydrateOption() for where those
# get resolved into real values/functions client-side) and calls
# register_chart() to get back an HTML placeholder div. build_dashboard()
# drains the registry once per call and serializes it as a single
# `window.__CHARTS__` <script> block near the end of the page.
#
# thread-local, not a plain module-level list: webapp/app.py serves via
# waitress, which is multi-threaded by default -- a shared mutable list
# would let two concurrent dashboard builds corrupt each other's charts.
# ============================================================================

_chart_state = threading.local()


def _reset_chart_registry():
    _chart_state.charts = []
    _chart_state.counter = 0


def register_chart(option: dict, height_px: int, aria_label: str = "chart") -> str:
    if not hasattr(_chart_state, "charts"):
        _reset_chart_registry()
    _chart_state.counter += 1
    chart_id = f"chart-{_chart_state.counter}"
    _chart_state.charts.append((chart_id, option))
    return (
        f'<div id="{chart_id}" class="echarts-container" role="img" '
        f'aria-label="{esc(aria_label)}" style="height:{height_px}px"></div>'
    )


def _drain_chart_registry():
    charts = getattr(_chart_state, "charts", [])
    _reset_chart_registry()
    return dict(charts)


def viz_card(title, chart_html, table_html, legend_html="", note="", info=None):
    """chart_html: the HTML returned by register_chart(), or None for empty
    data -- renders the table only, no chart pane, when None."""
    icon = info_icon(info) if info else ""
    chart_block = f'<div class="viz-chart">{chart_html}{legend_html}</div>' if chart_html else ""
    toggle = '<button type="button" class="viz-toggle" aria-pressed="false">View as table</button>' if chart_html else ""
    table_class = "viz-table" if chart_html else "viz-table viz-table-only"
    return f"""
<div class="viz-card">
  <div class="viz-card-head">
    <span class="viz-title">{esc(title)}{icon}</span>
    {toggle}
  </div>
  {chart_block}
  <div class="{table_class}">{table_html}</div>
  {f'<div class="viz-note">{esc(note)}</div>' if note else ''}
</div>"""


def legend(items):
    """items: list of (label, color_css_var)"""
    keys = "".join(
        f'<span class="key"><span class="swatch" style="background:{color}"></span>{esc(label)}</span>'
        for label, color in items
    )
    return f'<div class="viz-legend">{keys}</div>'


def subtabs(group_id, tabs, bar_class=""):
    """tabs: list of (label, panel_html). Splits one crowded section into
    focused sub-views (see section_ownership/section_dividends_options_macro_
    social) via a pill bar matching .range-btn's visual language, toggled
    client-side by webui/src/js/subtabs.js. Every panel is fully rendered
    server-side; only the first carries is-active by default, so a
    JS-disabled reader still sees a complete, correctly-laid-out first tab.
    group_id must be unique on the page (multiple tab groups can coexist,
    including nested -- see build_dashboard()'s top-level "main" group
    wrapping section_ownership's own "ownership" group).

    The bar carries data-group="{group_id}" and the panels wrapper carries
    data-panels-for="{group_id}" -- subtabs.js links them by that attribute,
    not DOM adjacency, specifically because build_dashboard() renders the
    top-level "main" bar inside .sticky-top (so it sticks to the topbar)
    while its panels live in .wrap several elements later, not as a
    sibling (an earlier version used bar.nextElementSibling and silently
    never switched the top-level panels because of exactly this -- the
    button's is-active toggle worked fine either way, which is what made
    it easy to miss until actually clicking a tab and checking the
    content, not just the button state).

    bar_class: extra class(es) on the pill bar itself (e.g. "page-tabs"
    for the top-level group, which is sticky and styled larger -- see
    components.css -- to read as primary navigation, not a second copy of
    the same secondary in-section grouping control)."""
    buttons, panels = [], []
    for i, (label, panel_html) in enumerate(tabs):
        panel_id = f"{group_id}-{i}"
        active = " is-active" if i == 0 else ""
        buttons.append(f'<button type="button" class="subtab-btn{active}" data-target="{panel_id}">{esc(label)}</button>')
        panels.append(f'<div class="subtab-panel{active}" data-panel="{panel_id}">{panel_html}</div>')
    bar_cls = f"subtabs {bar_class}".strip()
    bar_html = f'<div class="{bar_cls}" role="tablist" data-group="{group_id}">{"".join(buttons)}</div>'
    panels_html = f'<div data-panels-for="{group_id}">{"".join(panels)}</div>'
    return bar_html, panels_html


# ============================================================================
# Charts
# ============================================================================

def bar_chart_horizontal(items, unit="", value_fmt=None):
    """items: list of (label, value). Single series, magnitude comparison."""
    items = [it for it in items if it[1] is not None]
    if not items:
        return None, empty_state()
    value_fmt = value_fmt or (lambda v: fmt_num(v, 2))
    row_h, gap, pad = 22, 12, 16
    H = pad * 2 + len(items) * (row_h + gap) - gap

    option = {
        "grid": {"left": 8, "right": 80, "top": pad, "bottom": pad, "containLabel": True},
        "tooltip": {"trigger": "item", "formatter": "__tooltipFmt__"},
        "xAxis": {"type": "value", "show": False},
        "yAxis": {
            "type": "category", "inverse": True, "data": [label for label, _ in items],
            "axisLine": {"show": False}, "axisTick": {"show": False},
            "axisLabel": {"color": "var(--text-secondary)", "fontSize": 13},
        },
        "series": [{
            "type": "bar", "barMaxWidth": row_h,
            "itemStyle": {"color": "var(--series-1)", "borderRadius": [0, 4, 4, 0]},
            "label": {"show": True, "position": "right", "color": "var(--text-primary)", "formatter": "__labelFmt__"},
            "data": [{"value": v, "fmt": value_fmt(v)} for _, v in items],
        }],
    }
    chart_html = register_chart(option, H, aria_label=unit or "bar chart")

    rows = [[label, value_fmt(v)] for label, v in items]
    table = data_table(["Metric", "Value"], rows)
    return chart_html, table


INSIDE_LABEL_FRACTION = 0.2  # a bar this fraction of max_v or longer gets its value label inside (light text), not past its tip -- avoids a long negative bar's label landing on top of that row's own name label


def diverging_bar_horizontal(items, value_fmt=None):
    """items: list of (label, value) where value can be +/-. Baseline at center."""
    items = [it for it in items if it[1] is not None]
    if not items:
        return None, empty_state(), ""
    value_fmt = value_fmt or (lambda v: fmt_pct(v))
    max_v = max(abs(v) for _, v in items) or 1
    row_h, gap, pad = 22, 12, 16
    H = pad * 2 + len(items) * (row_h + gap) - gap

    data = []
    for label, v in items:
        long_enough = (abs(v) / max_v) >= INSIDE_LABEL_FRACTION
        is_pos = v >= 0
        color = "var(--diverge-pos)" if is_pos else "var(--diverge-neg)"
        position = ("insideRight" if is_pos else "insideLeft") if long_enough else ("right" if is_pos else "left")
        data.append({
            "value": v, "fmt": value_fmt(v),
            "itemStyle": {"color": color},
            "label": {
                "position": position,
                "color": "#fff" if long_enough else "var(--text-primary)",
                "fontWeight": 600 if long_enough else 400,
            },
        })

    option = {
        "grid": {"left": 8, "right": 8, "top": pad, "bottom": pad, "containLabel": True},
        "tooltip": {"trigger": "item", "formatter": "__tooltipFmt__"},
        "xAxis": {"type": "value", "min": -max_v, "max": max_v, "show": False, "splitLine": {"show": False}},
        "yAxis": {
            "type": "category", "inverse": True, "data": [label for label, _ in items],
            "axisLine": {"show": False}, "axisTick": {"show": False},
            "axisLabel": {"color": "var(--text-secondary)", "fontSize": 13},
        },
        "series": [{
            "type": "bar", "barMaxWidth": row_h,
            "markLine": {"symbol": "none", "silent": True, "lineStyle": {"color": "var(--baseline)"}, "data": [{"xAxis": 0}]},
            "label": {"show": True, "formatter": "__labelFmt__"},
            "data": data,
        }],
    }
    chart_html = register_chart(option, H, aria_label="values relative to baseline")

    rows = [[label, value_fmt(v)] for label, v in items]
    table = data_table(["Period", "Value"], rows)
    leg = legend([("Beat / above baseline", "var(--diverge-pos)"), ("Miss / below baseline", "var(--diverge-neg)")])
    return chart_html, table, leg


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
        return None, empty_state(), ""
    max_abs = max(abs(v) for v in all_vals) or 1

    # Series identity (name + color) is defined by first occurrence, in
    # order -- every group is expected to carry the same series names (e.g.
    # Stock/S&P 500/Sector, once per time-window group). ECharts groups
    # same-category series side by side natively -- category = each group
    # (time window), one bar per series within it, colored by series
    # identity, diverging from a shared zero baseline the axis itself
    # provides (no manual centering math).
    series_order, series_colors = [], {}
    for _, items in groups:
        for name, color, _ in items:
            if name not in series_colors:
                series_order.append(name)
                series_colors[name] = color
    n_series = len(series_order) or 1

    row_h, gap, group_gap, header_h, pad = 20, 8, 22, 22, 16
    H = pad * 2 + len(groups) * (n_series * (row_h + gap) - gap + group_gap) - group_gap

    series = []
    for name in series_order:
        data = []
        for group_title, items in groups:
            v = next((v for n2, _, v in items if n2 == name), None)
            data.append({"value": v, "fmt": value_fmt(v), "name": f"{name} — {group_title}"} if v is not None else None)
        series.append({
            "name": name, "type": "bar",
            "itemStyle": {"color": series_colors[name]},
            "label": {"show": True, "formatter": "__labelFmt__", "color": "var(--text-primary)"},
            "data": data,
        })

    option = {
        "grid": {"left": 8, "right": 8, "top": header_h, "bottom": pad, "containLabel": True},
        "tooltip": {"trigger": "item", "formatter": "__tooltipFmt__"},
        "legend": {"show": False},  # the HTML legend below is authoritative -- avoid rendering two
        "xAxis": {"type": "value", "min": -max_abs, "max": max_abs, "show": False},
        "yAxis": {
            "type": "category", "inverse": True, "data": [g for g, _ in groups],
            "axisLine": {"show": False}, "axisTick": {"show": False},
            "axisLabel": {"color": "var(--text-primary)", "fontWeight": 600, "fontSize": 13.5},
        },
        "series": series,
    }
    chart_html = register_chart(option, H, aria_label="grouped comparison chart")

    rows = []
    for group_title, items in groups:
        for name, _, v in items:
            rows.append([group_title, name, value_fmt(v) if v is not None else "—"])
    table = data_table(["Period", "Series", "Value"], rows)
    leg_items = groups[0][1] if groups else []
    leg = legend([(name, color) for name, color, _ in leg_items])
    return chart_html, table, leg


def grouped_column_chart(categories, series):
    """categories: list of str (x-axis). series: list of (name, color_var, [values])."""
    n_cat = len(categories)
    if n_cat == 0:
        return None, empty_state(), ""
    all_vals = [v for _, _, vals in series for v in vals if v is not None]
    if not all_vals:
        return None, empty_state(), ""
    max_v = max(all_vals)
    min_v = min(0, min(all_vals))
    H = 260

    echarts_series = []
    for name, color, vals in series:
        data = []
        for ci in range(n_cat):
            v = vals[ci] if ci < len(vals) else None
            if v is None:
                data.append(None)
                continue
            point = {"value": v, "fmt": fmt_usd(v, 1), "name": f"{categories[ci]} — {name}"}
            if ci == n_cat - 1:  # direct label on the last/most-recent category only
                point["label"] = {"show": True, "position": "top", "color": "var(--text-primary)", "formatter": "__labelFmt__"}
            data.append(point)
        echarts_series.append({
            "name": name, "type": "bar", "barMaxWidth": 24,
            "itemStyle": {"color": color},
            "data": data,
        })

    option = {
        "grid": {"left": 8, "right": 16, "top": 40, "bottom": 30, "containLabel": True},
        "tooltip": {"trigger": "item", "formatter": "__tooltipFmt__"},
        "legend": {"show": False},  # the HTML legend below is authoritative
        # A real, working greedy stagger for the last category's value
        # labels (see webui/src/js/hydrate.js's makeVerticalBarLabelStagger) -- the
        # declarative {"moveOverlap": "shiftY"} shorthand was tried first
        # and does not reliably move labels that have an explicit position
        # (confirmed by direct testing, not assumed).
        "labelLayout": "__verticalBarLabelStagger__",
        "xAxis": {
            "type": "category", "data": categories,
            "axisLine": {"lineStyle": {"color": "var(--baseline)"}},
            "axisLabel": {"color": "var(--text-secondary)", "fontSize": 12.5}, "axisTick": {"show": False},
        },
        "yAxis": {
            # interval forces exactly 3 gridline ticks (min/mid/max), matching
            # the old fixed 3-tick scheme instead of ECharts' default
            # "nice number" auto-ticking, which could vary chart to chart.
            "type": "value", "min": min_v, "max": max_v, "interval": (max_v - min_v) / 2 or 1,
            "splitLine": {"lineStyle": {"color": "var(--gridline)"}},
            "axisLabel": {"color": "var(--text-muted)", "fontSize": 12, "formatter": "__compactAxis__"},
        },
        "series": echarts_series,
    }
    chart_html = register_chart(option, H, aria_label="grouped column chart")

    headers = ["Quarter"] + [name for name, _, _ in series]
    rows = []
    for ci, cat in enumerate(categories):
        row = [cat] + [fmt_usd(vals[ci]) if ci < len(vals) and vals[ci] is not None else "—" for _, _, vals in series]
        rows.append(row)
    table = data_table(headers, rows)
    leg = legend([(name, color) for name, color, _ in series])
    return chart_html, table, leg


def _range_track_option(low, high, current, markers, current_label, label_fmt, corner_word_prefix=False):
    """Shared ECharts option for range_meter and range_position_plot: a
    value-axis track from low to high, named point markers (dots + labels),
    and a distinct triangle "current" marker. markers: list of (name, value,
    color_css_var). corner_word_prefix: range_meter's corner labels read
    "Low $215.00" / "High $400.00"; range_position_plot's read just the bare
    price ("$201.58") since its track already leads with a "Price vs..."
    card title -- the word would be redundant there.

    ECharts' labelLayout (set globally below) resolves label-vs-label
    collisions automatically -- Mean/Median crowding together, or "Current"
    crowding a Low/High corner label when the value sits near an edge (the
    old SVG version needed a hand-rolled stagger pass and a "suppress
    whichever label is in the way" compromise for exactly these two cases;
    neither is needed here). Low/High labels are centered on their own dot
    (no align override), same as every other marker -- an explicit
    align:"left"/"right" was tried first specifically to avoid clipping
    past the plot's edge, but a user reading the rendered page expected
    every dot to carry its own label directly above it the same way
    MA20/Mean/etc. do, not off to one side. The grid's left/right margin is
    widened instead (see below) to give a centered label room to clip
    against the SVG edge, without needing the label to land off to one side.
    """
    def low_high_fmt(word, v):
        return f"{word} {label_fmt(v)}" if corner_word_prefix else label_fmt(v)

    def clamp(v):
        # A marker (most commonly "current") can legitimately fall outside
        # [low, high] -- e.g. today's price above its own 52-week high on a
        # new-high day. The xAxis is fixed to [low, high], so an unclamped
        # coordinate would render off-chart (or not at all); pin it visually
        # to whichever edge it overshot instead of losing it.
        return max(low, min(high, v))

    # Low/High used to be symbolSize: 0 (invisible, relying on the track's
    # own rounded end-caps to imply an endpoint) -- given an explicit dot
    # here too, same size/border as every other marker, for visual
    # consistency across the whole track (found live: a user expected
    # every labeled point to carry the same dot the named markers do).
    # var(--text-secondary) keeps them visually neutral, since Low/High
    # aren't a categorical series the way MA20/Mean/etc. are.
    scatter_data = [
        {"value": [low, 0.5], "symbolSize": 18,
         "itemStyle": {"color": "var(--text-secondary)", "borderColor": "var(--surface-1)", "borderWidth": 2},
         "name": "Low", "fmt": low_high_fmt("Low", low),
         "label": {"show": True, "position": "top", "distance": 20, "color": "var(--text-secondary)",
                    "fontSize": 13.5, "formatter": "__labelFmt__"}},
        {"value": [high, 0.5], "symbolSize": 18,
         "itemStyle": {"color": "var(--text-secondary)", "borderColor": "var(--surface-1)", "borderWidth": 2},
         "name": "High", "fmt": low_high_fmt("High", high),
         "label": {"show": True, "position": "top", "distance": 20, "color": "var(--text-secondary)",
                    "fontSize": 13.5, "formatter": "__labelFmt__"}},
    ]
    for name, v, color in markers:
        scatter_data.append({
            # borderColor/borderWidth: at the series-level symbolSize (18,
            # below) a flat-colored dot still read as a thin sliver barely
            # poking above the 10px-thick track it sits on (found live from
            # a screenshot) -- a light ring gives every marker a crisp,
            # consistent edge against the track regardless of how close its
            # own color is to var(--gridline).
            "value": [clamp(v), 0.5],
            "itemStyle": {"color": color, "borderColor": "var(--surface-1)", "borderWidth": 2},
            "name": name, "fmt": label_fmt(v),
            "label": {"show": True, "position": "bottom", "color": "var(--text-secondary)", "formatter": "__labelFmt__"},
        })

    track_series = {
        # z: 1 -- ECharts does NOT paint cartesian series strictly in this
        # list's order (confirmed live by reading the actual rendered SVG's
        # element order): the scatter series below was painted BEFORE this
        # line regardless of array position, so the opaque 10px-thick track
        # drew right on top of every marker dot, hiding most of each one --
        # found live from a real screenshot ("the circles are still behind
        # the bar"). Explicit z (not array order) is what actually controls
        # paint order; the scatter series is given z: 2 to guarantee it
        # always paints above this track regardless of type-based defaults.
        "type": "line", "silent": True, "symbol": "none", "z": 1,
        "lineStyle": {"width": 10, "color": "var(--gridline)", "cap": "round"},
        "data": [[low, 0.5], [high, 0.5]],
    }
    if current is not None:
        track_series["markPoint"] = {
            # symbolSize must be set explicitly -- a path symbol with no
            # size renders at ECharts' default 50x50, ~4-5x this path's own
            # 12x10-unit coordinate space, oversized enough to visually
            # cover the High corner label whenever "current" sits close to
            # it (found live: a triangle wide enough to hide "$340.08"
            # entirely). [12, 10] renders the path at its own native size.
            "symbol": "path://M -6 -10 L 6 -10 L 0 0 Z", "symbolSize": [12, 10], "symbolOffset": [0, -16],
            "itemStyle": {"color": "var(--text-primary)"},
            "label": {"show": True, "position": "top", "fontWeight": 600, "color": "var(--text-primary)", "formatter": "__labelFmt__"},
            "data": [{"coord": [clamp(current), 0.5], "name": current_label, "fmt": label_fmt(current)}],
        }

    return {
        # left/right: wide enough that a centered Low/High label (up to
        # "High $400.00" -- range_meter's corner_word_prefix form, the
        # longest case) doesn't clip past the SVG edge now that it's
        # centered on its own dot instead of right/left-aligned inward.
        "grid": {"left": 55, "right": 55, "top": 50, "bottom": 40},
        "tooltip": {"trigger": "item", "formatter": "__tooltipFmt__"},
        # A real, working greedy stagger (see webui/src/js/hydrate.js's
        # makeRangeTrackLabelLayout) -- the declarative
        # {"moveOverlap": "shiftY"} shorthand was tried first and does not
        # reliably move labels that have an explicit position (confirmed
        # by direct testing, not assumed).
        "labelLayout": "__rangeTrackLabelLayout__",
        "xAxis": {"type": "value", "min": low, "max": high, "show": False},
        "yAxis": {"type": "value", "min": 0, "max": 1, "show": False},
        # symbolSize 18 vs. the track's own 10px width: markers must be
        # clearly larger than the line they sit on, or they read as a thin
        # colored sliver peeking out from behind it rather than a distinct
        # dot on top of it (found live from a screenshot -- 12 was only 1px
        # bigger than the track per side, effectively invisible).
        "series": [track_series, {"type": "scatter", "z": 2, "symbolSize": 18, "data": scatter_data}],
    }


def range_meter(low, mean, median, high, current, label_fmt=fmt_price):
    """Analyst target range: a track from low to high with mean/median/current markers."""
    if low is None or high is None or high <= low:
        return None, empty_state(), ""
    markers = []
    if mean is not None:
        markers.append(("Mean", mean, "var(--series-1)"))
    if median is not None and median != mean:
        markers.append(("Median", median, "var(--series-3)"))
    option = _range_track_option(low, high, current, markers, "Current", label_fmt, corner_word_prefix=True)
    chart_html = register_chart(option, 150, aria_label="analyst target price range")

    rows = [["Low", label_fmt(low)], ["Mean", label_fmt(mean)], ["Median", label_fmt(median)],
            ["High", label_fmt(high)], ["Current price", label_fmt(current)]]
    table = data_table(["Point", "Price"], rows)
    # The colored marker dots (Mean/Median) carry a bare price with no name
    # attached in the chart itself -- found live, a user couldn't tell
    # which dot was which. Low/High/Current aren't included here: Low/High
    # are self-evident track endpoints, and Current already carries its own
    # explicit "$X" label directly above the track.
    leg = legend([(name, color) for name, _, color in markers]) if markers else ""
    return chart_html, table, leg


def range_position_plot(low, high, current, markers, aria_label="value range", current_label="Current", label_fmt=fmt_price):
    """
    A dot plot on one shared axis: a track from low to high with named
    marker points placed by value, plus a distinct triangle marker for
    "current" (same visual language as range_meter's analyst-target
    track). This is the right form (dataviz skill: compare points along a
    single numeric scale) for values that live in a narrow band relative
    to their own magnitude -- e.g. price vs. its 52-week range and moving
    averages, all within a few percent of each other. A zero-anchored bar
    chart would render every bar as nearly the same length and hide
    exactly the relative positions that matter; a shared track shows them
    immediately.

    markers: list of (label, value, color_css_var), rendered as dots below
    the track with collision-avoiding label stagger. current is rendered
    separately, above the track, so it never collides with the dots.
    """
    if low is None or high is None or high <= low:
        return None, empty_state(), ""
    valid_markers = [(l, v, c) for l, v, c in markers if v is not None]
    option = _range_track_option(low, high, current, valid_markers, current_label, label_fmt)
    chart_html = register_chart(option, 150, aria_label=aria_label)

    rows = [[label, label_fmt(v)] for label, v, _ in valid_markers]
    if current is not None:
        rows.append([current_label, label_fmt(current)])
    rows.append(["Range", f"{label_fmt(low)} – {label_fmt(high)}"])
    table = data_table(["Point", "Price"], rows)
    # Same gap as range_meter above: bare-price marker dots with no name
    # attached in the chart itself, found live from a user screenshot of
    # this exact chart (MA20/MA50/MA200 were impossible to tell apart).
    leg = legend([(name, color) for name, _, color in valid_markers]) if valid_markers else ""
    return chart_html, table, leg


def gauge_meter(value, min_v, max_v, zones, label=""):
    """zones: list of (threshold_upto, color_var, status_name) covering
    min_v..max_v in order (e.g. RSI's oversold/neutral/overbought bands).

    Native ECharts type:"gauge" -- a real, deliberate visual-form change
    from the old horizontal zone-strip-with-a-dot to a semicircular dial
    (see CHANGELOG for why: the old version needed hand-tracked track_y/
    headline-offset math that clipped its own headline number against the
    SVG edge more than once). This is the idiomatic, well-supported way to
    render "single value + zones + a big number" -- a hand-built "linear
    gauge" custom series would just be re-building bespoke geometry again."""
    if value is None:
        return None, empty_state()
    span = (max_v - min_v) or 1
    # ECharts zone stops are fractions of [min_v, max_v], not absolute values.
    color_stops = [[(upto - min_v) / span, color] for upto, color, _ in zones]

    option = {
        "tooltip": {"trigger": "item", "formatter": "__tooltipFmt__"},
        "series": [{
            "type": "gauge", "startAngle": 180, "endAngle": 0,
            "min": min_v, "max": max_v,
            "radius": "100%", "center": ["50%", "85%"],
            "axisLine": {"lineStyle": {"width": 12, "color": color_stops}},
            # A "you are here" dot exactly on the colored band, not the
            # default needle from the pivot -- was `show: False` entirely
            # until a real user screenshot pointed out there was no visual
            # link at all between the big number and the band it's meant to
            # sit within. For icon:"circle", ECharts centers the dot at
            # HALF of `length` (confirmed empirically by reading the
            # rendered SVG's actual transform, not assumed from docs) --
            # 186% here lands the dot at 93% of the gauge's own radius,
            # i.e. the middle of the band (band spans ~86%-100% of radius
            # at width:12), and being a percentage (not a fixed px length)
            # it stays correctly on the band across every container width
            # this responsive chart can render at.
            "pointer": {
                "show": True, "icon": "circle", "length": "186%", "width": 16,
                "itemStyle": {"color": "var(--surface-1)", "borderColor": "var(--text-primary)", "borderWidth": 3},
            },
            "anchor": {"show": False},
            "axisTick": {"show": False}, "splitLine": {"show": False},
            "axisLabel": {"distance": -30, "color": "var(--text-muted)", "fontSize": 12},
            "detail": {
                "valueAnimation": False, "formatter": "{value}",
                "fontSize": 34, "fontWeight": 650, "offsetCenter": [0, "-30%"],
                "color": "var(--text-primary)",
            },
            "data": [{"value": round(value, 1), "name": label, "fmt": fmt_num(value, 1)}],
        }],
    }
    chart_html = register_chart(option, 170, aria_label=f"{label} gauge")

    table = data_table(["Metric", "Value"], [[label, fmt_num(value, 1)]])
    return chart_html, table


def stacked_bar_parts(parts_data, total=100.0):
    """parts_data: list of (label, value, color_var). Renders one horizontal stacked bar."""
    parts_data = [(l, v, c) for l, v, c in parts_data if v is not None and v > 0]
    if not parts_data:
        return None, empty_state(), ""
    n = len(parts_data)
    r = 4

    echarts_series = []
    for i, (label, v, color) in enumerate(parts_data):
        is_first, is_last = i == 0, i == n - 1
        # ECharts' 4-corner array ([top-left, top-right, bottom-right,
        # bottom-left], CSS order) directly replaces the old manual
        # rounded-rect path math: only the outermost edge of the first/
        # last segment in the stack gets rounded.
        echarts_series.append({
            "name": label, "type": "bar", "stack": "total", "barWidth": 24,
            "itemStyle": {
                "color": color,
                "borderRadius": [r if is_first else 0, r if is_last else 0, r if is_last else 0, r if is_first else 0],
            },
            "data": [{"value": v, "fmt": fmt_pct(v, signed=False), "name": label}],
        })

    option = {
        "grid": {"left": 4, "right": 4, "top": 4, "bottom": 4},
        "tooltip": {"trigger": "item", "formatter": "__tooltipFmt__"},
        "legend": {"show": False},  # the HTML legend below is authoritative
        "xAxis": {"type": "value", "max": total, "show": False},
        "yAxis": {"type": "category", "data": [""], "show": False},
        "series": echarts_series,
    }
    chart_html = register_chart(option, 60, aria_label="ownership breakdown")

    rows = [[label, fmt_pct(v, signed=False)] for label, v, _ in parts_data]
    table = data_table(["Holder type", "% of shares"], rows)
    leg = legend([(label, color) for label, _, color in parts_data])
    return chart_html, table, leg


def diverging_stacked_sentiment(bearish, untagged, bullish):
    """Diverging stacked bar centered on the neutral/untagged middle segment.

    ECharts' bar `stack` is bidirectional and self-centering by
    construction -- each series is placed further from zero in its own
    sign's direction, so a heavily skewed split (found live: 9 bullish vs.
    4 bearish; worse, 18 vs. 1) simply produces a long bar on one side and
    a short one on the other, never an overflow. No manual scale-factor
    math needed at all, unlike the SVG version this replaces. The
    "straddles zero" look comes from splitting the neutral segment into two
    equal halves, one declared on each side of zero -- a real, working
    layout trick, not a hack; each half still reports the true (not
    halved) count on hover.
    """
    total = (bearish or 0) + (untagged or 0) + (bullish or 0)
    if total == 0:
        return None, empty_state(), ""
    half_untagged = (untagged or 0) / 2
    bearish, bullish = bearish or 0, bullish or 0

    def seg(value, color, name, count, end_label=None):
        data = {"value": value, "fmt": f"{count} messages", "name": name}
        if end_label and count > 0:
            # A literal formatter string (not the shared "__labelFmt__"
            # token): the end-label shows the bare count ("4"), the
            # tooltip shows "4 messages" via the same datapoint's `fmt` --
            # two different display strings for one point, so this one
            # doesn't route through the generic fmt-reading formatter.
            data["label"] = {"show": True, "position": end_label, "color": "var(--text-primary)", "formatter": str(count)}
        return {"type": "bar", "stack": "s", "barWidth": 26, "itemStyle": {"color": color}, "data": [data]}

    # Declaration order = innermost-to-outermost per side (stacking walks
    # outward from zero in the order series are declared).
    echarts_series = [
        seg(-half_untagged, "var(--gridline)", "Untagged", untagged),
        seg(-bearish, "var(--diverge-neg)", "Bearish", bearish, end_label="left"),
        seg(half_untagged, "var(--gridline)", "Untagged", untagged),
        seg(bullish, "var(--diverge-pos)", "Bullish", bullish, end_label="right"),
    ]

    option = {
        "grid": {"left": 40, "right": 40, "top": 8, "bottom": 8},
        "tooltip": {"trigger": "item", "formatter": "__tooltipFmt__"},
        "legend": {"show": False},  # the HTML legend below is authoritative
        "xAxis": {"type": "value", "show": False},
        "yAxis": {"type": "category", "data": [""], "show": False},
        "series": echarts_series,
    }
    chart_html = register_chart(option, 70, aria_label="social sentiment split")

    table = data_table(["Sentiment", "Messages"], [["Bearish", bearish], ["Untagged", untagged], ["Bullish", bullish]])
    leg = legend([("Bearish", "var(--diverge-neg)"), ("Untagged", "var(--gridline)"), ("Bullish", "var(--diverge-pos)")])
    return chart_html, table, leg


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

    Every segment's plotted value is that segment's percent of this call's
    own total, not its raw count, and the x-axis is pinned to a fixed
    [-100, 100] range on every call (not scaled to fit each instance's own
    data) -- section_analyst() renders several of these as independent
    small multiples, one per period, and periods need to stay visually
    comparable regardless of how many analysts covered each one. This also
    means, as a side effect of ECharts' bidirectional stacking (see
    diverging_stacked_sentiment's docstring), that no skew can ever
    overflow the fixed range -- the old SVG version's per-instance
    overflow-prevention scale factor was a real, if secondary, source of
    inconsistency between small multiples too: two periods with different
    skew could end up scaled to different effective widths.
    """
    total = (mid_value or 0) + sum(v or 0 for _, v in neg_segments) + sum(v or 0 for _, v in pos_segments)
    if total == 0:
        return None, empty_state(), ""

    def pct(v):
        return (v or 0) / total * 100

    def opacity_for(i, n):
        return 0.55 + 0.45 * ((i + 1) / n)

    half_mid = pct(mid_value) / 2
    neg_active = [seg for seg in neg_segments if seg[1]]
    pos_active = [seg for seg in pos_segments if seg[1]]

    # Declaration order = innermost-to-outermost per side (stacking walks
    # outward from zero in the order series are declared).
    echarts_series = [
        {"type": "bar", "stack": "s", "barWidth": 26, "itemStyle": {"color": "var(--gridline)"},
         "data": [{"value": -half_mid, "fmt": fmt_num(mid_value), "name": mid_label}]},
    ]
    for i, (label, v) in enumerate(neg_active):
        data = {"value": -pct(v), "fmt": fmt_num(v), "name": label}
        if i == len(neg_active) - 1:  # outermost negative segment: running total, direct-labeled
            data["label"] = {"show": True, "position": "left", "color": "var(--text-primary)",
                              "formatter": fmt_num(sum(v2 for _, v2 in neg_active))}
        echarts_series.append({
            "type": "bar", "stack": "s", "barWidth": 26,
            "itemStyle": {"color": "var(--diverge-neg)", "opacity": opacity_for(i, len(neg_active))},
            "data": [data],
        })

    echarts_series.append({
        "type": "bar", "stack": "s", "barWidth": 26, "itemStyle": {"color": "var(--gridline)"},
        "data": [{"value": half_mid, "fmt": fmt_num(mid_value), "name": mid_label}],
    })
    for i, (label, v) in enumerate(pos_active):
        data = {"value": pct(v), "fmt": fmt_num(v), "name": label}
        if i == len(pos_active) - 1:  # outermost positive segment: running total, direct-labeled
            data["label"] = {"show": True, "position": "right", "color": "var(--text-primary)",
                              "formatter": fmt_num(sum(v2 for _, v2 in pos_active))}
        echarts_series.append({
            "type": "bar", "stack": "s", "barWidth": 26,
            "itemStyle": {"color": "var(--diverge-pos)", "opacity": opacity_for(i, len(pos_active))},
            "data": [data],
        })

    option = {
        "grid": {"left": 40, "right": 40, "top": 8, "bottom": 8},
        "tooltip": {"trigger": "item", "formatter": "__tooltipFmt__"},
        "legend": {"show": False},  # the HTML legend below is authoritative
        "xAxis": {"type": "value", "min": -100, "max": 100, "show": False},
        "yAxis": {"type": "category", "data": [""], "show": False},
        "series": echarts_series,
    }
    chart_html = register_chart(option, 70, aria_label=aria_label)

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
    return chart_html, table, leg


def price_history_chart(price_series, aria_label="price history"):
    """A full interactive price chart -- a colored area line (green/red by
    net change over the series, gradient-filled and topped with a filled
    dot at the latest close, like Google Finance's quote chart) with
    volume and MA20/50/200 overlays, drag-to-zoom (mouse wheel/pinch + a
    slider), and a crosshair tooltip -- the "real stock app" chart the
    Price & Technicals section was missing. Built entirely from
    price_series, which backtest/engine.py already fetches once per run
    and shares with every strategy's own trade chart; this reuses the
    exact same list, no separate fetch of its own.

    Line, not candlesticks: candlesticks read as a trading/execution tool
    (each bar is a single day's open/high/low/close), which doesn't match
    this dashboard's research/decision-support framing -- a smooth line is
    also what most non-trader users expect when they picture "a stock
    chart". OHLC detail isn't lost from the bundle, just not charted here.

    The gradient fill and end-of-line dot are real, theme-aware colors
    resolved client-side (see hydrate.js's areaGradient()/hexToRgba()),
    not baked into this HTML -- the "__areaGradientPos__"/"Neg__" tokens
    below are the same "leave a token, let JS resolve it" pattern this
    file already uses for every other formatter/color (see this module's
    top-of-file comment on register_chart()). No "previous close" dashed
    reference line, unlike Google's: that's specifically an intraday
    (today vs. yesterday's close) concept, and this chart shows daily
    closes over months/years, not intraday ticks -- there's no single
    "previous close" value that stays meaningful across every zoom level
    here, so it's not faked in.

    Verified structurally against the real vendored echarts.min.js in a
    standalone headless-chromium harness before wiring in here: 5 series
    render, the default ~1-year zoom window computes correctly, and the
    range-preset buttons' dataZoom dispatch actually changes the visible
    range (see HANDOFF.md for the item covering this).
    """
    if not price_series:
        return None
    dates = [p["date"] for p in price_series]
    n = len(price_series)

    closes = []
    for p in price_series:
        c = p.get("close")
        closes.append(None if c is None else {"value": c, "fmt": fmt_price(c)})
    first_close = next((p["close"] for p in price_series if p.get("close") is not None), None)
    last_idx, last_close = next(
        ((i, p["close"]) for i, p in reversed(list(enumerate(price_series))) if p.get("close") is not None),
        (None, None),
    )
    is_down = first_close is not None and last_close is not None and last_close < first_close
    line_color = "var(--diverge-neg)" if is_down else "var(--diverge-pos)"
    area_gradient = "__areaGradientNeg__" if is_down else "__areaGradientPos__"
    # A filled dot at the most recent close, like Google Finance's quote
    # chart -- every range-preset button (see chart-toolbar.js) zooms to
    # end:100, so the latest point is always at the visible right edge.
    end_marker = (
        {
            "symbol": "circle", "symbolSize": 7,
            "itemStyle": {"color": line_color},
            "label": {"show": False},
            "data": [{"coord": [last_idx, last_close]}],
        }
        if last_idx is not None else None
    )

    def _ma_series(key, color, name):
        data = []
        for p in price_series:
            v = p.get(key)
            data.append(None if v is None else {"value": v, "fmt": fmt_price(v)})
        return {
            "name": name, "type": "line", "data": data,
            "xAxisIndex": 0, "yAxisIndex": 0, "showSymbol": False,
            "lineStyle": {"color": color, "width": 1.25}, "z": 2, "connectNulls": True,
        }

    volumes = []
    for p in price_series:
        if p["volume"] is None:
            volumes.append(None)
            continue
        up = (p["close"] or 0) >= (p["open"] or 0)
        volumes.append({
            "value": p["volume"], "fmt": fmt_compact(p["volume"]),
            "itemStyle": {"color": "var(--diverge-pos)" if up else "var(--diverge-neg)"},
        })

    # Default view: the most recent ~1 trading year, not all 6 -- matches
    # how real stock apps land (recent context first), with the range
    # buttons/slider available to zoom out. If there's less than a year of
    # history (a recent IPO), just show everything.
    start_pct = max(0.0, (1 - 252 / n) * 100) if n > 252 else 0.0

    option = {
        "animation": False,
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"}, "formatter": "__tooltipFmt__"},
        "legend": {
            "data": ["MA20", "MA50", "MA200"], "top": 0, "right": 8,
            "textStyle": {"color": "var(--text-secondary)", "fontSize": 11.5},
            "itemWidth": 14, "itemHeight": 8,
        },
        "axisPointer": {"link": [{"xAxisIndex": "all"}]},
        "grid": [
            {"left": 8, "right": 16, "top": 30, "height": "56%", "containLabel": True},
            {"left": 8, "right": 16, "top": "72%", "height": "16%", "containLabel": True},
        ],
        "xAxis": [
            {
                "type": "category", "data": dates, "gridIndex": 0, "boundaryGap": True,
                "axisLine": {"lineStyle": {"color": "var(--baseline)"}}, "axisLabel": {"show": False},
                "axisTick": {"show": False}, "splitLine": {"show": False},
            },
            {
                "type": "category", "data": dates, "gridIndex": 1, "boundaryGap": True,
                "axisLine": {"lineStyle": {"color": "var(--baseline)"}},
                "axisLabel": {"color": "var(--text-secondary)", "fontSize": 11},
                "axisTick": {"show": False}, "splitLine": {"show": False},
            },
        ],
        "yAxis": [
            {
                "type": "value", "scale": True, "gridIndex": 0,
                "splitLine": {"lineStyle": {"color": "var(--gridline)"}},
                "axisLabel": {"color": "var(--text-muted)", "fontSize": 11, "formatter": "${value}"},
            },
            {
                "type": "value", "scale": True, "gridIndex": 1, "splitNumber": 2,
                "splitLine": {"show": False},
                "axisLabel": {"color": "var(--text-muted)", "fontSize": 10, "formatter": "__compactAxis__"},
            },
        ],
        "dataZoom": [
            {"type": "inside", "xAxisIndex": [0, 1], "start": start_pct, "end": 100},
            {
                "type": "slider", "xAxisIndex": [0, 1], "start": start_pct, "end": 100,
                "height": 20, "bottom": 4,
                "borderColor": "var(--border)", "fillerColor": "rgba(42,120,214,0.12)",
                "handleStyle": {"color": "var(--series-1)"},
                "textStyle": {"color": "var(--text-secondary)", "fontSize": 10},
                "dataBackground": {
                    "lineStyle": {"color": "var(--text-muted)"},
                    "areaStyle": {"color": "var(--gridline)"},
                },
            },
        ],
        "series": [
            {
                "name": "Price", "type": "line", "data": closes,
                "xAxisIndex": 0, "yAxisIndex": 0, "showSymbol": False,
                "lineStyle": {"color": line_color, "width": 2},
                "areaStyle": {"color": area_gradient},
                "connectNulls": True, "z": 3,
                **({"markPoint": end_marker} if end_marker else {}),
            },
            _ma_series("ma20", "var(--series-1)", "MA20"),
            _ma_series("ma50", "var(--series-2)", "MA50"),
            _ma_series("ma200", "var(--series-3)", "MA200"),
            {
                "name": "Volume", "type": "bar", "data": volumes,
                "xAxisIndex": 1, "yAxisIndex": 1, "barMaxWidth": 6,
            },
        ],
    }
    return register_chart(option, height_px=460, aria_label=aria_label)


def strategy_trade_chart(price_series, trades, aria_label="strategy trades over time"):
    """Line chart of a stock's own price over the tested period, with a
    green triangle at each real buy and a red diamond at each real sell --
    built entirely from price_series and trades already computed once by
    backtest/engine.py (see run_backtests()), no new data fetch or
    re-computation here."""
    if not price_series:
        return None
    dates = [p["date"] for p in price_series]
    price_data = [
        {"value": [p["date"], p["close"]], "fmt": fmt_price(p["close"])}
        for p in price_series
    ]
    buy_data = [
        {"value": [t["entry_date"], t["entry_price"]], "fmt": f"Buy — {fmt_price(t['entry_price'])}"}
        for t in trades
    ]
    sell_data = [
        {"value": [t["exit_date"], t["exit_price"]], "fmt": f"Sell — {fmt_price(t['exit_price'])}"}
        for t in trades
    ]
    option = {
        "grid": {"left": 8, "right": 16, "top": 24, "bottom": 26, "containLabel": True},
        "tooltip": {"trigger": "item", "formatter": "__tooltipFmt__"},
        "legend": {"show": False},  # the HTML legend below is authoritative
        "xAxis": {
            "type": "category", "data": dates, "boundaryGap": False,
            "axisLine": {"lineStyle": {"color": "var(--baseline)"}},
            "axisLabel": {"color": "var(--text-secondary)", "fontSize": 11, "showMaxLabel": True},
        },
        "yAxis": {
            "type": "value", "scale": True,
            "splitLine": {"lineStyle": {"color": "var(--gridline)"}},
            "axisLabel": {"color": "var(--text-muted)", "fontSize": 11, "formatter": "${value}"},
        },
        "series": [
            {
                "type": "line", "name": "Price", "data": price_data,
                "showSymbol": False, "lineStyle": {"color": "var(--text-secondary)", "width": 1.25}, "z": 1,
            },
            {
                "type": "scatter", "name": "Buy", "data": buy_data,
                "symbol": "triangle", "symbolSize": 11, "itemStyle": {"color": "var(--diverge-pos)"}, "z": 2,
            },
            {
                "type": "scatter", "name": "Sell", "data": sell_data,
                "symbol": "diamond", "symbolSize": 10, "itemStyle": {"color": "var(--diverge-neg)"}, "z": 2,
            },
        ],
    }
    return register_chart(option, height_px=260, aria_label=aria_label)


# ============================================================================
# Sections
# ============================================================================

def _humanize_fetched_at(iso_str: str) -> str:
    """Bundle timestamps are always UTC ISO8601 with a trailing "Z" (see
    data/bundle.py) -- shown here as a readable absolute date/time, not a
    relative "3 hours ago": this dashboard is a static file that can be
    reopened long after it was generated, and a relative time computed at
    generation would silently go wrong the moment that happens (there's
    no client-side clock to recompute it against, unlike the live
    /progress page)."""
    if not iso_str:
        return "—"
    try:
        parsed = dt.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except ValueError:
        return iso_str
    return parsed.strftime("%b %-d, %Y · %-I:%M %p UTC")


# logo.dev's token, chosen (over Google's keyless favicon service used
# previously) for real ticker-native, theme-aware brand logos instead of
# a low-res favicon guessed from a domain. Deliberately hardcoded, not
# routed through config.py's env-var pattern like ANTHROPIC_API_KEY/etc:
# an explicit choice the user made after being told this repo is public
# on GitHub and anyone can read (and use) a hardcoded token forever, even
# from old commits. If this ever needs rotating, this is the one place
# to change it.
LOGO_DEV_TOKEN = "pk_fdrRsJx-Rh64maUoQjYCnQ"


def section_header(bundle):
    ticker = bundle.get("ticker", "?")
    fundamentals = bundle.get("fundamentals", {}) or {}
    company_name = fundamentals.get("company_name")
    fetched_at = _humanize_fetched_at(bundle.get("fetched_at", ""))
    initial = esc((ticker or "?")[:1].upper())

    # logo.dev looks up by ticker directly -- no domain-guessing from
    # yfinance's `website` field needed (unlike the Google-favicon version
    # this replaced). A single <img>, not a light/dark pair: logo.dev's
    # own theme variants are picked client-side by JS on load and on
    # every toggle (webui/src/js/theme-toggle.js's applyLogoForTheme()),
    # the same "re-run on toggle" shape hydrate.js's reapplyTheme()
    # already uses for charts -- a pure-CSS <picture media="..."> can't
    # do this correctly, since it only ever tracks OS-level
    # prefers-color-scheme and has no way to see this app's own manual
    # dark-mode toggle (a real, separate, already-supported preference
    # layered on top of OS preference, persisted to localStorage). The
    # two URLs are precomputed here and handed to the client as data
    # attributes -- it only ever picks between them, never builds a URL
    # itself. A ticker logo.dev has nothing for still returns a real
    # (small, clean) image -- its own auto-generated initial-letter
    # placeholder -- so the onerror fallback below only ever fires for a
    # genuine network failure (offline HA instance, logo.dev itself
    # unreachable), the same case Clearbit's and Google's versions
    # handled the same way.
    logo_base = f"https://img.logo.dev/ticker/{esc(ticker)}?token={LOGO_DEV_TOKEN}&format=webp&retina=true&theme="
    logo_html = f"""
      <img class="company-logo" id="company-logo-img" data-light="{logo_base}light" data-dark="{logo_base}dark"
           src="{logo_base}light" alt="{esc(company_name or ticker)} logo"
           width="40" height="40" loading="lazy"
           onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">
      <div class="company-logo-fallback" style="display:none;">{initial}</div>"""

    company_line = f" · {esc(company_name)}" if company_name else ""

    return f"""
<div class="topbar">
  <div class="topbar-identity">
    <a href="/" class="back-link" title="Back to ticker search" aria-label="Back to ticker search">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M19 12H5"/><path d="m12 19-7-7 7-7"/>
      </svg>
    </a>
    <div class="company-logo-wrap">{logo_html}</div>
    <div class="topbar-title-group">
      <h1>{esc(ticker)}</h1>
      <div class="meta">{esc(fetched_at)}{company_line}</div>
    </div>
  </div>
  <div class="topbar-actions">
    <button type="button" class="chip chip-accent" id="llm-export-btn" data-ticker="{esc(ticker)}"
            title="Download a Markdown file with all this data plus instructions, to paste/upload into a free AI chat (Claude, ChatGPT, etc.) for an independent analysis">
      <svg class="chip-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
           stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>
      </svg>
      Download for AI Chat
    </button>
    <button type="button" class="chip" id="theme-toggle">Dark mode</button>
  </div>
</div>"""


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
        fv_svg, fv_table, _fv_legend = range_meter(fv_low, None, None, fv_high, current_price)
        if fv_svg:
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

    # Reuses backtest/engine.py's price_series -- the same OHLCV +
    # MA20/50/200 history already fetched once for the Strategy Backtests
    # section -- rather than fetching price history a second time here.
    price_series = ((bundle.get("backtests", {}) or {}).get("price_series")) or []
    history_chart_html = price_history_chart(price_series, aria_label="interactive price history with volume and moving averages")
    if history_chart_html:
        history_block = f"""
<div class="price-chart-wrap">
  <div class="chart-toolbar">
    <button type="button" class="range-btn" data-days="21">1M</button>
    <button type="button" class="range-btn" data-days="63">3M</button>
    <button type="button" class="range-btn" data-days="126">6M</button>
    <button type="button" class="range-btn is-active" data-days="252">1Y</button>
    <button type="button" class="range-btn" data-days="504">2Y</button>
    <button type="button" class="range-btn" data-days="0">All</button>
  </div>
  {history_chart_html}
</div>"""
    else:
        history_block = ""

    low_52w, high_52w = price.get("52w_low"), price.get("52w_high")
    ma_markers = [
        ("MA200", price.get("ma200"), "var(--series-3)"),
        ("MA50", price.get("ma50"), "var(--series-2)"),
        ("MA20", price.get("ma20"), "var(--series-1)"),
    ]
    svg, table, ma_legend = range_position_plot(
        low_52w, high_52w, price.get("current_price"), ma_markers,
        aria_label="price vs. 52-week range and moving averages",
    )
    price_card = viz_card("Price vs. moving averages", svg, table, ma_legend, info="price_vs_ma")

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
  {history_block}
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

    range_svg, range_table, range_legend = range_meter(
        fundamentals.get("target_low_price"), fundamentals.get("target_mean_price"),
        fundamentals.get("target_median_price"), fundamentals.get("target_high_price"),
        bundle.get("price", {}).get("current_price"),
    )
    range_card = viz_card(
        f"Analyst target price range ({fundamentals.get('number_of_analyst_opinions') or 0} analysts)",
        range_svg, range_table, range_legend, info="analyst_target_range",
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
                f'<div class="rec-trend-chart">{svg or empty_state("No data for this period.")}</div></div>'
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
        surprise_card = viz_card("EPS surprise history", None, empty_state(), info="eps_surprise")

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


def _backtest_result_badge(strat):
    if not strat.get("num_trades"):
        return badge("No trades", "neutral")
    if strat.get("beat_buy_hold") is True:
        return badge("Beat Buy & Hold", "good")
    if strat.get("beat_buy_hold") is False:
        return badge("Underperformed", "critical")
    return badge("—", "neutral")


def _holding_badge(status):
    if not status:
        return badge("Unknown", "neutral")
    return badge("Holding" if status["holding"] else "Not Holding", "info" if status["holding"] else "neutral")


def _backtest_status_box(status):
    """A small styled panel: "what would this rule tell me to do right
    now" -- the current reading and its trigger shown as two stat tiles
    (not one narrative sentence, since the underlying trigger can be a raw
    price, an RSI reading, or a percent -- see strategies.py's "_status
    functions" block, and forcing all three into identical grammar read
    worse than a consistent label/value pair), plus a short plain-English
    caption for when it actually fires."""
    if not status:
        return f"""
<div class="status-box">
  <div class="status-box-head">{_holding_badge(None)}</div>
  <div class="status-box-caption">Not enough data to show a current reading for this rule.</div>
</div>"""

    verb = "Sell" if status["next_action"] == "sell" else "Buy"
    if status["unit"] == "$":
        fmt = fmt_price
    elif status["unit"] == "%":
        fmt = lambda v: fmt_pct(v, signed=False)
    else:
        fmt = lambda v: fmt_num(v, 1)
    move_phrase = "rises above" if status["direction"] == "above" else "drops below"
    caption = f"Fires when this {move_phrase} that level."
    if status.get("extra_note"):
        caption += " " + status["extra_note"]

    return f"""
<div class="status-box">
  <div class="status-box-head">{_holding_badge(status)} What would this rule do right now?</div>
  <div class="backtest-stats-row" style="margin-top:0;">
    {stat_tile(status['current_label'], fmt(status['current_value']))}
    {stat_tile(f"{verb} trigger", fmt(status['trigger_value']), sub=status['trigger_label'])}
  </div>
  <div class="status-box-caption">{esc(caption)}</div>
</div>"""


def section_backtests(bundle):
    backtests = bundle.get("backtests", {}) or {}
    strategies = backtests.get("strategies", []) or []

    if not strategies:
        return f"""
<div class="card full" id="sec-backtests">
  <h2>Strategy Backtests {info_icon('section_backtests')}</h2>
  {empty_state(backtests.get("note") or "Not enough price history to run a backtest for this ticker.")}
</div>"""

    price_series = backtests.get("price_series", []) or []
    years = backtests.get("years_tested")
    period_note = (
        f"Tested over {years} years of this stock's actual price history "
        f"({backtests.get('history_start')} to {backtests.get('history_end')}), assuming a "
        f"0.1% trading cost per trade. Not a prediction of the future -- just what these "
        f"specific, well-known rules would actually have done."
    ) if years else ""

    cards = []
    for s in strategies:
        return_pct, buy_hold_pct = s.get("return_pct"), s.get("buy_hold_return_pct")
        stats_row = f"""
<div class="backtest-stats-row">
  {stat_tile("Return", fmt_pct(return_pct) if return_pct is not None else "—",
              value_cls=delta_class(return_pct) if return_pct is not None else None)}
  {stat_tile("Buy & Hold", fmt_pct(buy_hold_pct) if buy_hold_pct is not None else "—",
              value_cls=delta_class(buy_hold_pct) if buy_hold_pct is not None else None)}
  {stat_tile("Win Rate", fmt_pct(s.get("win_rate_pct"), signed=False) if s.get("win_rate_pct") is not None else "—", info="backtest_win_rate")}
  {stat_tile("Trades", fmt_num(s.get("num_trades")) if s.get("num_trades") is not None else "—")}
</div>"""

        status = s.get("current_status")
        status_html = _backtest_status_box(status)

        trades = s.get("trades", []) or []
        chart_html = (
            strategy_trade_chart(price_series, trades, aria_label=f"{s.get('name')} buy/sell markers")
            if trades and price_series else None
        )
        chart_block = f"""
<details class="chart-disclosure">
  <summary>Show chart (buy/sell markers on price)</summary>
  <div>{chart_html}</div>
</details>""" if chart_html else ""

        cards.append(f"""
<div class="strategy-card">
  <div class="strategy-card-head">
    <span class="strategy-card-title-group">
      <span class="strategy-card-title">{esc(s.get('name') or '—')}</span>
      {badge(s.get('category') or '—', 'neutral')}
    </span>
    {_backtest_result_badge(s)}
  </div>
  <div class="card-sub">{esc(s.get('explanation') or '')}</div>
  {stats_row}
  {status_html}
  {chart_block}
</div>""")

    return f"""
<div class="card full" id="sec-backtests">
  <h2>Strategy Backtests {info_icon('section_backtests')}</h2>
  <div class="card-sub">{esc(period_note)}</div>
  <div class="strategy-card-list">{''.join(cards)}</div>
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

    institutional_panel = f"""
{stack_card}
<div class="viz-card" style="margin-top:16px;"><div class="viz-card-head"><span class="viz-title">Top institutional holders {info_icon('top_holders')}</span></div>{holders_table}</div>
<div class="viz-card" style="margin-top:16px;"><div class="viz-card-head"><span class="viz-title">Schedule 13D/13G (&gt;5% stakes) {info_icon('beneficial_ownership')}</span></div>{ben_table if ben_rows else empty_state()}</div>"""

    insiders_panel = f"""
{mspr_html}
<div class="viz-card"><div class="viz-card-head"><span class="viz-title">Insider transactions (Form 4) {info_icon('insider_transactions')}</span></div>{insider_table if insider_rows else empty_state()}</div>
<div class="viz-card" style="margin-top:16px;"><div class="viz-card-head"><span class="viz-title">Form 144 proposed sales {info_icon('form144')}</span></div>{f144_table if f144_rows else empty_state()}</div>"""

    ownership_bar, ownership_panels = subtabs("ownership", [("Institutional", institutional_panel), ("Insiders", insiders_panel)])
    return f"""
<div class="card full" id="sec-ownership">
  <h2>Ownership {info_icon('section_ownership')}</h2>
  <div class="card-sub">Snapshot of current holders — not a quarter-over-quarter 13F change (see data notes).</div>
  {ownership_bar}
  {ownership_panels}
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
        q_card = viz_card("Quarterly revenue & net income", None, empty_state(), info="quarterly_financials")

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
        bb_card = viz_card("Quarterly buyback spend", None, empty_state("No buyback activity found."), info="buybacks")

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

    dividends_panel = f"{div_tiles}{bb_card}"
    options_panel = opt_html
    macro_panel = macro_tiles
    sentiment_panel = f"""
{sent_card}
<div class="viz-card" style="margin-top:16px;">
  <div class="viz-card-head"><span class="viz-title">Sample posts (unverified)</span></div>
  {sample_html}
</div>"""

    extras_bar, extras_panels = subtabs("extras", [
        ("Dividends & Buybacks", dividends_panel),
        ("Options", options_panel),
        ("Macro", macro_panel),
        ("Sentiment", sentiment_panel),
    ])
    return f"""
<div class="card full" id="sec-extras">
  <h2>Dividends, Buybacks, Options & Sentiment {info_icon('section_extras')}</h2>
  {extras_bar}
  {extras_panels}
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
        body = f'<div class="news-grid">{"".join(items)}</div>'
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
    _reset_chart_registry()  # must run before any section/chart function below
    ticker = esc(bundle.get("ticker", "Ticker"))
    # One section visible at a time instead of one long scroll of ~9 full
    # cards (user request) -- same subtabs() component section_ownership/
    # section_dividends_options_macro_social already use internally, just
    # applied one level up. Price & Technicals is first (so it's still
    # the first thing shown, same as when it had its own pinned spot) and
    # therefore active by default. Data Quality Notes stays outside the
    # tabs, same reasoning as the footer disclaimer below: a brief,
    # page-wide caveat, not a per-topic view.
    main_tabs_bar, main_tabs_panels = subtabs(
        "main",
        [
            ("Price & Technicals", section_price_technicals(bundle)),
            ("Analyst", section_analyst(bundle)),
            ("Backtests", section_backtests(bundle)),
            ("Performance", section_relative_performance(bundle)),
            ("Financials", section_financials(bundle)),
            ("Ownership", section_ownership(bundle)),
            ("Dividends & More", section_dividends_options_macro_social(bundle)),
            ("News", section_news(bundle)),
            ("Filings", section_filings(bundle)),
        ],
        bar_class="page-tabs",
    )
    data_notes_html = section_data_notes(bundle)
    ai_section = section_ai_recommendation(bundle, pipeline_result) if pipeline_result else ""
    charts_json = json.dumps(_drain_chart_registry())
    # Base64, not raw/escaped text: a <script> tag's content is parsed as
    # raw text by the HTML parser regardless of `type`, looking only for a
    # literal "</script" terminator -- base64's alphabet can never contain
    # that (or any other HTML-special character), so this is safe against
    # arbitrary bundle content (filing text, tickers, anything) without
    # needing to HTML-escape it. Decoded back to text client-side in
    # webui/src/js/llm-export.js's "Download for AI Chat" button handler.
    llm_export_b64 = base64.b64encode(build_llm_export_markdown(bundle).encode("utf-8")).decode("ascii")
    built = load_built_assets()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- iOS "Add to Home Screen" support -- see webapp/app.py's PAGE_HEAD for
     the same tags on the index page; both matter since either can be the
     page a user actually bookmarks to their home screen. -->
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="ADELE">
<link rel="apple-touch-icon" href="assets/icon.png">
<title>{ticker} — ADELE Research Dashboard</title>
<script>{THEME_INIT_SCRIPT}</script>
<link rel="stylesheet" href="assets/dist/{built['css']}">
</head>
<body>
<div class="sticky-top">
{section_header(bundle)}
{main_tabs_bar}
</div>
{section_hero(bundle, pipeline_result)}
<div class="wrap">
  {ai_section}
  {section_kpis(bundle)}
  {section_at_a_glance(bundle)}
  {main_tabs_panels}
  {data_notes_html}
</div>
<footer class="disclaimer">
  ADELE is a research/decision-support tool. It is NOT financial advice and never places trades.
  This dashboard renders what is in the underlying JSON research bundle. The "At a Glance" panel
  turns numbers into sentences — every sentence there comes from a fixed, mechanical rule applied
  to a real field below (e.g. "P/E premium over 15% = trading at a premium"), not from any judgment
  call or outside opinion. The "AI Recommendation" panel, when present, is different: it is the
  actual output of ADELE's own 6-agent LLM pipeline (Bull/Bear/two independent Skeptics/Quant
  Checker/Judge) — read it as one
  automated opinion informed by the data below, not as fact. Everything else on this page is
  unmodified data, not re-derived, judged, or fact-checked beyond what the data-fetch layer already notes.
</footer>
<script>window.__CHARTS__ = {charts_json};</script>
<script type="text/plain" id="llm-export-data">{llm_export_b64}</script>
<script src="assets/dist/echarts.min.js"></script>
<script type="module" src="assets/dist/{built['js']}"></script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate an HTML dashboard from an ADELE research bundle JSON file.")
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
    ensure_vendored_assets(os.path.dirname(output_path) or ".")

    print(f"Dashboard written to: {output_path}")


if __name__ == "__main__":
    main()
