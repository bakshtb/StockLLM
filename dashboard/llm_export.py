"""
Builds a single, self-contained Markdown document out of a research bundle,
meant to be downloaded from the dashboard and pasted/uploaded into a free
LLM chat (Claude.ai, ChatGPT, etc.) that has no API access to this tool.

Why this exists: a dry run (all the data below) is free; a full run (the
Bull/Bear/Skeptic/Judge pipeline) costs a little in API calls. This lets
someone get an equivalent bull/bear/fair-value analysis for free, by
outsourcing the reasoning step to a free-tier chat UI instead of our own
paid agents -- using the exact same grounding rules those agents already
follow (see agents/prompts/*.md), condensed into one instructions block a
single general-purpose chat model can follow in one pass.

Deliberately Markdown, not JSON: this file is meant to be read by a chat
UI a human pastes text into, not parsed programmatically -- headers/tables/
bullet lists read naturally to both a human skimming it and an LLM
reasoning over it, and there's no risk of a giant single-line JSON blob
getting mangled by a paste box.

Deliberately excludes StockLLM's own AI Recommendation (Bull/Bear/Judge
output), even when a bundle has one -- the whole point is an independent
second read from a different model, not a summary of what we already
concluded.
"""

import datetime as dt


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, str) and not v.strip():
        return "—"
    return str(v)


def _label(key: str) -> str:
    return key.replace("_", " ").replace("pct", "%").strip().capitalize()


def _kv_list(d: dict, skip=()) -> str:
    """Flat scalar fields of a dict as a bullet list -- callers handle any
    nested dict/list fields separately, explicitly, so nothing silently
    gets dropped."""
    lines = [
        f"- **{_label(k)}**: {_fmt(v)}"
        for k, v in d.items()
        if k not in skip and v is not None and not isinstance(v, (dict, list))
    ]
    return "\n".join(lines) if lines else "_No data available._"


def _table(headers: list, rows: list) -> str:
    if not rows:
        return "_No data available._"
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(_fmt(c) for c in r) + " |")
    return "\n".join(out)


def _list_of_dicts_table(items: list, columns: list) -> str:
    """columns: list of (header, key) pairs."""
    if not items:
        return "_No data available._"
    headers = [h for h, _ in columns]
    rows = [[item.get(k) for _, k in columns] for item in items]
    return _table(headers, rows)


INSTRUCTIONS = """\
## Instructions for the AI reading this file

You are acting as an equity research analyst. Below is real market data for
this stock, gathered from free/public data sources moments ago. Your job is
to read all of it and produce a structured investment analysis.

**Critical grounding rule:** Only use facts present in this document.
Do NOT use prior knowledge about this company's fundamentals, price
history, or news from your own training data -- your training data may be
outdated, and the entire point of this exercise is to reason from the
current, real data below, not from what you already "know" (or think you
know) about this company. If this document doesn't contain enough information to
support a point, say so explicitly rather than making it up.

Please produce, in this order:

1. **Bull case** -- the strongest reasonable case FOR this stock, citing
   specific figures from this document for each point.
2. **Bear case** -- the strongest reasonable case AGAINST it, same rule.
3. **Self-check** -- briefly critique your own two cases above: are any
   points weakly supported, based on thin/old data, or missing context
   that's actually present elsewhere in this document?
4. **Key risks** -- a short list.
5. **Fair-value estimate** -- a low/high dollar range for what this stock
   is actually worth TODAY (not a price prediction for some future date).
   Base it on the analyst price targets, any independent DCF/PEG data,
   the stock's valuation relative to its sector/benchmark, and its growth
   figures below -- weigh conflicting signals explicitly (e.g. "analyst
   targets suggest X, but the DCF estimate suggests Y, because...") rather
   than picking one arbitrarily.
6. **Recommendation** -- Buy / Hold / Sell / Insufficient Data, with a
   confidence score (0-100%) and a short explanation.
7. **Data-quality caveat** -- one sentence on how much to trust this
   analysis given what's actually present vs. missing in this document.

Be honest, not just persuasive -- if the data is thin, old, or conflicting,
say so and lower your confidence accordingly. This is a research/
decision-support exercise, not financial advice, and none of this should be
read as a guarantee or a recommendation to actually trade.
"""


def _section_price(price: dict) -> str:
    parts = [_kv_list(price)]
    return "\n".join(parts)


def _section_fundamentals(fundamentals: dict) -> str:
    return _kv_list(fundamentals)


def _section_analyst(bundle: dict) -> str:
    """Consensus price targets/PE already appear in the Fundamentals
    section above -- this one only covers what's genuinely specific to
    analyst activity, not a second copy of the same fundamentals dict."""
    analyst_ratings = bundle.get("analyst_ratings", {}) or {}
    earnings_est = bundle.get("earnings_estimates", {}) or {}

    parts = []

    actions = analyst_ratings.get("actions", []) or []
    parts.append("### Recent individual rating actions")
    parts.append(_list_of_dicts_table(actions, [
        ("Date", "date"), ("Firm", "firm"), ("Action", "action"),
        ("From", "from_grade"), ("To", "to_grade"),
        ("New price target", "current_price_target"), ("Prior target", "prior_price_target"),
    ]))

    surprises = earnings_est.get("earnings_surprise_history", []) or []
    parts.append("\n### Earnings surprise history (actual vs. estimate)")
    parts.append(_list_of_dicts_table(surprises, [
        ("Quarter end", "quarter_end"), ("Estimated EPS", "eps_estimate"),
        ("Actual EPS", "eps_actual"), ("Surprise %", "surprise_pct"),
    ]))

    trend = earnings_est.get("eps_estimate_trend", {}) or {}
    if trend:
        parts.append("\n### EPS estimate trend (Street consensus, over time)")
        rows = []
        for period_label, key in [("Current quarter", "current_quarter"), ("Next quarter", "next_quarter"),
                                   ("Current year", "current_year"), ("Next year", "next_year")]:
            p = trend.get(key)
            if p:
                rows.append([period_label, p.get("90daysAgo"), p.get("30daysAgo"), p.get("7daysAgo"), p.get("current")])
        parts.append(_table(["Period", "90d ago", "30d ago", "7d ago", "Current"], rows))

    return "\n".join(parts)


def _section_relative_performance(rel: dict) -> str:
    return _kv_list(rel)


def _section_financials(bundle: dict) -> str:
    balance = bundle.get("balance_sheet_health", {}) or {}
    income = bundle.get("income_statement", {}) or {}
    parts = ["### Balance sheet health", _kv_list(balance)]
    parts.append("\n### Income statement (recent quarters)")
    parts.append(_list_of_dicts_table(income.get("quarterly", []) or [], [
        ("Quarter end", "period_end"), ("Revenue", "total_revenue"), ("Net income", "net_income"),
        ("Diluted EPS", "diluted_eps"), ("Revenue YoY %", "revenue_growth_yoy_pct"),
        ("Net income YoY %", "net_income_growth_yoy_pct"),
    ]))
    return "\n".join(parts)


def _section_ownership(bundle: dict) -> str:
    institutional = bundle.get("institutional_ownership", {}) or {}
    insider = bundle.get("insider_transactions", {}) or {}
    form144 = bundle.get("form144_notices", {}) or {}
    beneficial = bundle.get("beneficial_ownership", {}) or {}

    parts = ["### Institutional ownership (snapshot, not a trend)"]
    parts.append(_kv_list(institutional, skip=("top_holders",)))
    parts.append("\n#### Top institutional holders")
    parts.append(_list_of_dicts_table(institutional.get("top_holders", []) or [], [
        ("Holder", "holder"), ("Shares", "shares"), ("% out", "pct_out"), ("Value", "value"),
    ]))

    parts.append("\n### Insider transactions (SEC Form 4)")
    parts.append(_list_of_dicts_table(insider.get("transactions", []) or [], [
        ("Date", "date"), ("Owner", "owner"), ("Title", "title"),
        ("Direction", "direction"), ("Shares", "shares"), ("Price/share", "price_per_share"),
    ]))

    parts.append("\n### Proposed insider sales (Form 144, not yet confirmed)")
    parts.append(_list_of_dicts_table(form144.get("notices", []) or [], [
        ("Approx. sale date", "approx_sale_date"), ("Seller", "seller"), ("Relationship", "relationship"),
        ("Shares proposed", "shares_proposed_to_sell"), ("Market value", "aggregate_market_value_usd"),
    ]))

    parts.append("\n### Beneficial ownership >5% (13D/13G)")
    parts.append(_list_of_dicts_table(beneficial.get("filings", []) or [], [
        ("Reporting person", "reporting_person"), ("% of class", "percent_of_class"),
        ("Form", "form"), ("Filing date", "filing_date"),
    ]))

    return "\n".join(parts)


def _section_extras(bundle: dict) -> str:
    parts = []
    for title, key in [
        ("Dividends & buybacks", "dividends_buybacks"),
        ("Options-market sentiment", "options_sentiment"),
        ("Macro backdrop", "macro_context"),
        ("Social/crowd sentiment (StockTwits)", "social_sentiment"),
    ]:
        parts.append(f"### {title}")
        parts.append(_kv_list(bundle.get(key, {}) or {}))
        parts.append("")
    return "\n".join(parts)


def _section_news(bundle: dict) -> str:
    digest = bundle.get("news_digest")
    headlines = bundle.get("news_headlines", []) or []
    parts = []
    if digest:
        parts.append("### News digest (AI-summarized, from the full run)")
        parts.append(digest)
    else:
        parts.append("### Recent headlines (not summarized -- this was a dry run)")
        parts.append(_list_of_dicts_table(headlines, [
            ("Date", "date"), ("Headline", "headline"), ("Source", "source"),
        ]))
    return "\n".join(parts)


def _section_filings(bundle: dict) -> str:
    digest = bundle.get("filings_digest")
    filings_raw = bundle.get("filings_raw", {}) or {}
    parts = []
    if digest:
        parts.append("### Filings digest (AI-summarized, from the full run)")
        parts.append(digest)
    else:
        parts.append("### Raw filing excerpts (not summarized -- this was a dry run)")
        for filing_type, filing in filings_raw.items():
            text = (filing or {}).get("text")
            if not text:
                continue
            parts.append(f"\n#### {filing_type}")
            parts.append(text)
    return "\n".join(parts)


def _section_valuation_signals(bundle: dict) -> str:
    fmp = bundle.get("fmp_valuation", {}) or {}
    finnhub = bundle.get("finnhub_signals", {}) or {}
    parts = ["### Independent valuation (FMP, optional)", _kv_list(fmp)]
    parts.append("\n### Finnhub signals (optional)")
    parts.append(_kv_list(finnhub, skip=("recommendation_trend",)))
    trend = finnhub.get("recommendation_trend", []) or []
    if trend:
        parts.append("\n#### Analyst recommendation trend over time")
        parts.append(_list_of_dicts_table(trend, [
            ("Period", "period"), ("Strong buy", "strong_buy"), ("Buy", "buy"),
            ("Hold", "hold"), ("Sell", "sell"), ("Strong sell", "strong_sell"),
        ]))
    return "\n".join(parts)


def _section_backtests(bundle: dict) -> str:
    backtests = bundle.get("backtests", {}) or {}
    strategies = backtests.get("strategies", []) or []
    if not strategies:
        return backtests.get("note") or "_No backtest data available for this ticker._"
    parts = [
        f"Tested over {backtests.get('years_tested')} years of real price history "
        f"({backtests.get('history_start')} to {backtests.get('history_end')}), "
        f"assuming a 0.1% trading cost per trade.",
        "",
        _list_of_dicts_table(strategies, [
            ("Strategy", "name"), ("Style", "category"), ("Return %", "return_pct"),
            ("Buy & hold %", "buy_hold_return_pct"), ("Win rate %", "win_rate_pct"),
            ("Trades", "num_trades"), ("Max drawdown %", "max_drawdown_pct"),
        ]),
    ]
    return "\n".join(parts)


def _section_data_notes(bundle: dict) -> str:
    notes = bundle.get("data_notes", []) or []
    if not notes:
        return "_No data-quality issues flagged._"
    return "\n".join(f"- {n}" for n in notes)


def build_llm_export_markdown(bundle: dict) -> str:
    ticker = bundle.get("ticker", "UNKNOWN")
    fetched_at = bundle.get("fetched_at", "")
    generated_at = dt.datetime.utcnow().isoformat() + "Z"

    sections = [
        ("Price & Technicals", _section_price(bundle.get("price", {}) or {})),
        ("Fundamentals", _section_fundamentals(bundle.get("fundamentals", {}) or {})),
        ("Analyst Ratings & Estimates", _section_analyst(bundle)),
        ("Strategy Backtests (real historical rule performance, no AI)", _section_backtests(bundle)),
        ("Relative Performance vs. S&P 500 / Sector", _section_relative_performance(bundle.get("relative_performance", {}) or {})),
        ("Financials", _section_financials(bundle)),
        ("Ownership & Insider Activity", _section_ownership(bundle)),
        ("Dividends, Options, Macro & Social Sentiment", _section_extras(bundle)),
        ("Independent Valuation Signals", _section_valuation_signals(bundle)),
        ("News", _section_news(bundle)),
        ("Filings", _section_filings(bundle)),
        ("Data Quality Notes", _section_data_notes(bundle)),
    ]

    body = "\n\n".join(f"## {title}\n\n{content}" for title, content in sections)

    return f"""\
# {ticker} — Research Data Export

Generated by StockLLM on {generated_at} (underlying data bundle fetched
{fetched_at}). Real market data from free/public sources -- no AI opinion
is included in this file. Paste or upload this whole document into an AI
chat assistant (Claude, ChatGPT, etc.) and ask it to follow the
instructions below.

{INSTRUCTIONS}

---

# Data

{body}

---

*StockLLM is a research/decision-support tool. It never places trades, and
this export is not financial advice.*
"""
