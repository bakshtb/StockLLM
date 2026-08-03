# StockLLM — Handoff

This document captures everything decided and built so far, across a claude.ai
chat (original build) and a Claude Code session (data-layer hardening +
expansion). Read this fully before making changes — it explains *why* things
are built the way they are, not just what's in the code.

**Repo**: https://github.com/bakshtb/StockLLM (branch `main`). To pick up on a
new machine: clone it, `pip install -r requirements.txt`, then run
`python main.py check AAPL --dry-run` first (no API key needed) to confirm the
free data layer works before touching anything else.

## Project goal

A personal research tool: give it a stock ticker, it gathers real data (price/
technicals, fundamentals, short interest, balance sheet, income statement,
insider transactions, Form 144 sale notices, 13D/13G beneficial ownership,
institutional ownership, 10-K/10-Q/8-K filings, DEF 14A proxy, news) and runs
it through a multi-agent LLM pipeline (Bull / Bear / Skeptic / Judge) that
produces a structured buy/sell/hold recommendation with confidence and
reasoning, printed to the terminal.

**Hard constraints — do not violate these without explicit user confirmation:**
- This is a decision-support/research tool, NOT an auto-trading system. It must
  never place trades or connect to a broker.
- No Telegram notifications, no scheduler/watchlist automation, no web UI. Those
  were explicitly deferred (see "Explicitly deferred" below) — the person wanted
  a working CLI validated first before adding any of that.
- Every LLM agent must stay grounded in the provided data bundle only — no
  reasoning from the model's own training-data "knowledge" about the company.
  This is enforced via explicit prompt instructions in `agents/prompts/*.md`.

## Current architecture (as built)

```
StockLLM/
├── data/                          # data fetching layer
│   ├── fetch_prices.py            # price history + RSI/MACD/moving averages (free, yfinance)
│   ├── fetch_fundamentals.py      # P/E, market cap, analyst targets, short interest (free, yfinance)
│   ├── fetch_analyst_ratings.py   # individual analyst-firm actions: upgrade/downgrade/reiterate,
│   │                               #   from/to grade, price target changes, last ~60 days (free, yfinance)
│   ├── fetch_earnings_estimates.py # earnings surprise history (4 qtrs) + EPS/revenue estimate
│   │                               #   trend + revisions, 7/30/60/90-day windows (free, yfinance)
│   ├── fetch_relative_performance.py # stock's 20d/1y return vs. SPY and sector SPDR ETF (free, yfinance)
│   ├── fetch_dividends_buybacks.py # dividend yield/payout/history + quarterly buyback spend (free, yfinance)
│   ├── fetch_options_sentiment.py # put/call volume+OI ratio, ATM/OTM implied vol skew (free, yfinance)
│   ├── fetch_macro_context.py     # VIX level + 10Y Treasury yield, both with 20d change; same for
│   │                               #   every ticker on a given day, not ticker-specific (free, yfinance)
│   ├── fetch_social_sentiment.py  # StockTwits crowd bullish/bearish tag counts + sample messages
│   │                               #   (free, public API, no auth -- retail sentiment, not fact)
│   ├── fetch_balance_sheet.py     # debt, cash, free cash flow (free, yfinance)
│   ├── fetch_income_statement.py  # revenue/margins/EPS: latest annual + ALL recent quarters (free, yfinance)
│   ├── fetch_insider.py           # SEC Form 4 insider transactions (free, SEC EDGAR)
│   ├── fetch_form144.py           # proposed insider sale notices -- leading signal (free, SEC EDGAR)
│   ├── fetch_beneficial_ownership.py  # Schedule 13D/13G >5% stakes, active vs passive (free, SEC EDGAR)
│   ├── fetch_institutional.py     # institutional holder snapshot (free, yfinance)
│   ├── fetch_filings.py           # 10-K + 10-Q + 8-K raw fetch (free) + combined Haiku digest (SMALL LLM COST)
│   ├── fetch_proxy.py             # DEF 14A proxy, Compensation Discussion & Analysis section (free, SEC EDGAR)
│   ├── fetch_news.py              # headlines (free) + full-article raw fetch (free) + Haiku digest (SMALL LLM COST)
│   ├── edgar_utils.py             # shared SEC EDGAR helpers: CIK lookup, rate-limited requests,
│   │                               #   exhibit-document discovery, XML namespace stripping
│   ├── edgar_text.py              # shared HTML-to-text stripping + section-window selection
│   └── bundle.py                  # assembles all of the above into one research bundle
├── agents/
│   ├── prompts/{bull,bear,skeptic,judge}.md   # role instructions, grounding rules
│   ├── client.py                  # Anthropic API wrapper: prompt caching, JSON parsing, retries
│   ├── bull_agent.py / bear_agent.py / skeptic_agent.py / judge_agent.py
│   └── pipeline.py                # orchestrates bull → bear → skeptic → judge, logs to db
├── storage/
│   ├── schema.sql                 # runs, research_bundles, agent_outputs, outcomes tables
│   └── db.py                      # SQLite helpers
├── dashboard/
│   ├── generate_dashboard.py      # bundle JSON -> HTML dashboard; pure rendering layer,
│   │                               #   no network calls, no deps beyond stdlib
│   ├── assets.py                  # copies vendored chart assets next to a generated dashboard
│   └── assets/                    # vendored echarts.min.js + hand-written dashboard.js runtime
├── config.py                      # model choices per agent, pricing table, spend limit
├── main.py                        # CLI entrypoint: `python main.py check TICKER [--dry-run] [--output PATH]`
├── backtest/                      # empty placeholder, not built yet
├── requirements.txt
├── .env.example
├── README.md
└── aapl_dryrun.json, mobileye.json, AAPL.json, qqq.json, spcx.json
    # example dry-run output bundles from this session -- useful as a live
    # reference for the exact current schema shape
```

## Key design decisions and why

1. **Raw data fetching and LLM summarization are two strictly separate stages,
   and this now goes much deeper than just "which modules call the API."**
   `data/bundle.py` always runs a full "Stage 1: raw data" pass — this
   includes not just prices/fundamentals but the *full text* of the latest
   10-K, 10-Q, 8-K (incl. earnings press release exhibit), DEF 14A proxy, and
   as many full news article bodies as are fetchable. None of that needs an
   API key. Only "Stage 2: digests" (`filings_digest`, `news_digest` — Haiku
   summarizing that raw text down) is gated behind `run_digests=True` /
   having `ANTHROPIC_API_KEY` set. `--dry-run` runs Stage 1 in full and skips
   Stage 2 entirely. This means dry-run genuinely gets *all* the data, not a
   thinner version of it — see `data/bundle.py`'s module docstring.

2. **Model assignment per agent role -- picked per-role by benchmark, not one
   provider everywhere** (see the longer reasoning in config.py's comments):
   - Bull, Bear → Gemini 3.1 Pro -- best faithfulness/calibration benchmarks
     for a strictly-grounded persuasive-argument role.
   - News digest → Gemini Flash -- best summarization-faithfulness benchmark,
     cheapest/fastest tier.
   - Filings digest → Qwen3.7-Plus -- reads a MUCH larger window of the raw
     filing than the other agents ever see (`MAX_FILING_CHARS_FOR_DIGEST` =
     60,000 chars, vs. `MAX_FILING_CHARS` = 15,000 for what's actually stored
     in the shared bundle) -- Qwen's cost per token is cheap enough that 4x
     the text still costs less than the old smaller Gemini call did.
   - Skeptic (original) → Claude Sonnet -- best LLM-as-judge/critique benchmark.
   - Skeptic (independent 2nd opinion) + Quant Checker → Qwen3.7-Plus -- cheap
     supporting checks, deliberately a different provider from the original
     Skeptic for genuine cross-model diversity.
   - Judge → Claude Opus -- best confidence-calibration benchmark
     (ConfidenceBench), the call that matters most.
   These model ID strings are in `config.py` (`MODEL_BULL`, `MODEL_BEAR`,
   `MODEL_SKEPTIC`, `MODEL_JUDGE`, `MODEL_NEWS_DIGEST`, `MODEL_FILINGS_DIGEST`,
   `MODEL_SKEPTIC_QWEN`, `MODEL_QUANT_CHECKER`) -- update there if a provider
   renames/replaces a model, not scattered through the codebase. Three API
   keys are required for a full run: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
   `QWEN_API_KEY`.

3. **Prompt caching**: the research bundle is sent as a separate cached content
   block (`cache_control: {"type": "ephemeral"}`) ahead of each agent's
   role-specific instructions, with an identical shared system prompt across all
   four agents — this lets bull/bear/skeptic/judge reuse the cached bundle
   instead of re-paying full price for it 4 times per run. See `agents/client.py`
   `call_agent()`.

4. **Every agent returns strict JSON**, parsed via `_extract_json()` in
   `agents/client.py` which handles markdown-fenced JSON and stray surrounding
   text. One retry on parse/API failure, then the whole run fails loudly (see
   `agents/pipeline.py`) — no silent partial results.

5. **Cost accounting is real, not estimated after the fact.** Every agent call
   AND every digest call gets logged to `storage/agent_outputs` with actual
   input/output tokens and computed cost (`config.estimate_cost_usd()`). A
   monthly spend limit (`MONTHLY_SPEND_LIMIT_USD` in `.env`, default $50) is
   checked before each full run in `main.py`.

6. **`--dry-run` flag** on `python main.py check TICKER` skips ALL LLM calls
   (including the filings/news digest steps, not just the reasoning pipeline) —
   pure free data fetch + a data-quality health check printed to terminal. No
   API key required in this mode. Add `--output PATH` / `-o PATH` to write the
   full JSON bundle to a file instead of dumping it to the terminal (summary
   lines still print either way).

7. **Fetch ALL of 10-K, 10-Q, and 8-K independently — never pick just one.**
   `fetch_filings.py`'s `fetch_filings_raw()` returns
   `{"10-K": {...}, "10-Q": {...}, "8-K": {...}}`. Earlier versions picked
   whichever of the three was chronologically most recent, which meant the
   10-K (annual report — the only place with the *full* Risk Factors section
   and full-year audited financials; a 10-Q just references it) would get
   silently skipped whenever a newer 10-Q or 8-K existed. They cover
   different things and none is a superset of another.

8. **8-K earnings press release exhibit discovery uses SEC's own document
   Type metadata, not filename guessing.** An 8-K's `primaryDocument` is just
   the boilerplate cover page ("see attached exhibit") — the actual earnings
   release with real numbers and management quotes is a separate exhibit
   file in the same accession. Filers name that file however they want (one
   real example: Procter & Gamble's was `moellerpressrelease.htm`, no "ex99"
   anywhere in the name). `edgar_utils.find_exhibit_document()` instead
   parses the filing's own `-index.html` page, where SEC assigns an
   authoritative `Type` (e.g. `EX-99.1`) per document regardless of filename.

9. **MD&A / Compensation-Discussion-and-Analysis section extraction uses a
   "last occurrence wins" heuristic, not a naive `text[:max_chars]` cap.**
   10-Q/10-K/DEF 14A documents open with a cover page, hidden inline-XBRL
   metadata (stripped separately — see `edgar_text.strip_html`), financial
   statement tables (redundant with `income_statement`/`balance_sheet_health`
   anyway), and only later reach the actual prose unique to the document.
   `edgar_text.select_prose_window()` searches for the section heading
   (prefixed with its item number — "Item 7" for a 10-K's MD&A, "Item 2" for
   a 10-Q's — to filter out most incidental cross-references) and jumps to
   its **last** occurrence in the document. This is a verified structural
   invariant, not a guess: a document only ever cites its own later section
   by name *before* that section (table of contents, forward-looking-
   statements boilerplate), never after. Confirmed correct against AAPL's and
   MBLY's actual 10-K/10-Q text, including cases where the naive "2nd
   occurrence" heuristic picked the wrong spot.

10. **`income_statement.quarterly` returns ALL available recent quarters
    (~5), not just the latest one.** A single latest-quarter + latest-annual
    snapshot can invisibly skip an intermediate quarter with a major one-off
    event. Concretely found live: Mobileye's $3.79B goodwill impairment
    landed in the one quarter between the latest annual figure (FY2025) and
    the latest quarterly figure (Q2 2026) — completely invisible until the
    module was changed to return every quarter yfinance has.

11. **Short interest needed no new data source** — yfinance's `info` dict
    already surfaces `sharesShort`, `sharesShortPriorMonth`, `shortRatio`,
    `shortPercentOfFloat`, `dateShortInterest`. Just added to
    `fetch_fundamentals.py`'s output as a `short_interest` sub-dict; no FINRA
    scraping needed.

12. **13D/13G beneficial ownership can materially disagree with yfinance's
    "top holders" list, and that's a real signal, not noise to reconcile.**
    Concretely found live: Intel's actual Schedule 13G stake in Mobileye is
    **79.8%** (includes non-traded Class B super-voting shares), vs. the
    19.81% / 50M shares yfinance's float-based top-holders snapshot shows.
    `fetch_beneficial_ownership.py` also distinguishes 13D (active holder,
    stated "Purpose of Transaction") from 13G (passive) and flags amendments.

13. **SEC XML parsing gotchas worth knowing before touching any `fetch_*`
    module that parses EDGAR XML** (`fetch_insider.py`, `fetch_form144.py`,
    `fetch_beneficial_ownership.py`):
    - `primaryDocument` for ownership forms (4, 144) sometimes points into an
      XSL *viewer* subfolder (e.g. `xslF345X06/form4.xml`) that EDGAR serves
      as pre-rendered HTML, not the raw XML the parser expects. Strip that
      folder prefix to get the real machine-readable XML sitting at the
      accession root under the same filename.
    - Form 4's `isOfficer`/`isDirector` flags are `"1"`/`"0"` in some filings
      and `"true"`/`"false"` in others depending on schema version/filer —
      check both.
    - Unlike Form 4, the newer 13D/13G XML schema declares a default XML
      namespace, so plain `ElementTree.find("tagName")` silently returns
      nothing. `edgar_utils.strip_xml_namespaces()` handles this.

14. **`analyst_ratings` (individual firm actions) is a different, more
    granular signal than `fundamentals.analyst_recommendation`, and both are
    kept.** The latter is yfinance's single aggregated consensus + mean
    target (a static snapshot); `fetch_analyst_ratings.py` instead returns
    yfinance's `Ticker.upgrades_downgrades` feed as-is: one row per named
    firm's action (upgrade/downgrade/reiterate/initiate/maintain) with its
    from/to grade and price-target change, filtered to the last 60 days
    (`LOOKBACK_DAYS`). This lets the agents notice recent sentiment shifts
    (e.g. "3 upgrades in the last 2 weeks") that a single consensus number
    can't show. **Explicitly scoped as agent context only, not backtesting**
    — the person asked for this specifically so the bull/bear/skeptic/judge
    pipeline has more perspective to reason from, not to check past calls
    against outcomes (backtesting itself is still deferred, see below).

15. **Four more free data angles added the same session, same "more agent
    context, not backtesting" intent as #14:**
    - `fetch_earnings_estimates.py`: earnings surprise history (actual vs.
      estimate EPS, last 4 quarters) plus EPS/revenue estimate trend and
      revision counts over 7/30/60/90-day windows. Deliberately distinct
      from `analyst_ratings` — estimates can drift for weeks before any
      firm changes its official rating action.
    - `fetch_relative_performance.py`: the stock's existing 20d/1y return
      (from `fetch_prices.py`) minus SPY's and its sector SPDR ETF's return
      over the same windows. Fixes a real blind spot — `pct_change_1y` in
      isolation can't tell the agents whether a move was exceptional or
      just the whole market/sector moving together. Sector→ETF mapping
      (`SECTOR_ETF_MAP`) is the 11 standard SPDR sector ETFs, matched
      against yfinance's own `sector` string — confirmed live against 10
      tickers spanning all 11 sectors.
    - `fetch_dividends_buybacks.py`: dividend yield/payout/history plus
      quarterly buyback spend (from `Repurchase Of Capital Stock` in
      `quarterly_cashflow`). Note the yfinance unit inconsistency handled
      here: `dividendYield`/`fiveYearAvgDividendYield` come back already as
      plain percent numbers (0.32 means 0.32%), while `payoutRatio` comes
      back as a fraction needing `*100` — verified against AAPL's actual
      ~0.3% yield. Don't "fix" the dividend yield fields by multiplying
      them again.
    - `fetch_options_sentiment.py`: put/call volume & open-interest ratios,
      plus ATM/OTM implied volatility and the resulting skew, from the
      nearest options expiration ≥25 days out. **The put/call ratios are
      real and vary meaningfully by ticker; the IV fields are not
      trustworthy** — live-tested against AAPL/MSFT/TSLA and all three
      returned near-zero ATM IV plus an identical flat OTM value (0.0625)
      regardless of the ticker's actual volatility profile, which is a
      known yfinance data-quality issue (Yahoo's IV field is frequently
      stale/uncalculated), not a bug in this module. The module's own
      output note says this explicitly — don't remove that caveat, and
      weight `iv_skew_put_minus_call` accordingly in any future prompt work.

16. **Fixed a real bug in `fetch_institutional.py`** (found while looking
    for more data to add, not reported by the user): `pct_held_by_institutions`
    /`pct_held_by_insiders` had been `null` in every bundle generated so far
    (see the original AAPL.json/mobileye.json in git history). The old code
    tried to match row *labels* off `tk.major_holders` via
    `" ".join(str(v) for v in row.values)` — but that DataFrame keys the
    data by **index** (`insidersPercentHeld`, `institutionsPercentHeld`),
    not by a labeled column, so `row.values` only ever contained the numeric
    value, never a string with "institutions"/"insiders" in it — the match
    always failed silently. Fixed by reading `info.get("heldPercentInstitutions")`
    /`heldPercentInsiders")` directly instead (same free `info` dict every
    other module already uses); confirmed live (AAPL: 65.7%/1.6%, MBLY:
    59.0%/31.9%).

17. **Added analyst target price range/dispersion** to `fetch_fundamentals.py`:
    `target_median_price`, `target_high_price`, `target_low_price`,
    `number_of_analyst_opinions` — all were sitting unused in the same
    `info` dict already being read; only `target_mean_price` was surfaced
    before. Shows whether analysts are in tight agreement or split (AAPL:
    $215–$400 across 43 analysts).

18. **`fetch_macro_context.py`** is the one module that is NOT ticker-specific
    — it fetches `^VIX` and `^TNX` (10Y Treasury yield) once per run,
    identical for every ticker checked the same day, so the agents have some
    sense of the broader risk environment (rising rates pressure high-multiple
    growth names; elevated/rising VIX signals a risk-off backdrop) instead of
    reasoning about a ticker in a vacuum. Gotcha avoided: ^TNX has historically
    been quoted by some sources scaled by 10 (46.22 meaning 4.622%) — verified
    live that the yfinance feed returns the plain percent directly (4.62, not
    46.2), so there's deliberately no rescaling in this module.

19. **Two sources checked and rejected this session** (asked about
    explicitly, worth remembering so they're not re-proposed): ESG/
    sustainability scores (`yfinance`'s `tk.sustainability` returns a 404 —
    that endpoint is gone/deprecated in the current version) and
    congressional trading disclosures (Senate/House Stock Watcher's open S3
    datasets both returned 403 — dead/inaccessible, and even when up
    they're unofficial scrapers of periodic filings, not a stable API).

20. **`fetch_relative_performance.py` extended to compare valuation, not just
    returns**: stock's trailing P/E vs. SPY's and the sector ETF's trailing
    P/E (`pe_premium_vs_benchmark_pct`/`pe_premium_vs_sector_pct`). A stock
    can outperform its sector on returns while trading at a valuation
    discount to it, or vice versa — deliberately kept as a separate
    question from `relative_vs_*_pct`. `stock_pe_ratio` is passed in from
    `fundamentals.pe_ratio` rather than re-fetched, same pattern as the
    pct-change values already passed in. Returns `None` cleanly (not a
    crash) for non-earning/loss-making tickers with no P/E, e.g. MBLY.

21. **`fetch_social_sentiment.py`**: pulls the last ~30 public StockTwits
    posts for the ticker and counts self-tagged Bullish/Bearish sentiment
    (free, no auth, documented public limit 200 req/hour/IP — irrelevant
    for a manually-run CLI). This is the first genuinely non-professional
    data source in the bundle — retail/crowd chatter, not analyst/
    institutional data. Deliberately scoped as a sentiment gauge only:
    message bodies are unmoderated public chatter, included for color/
    citation, not as facts the agents should reason from. Request timeout is
    15s (bumped up from an initial 10s after a live transient timeout
    failure) matching `edgar_utils.py`'s convention.

22. **Defense-in-depth for the StockTwits caveat above, added right after
    confirming `agents/pipeline.py` sends the ENTIRE bundle verbatim to
    every agent** (`bundle_json_str = json.dumps(bundle)` — no filtering,
    so a raw post like `"$AAPL dropping to $25 thanks to trump"` reaches the
    model exactly as written, same visual weight as an SEC filing fact):
    - Renamed the field from `sample_messages` to
      `sample_messages_unverified` in `fetch_social_sentiment.py` — a
      self-documenting key that's visible every time regardless of whether
      the model "remembers" a prompt instruction from earlier in a long
      context, unlike a rule that only lives in the system prompt.
    - Added one line to `SHARED_SYSTEM_PROMPT` in `agents/client.py` (used
      by all four agents) explicitly naming
      `social_sentiment.sample_messages_unverified` as unmoderated public
      chatter, not to be cited as evidence — only
      `bullish_count`/`bearish_count`/`bullish_pct_of_tagged` are usable
      signal. If a future digest/fetch module adds more raw
      user-generated text, apply the same two-part pattern (self-documenting
      key name + explicit system-prompt callout) rather than relying on
      prompt wording alone.

23. **`dashboard/generate_dashboard.py`**: a viewer, not a new data source —
    takes any bundle JSON (existing file or a fresh `--dry-run` fetch) and
    renders it as an offline HTML dashboard (no CDN, no build step, no
    server — see item 34 below for why it's no longer a *single* file as of
    the ECharts migration). Built following the project's dataviz skill (color-by-job,
    validated reference palette used verbatim, table-view twin on every
    chart, hover+keyboard-focus tooltips). Two judgment calls worth knowing
    if you touch this file:
    - **RSI and the 13D badge are deliberately NOT colored good/bad.** An
      earlier draft colored RSI zones green (oversold)/red (overbought) and
      the 13D ownership badge orange/"warning" — both walked back to neutral
      grays/blue, because RSI extremes and active-investor filings aren't
      unambiguously good or bad (unlike an analyst upgrade/downgrade, or an
      insider buying with their own money, which ARE unambiguous and do get
      status-colored). Don't re-introduce directional coloring for genuinely
      ambiguous signals — it oversteps this tool's own "research tool, not
      financial advice, stay grounded" stance from the agent prompts.
    - **Handles bundles from before this session's data additions.**
      `AAPL.json`/`aapl_dryrun.json`/`google.json`/`qqq.json`/`spcx.json`
      predate `analyst_ratings`/`earnings_estimates`/`macro_context`/etc. —
      every section uses `bundle.get(key, {}) or {}` and renders an empty
      state rather than crashing when a key is missing. Verified live
      against all six existing bundle files in the repo, old and new.
    - No headless browser was available in this environment to screenshot
      the output — verified instead via BeautifulSoup structural parsing
      (svg/table counts, no leaked `None`/`nan` values) and manual read of
      the generated markup. Actually open the HTML in a real browser before
      trusting the visual layout completely.

24. **Full line-by-line audit of AAPL.json and mobileye.json** (every field,
    cross-checked arithmetic, read every raw text block start to end) found
    and fixed three real, pre-existing bugs — none introduced this session,
    all just never noticed until someone actually read the full output:
    - **`fetch_news.py`**: some sites (GuruFocus, Simply Wall St., MT
      Newswires, Yahoo Finance Video) render a generic client-side error
      banner ("Oops, something went wrong") into the page's initial HTML
      alongside whatever real content did load. The old 100-char threshold
      accepted this blindly — three MT Newswires articles were marked
      `full_text_fetched: true` at ~100-130 chars, cut off mid-word
      ("...took note of the Federal Reserve's decisi"), literally no more
      complete than the snippet already had. Fixed: strip the known
      boilerplate prefix, and raise the minimum length to 300 chars (all
      genuinely-fetched articles observed live were 700+ chars; all broken
      ones were under 200). Verified live against AAPL: articles that had
      real substantial content past the error banner (Qualcomm/GuruFocus,
      Simply Wall St., Yahoo Finance Video) now keep it with the banner
      stripped; the three genuinely-truncated MT Newswires ones now
      correctly report `full_text_fetched: false` and fall back to the
      original headline snippet.
    - **`fetch_income_statement.py`**: yfinance's `quarterly_income_stmt`
      sometimes returns one extra oldest column that's entirely empty
      (observed live: MBLY's 6th quarter column had every field `None`) —
      this was passed through as a visible-but-useless quarter entry
      instead of being dropped. Fixed by filtering out any quarter where
      every numeric field is `None` before returning the list.
    - **`fetch_proxy.py`**: the CD&A section-heading regex
      (`CDA_HEADING`) was overfit to AAPL's specific phrasing — it required
      the literal abbreviation `"(CD&A)"` to appear within 10 characters of
      the heading. MBLY's proxy never defines that abbreviation at all, so
      the heading was never found, `select_prose_window` silently fell back
      to a flat cap from the cover page, and the proxy text never reached
      the actual Compensation Discussion and Analysis section — despite it
      genuinely existing ~54% through the document (found by fetching and
      grepping the raw MBLY proxy directly). Worse: unlike 10-K/10-Q Item
      headings, proxies routinely cite the CD&A section BY NAME again later
      (pay-vs-performance tables, say-on-pay proposals) — verified this
      live in BOTH AAPL's and MBLY's proxies — so `select_prose_window`'s
      "last occurrence wins" heuristic (correct and validated for 10-K/10-Q,
      see #9) is NOT safe to rely on alone for the DEF 14A CD&A heading.
      Fixed with a regex requiring self-referential language immediately
      after the heading (`"(CD&A)"` OR `"...explains/describes"` within 100
      chars, no period in between) — a mere backward citation
      ("as discussed in the Compensation Discussion and Analysis section
      of...") doesn't use that phrasing, so it's excluded, and the LAST
      occurrence of this narrower pattern (existing `select_prose_window`
      behavior, unchanged) lands on the real heading in both filers tested.
      If a third filer's proxy still falls back to the cover page (check:
      `"skipped ahead" not in proxy_raw.text`), the CD&A section in that
      filing likely uses yet another phrasing — extend the alternation
      rather than replace it, so previously-working filers don't regress.
    - Also confirmed (not bugs, just worth remembering): the Manulife
      Financial Corporation 13G entries in MBLY's `beneficial_ownership`
      showing `shares_owned: 0.0` three times are genuine — the XML field
      was present and explicitly zero, not a missing-field default; Intel's
      79.8%/13G stake and the goodwill-impairment quarter (net_margin_pct
      -684%) both still match the values documented in #12/#10 above.

25. **Dashboard accessibility pass** (`dashboard/generate_dashboard.py`),
    driven by explicit feedback that a non-finance reader looked at the
    original P/E-premium card and had no way to know why it showed dashes.
    Three additions:
    - **`GLOSSARY` + `info_icon(key)`**: a plain-language, jargon-free
      explanation (2-3 sentences) for every metric/section, shown via a
      small clickable "i" next to the label. Wired through `stat_tile()`
      and `viz_card()`'s new `info=` parameter. If you add a new metric to
      the dashboard, add its glossary entry in the same commit — an
      unexplained number is exactly the gap this pass was meant to close.
    - **Green/red color reused everywhere a value has a clear "good news/
      bad news" reading for a lay reader** — per explicit request
      ("green and red is good"), overriding the earlier, more conservative
      stance in #23. Concretely: `--diverge-pos`/`--diverge-neg` (used by
      the earnings-surprise and sentiment diverging charts) were changed
      from the dataviz skill's default blue/red to reuse the exact
      `--status-good`/`--status-critical` hexes; RSI's gauge zones and the
      1-year-return/net-income/free-cash-flow/current-ratio stat tile
      *values* (not just their deltas, via `stat_tile()`'s new `value_cls=`
      param) now color directly. **Still deliberately NOT colored**: P/E
      premium/discount (can mean "expensive" or "growing faster," not
      inherently bad), insider *selling* (routine/tax-related far more
      often than not), and 13D vs. 13G identity — these get a neutral color
      and an info-icon explanation instead of a forced good/bad read that
      the data doesn't actually support. If a future request pushes to
      color these too, at least keep the honest caveat in the tooltip.
    - **`section_at_a_glance()`**: a new top-of-page panel that turns the
      numbers into 5-8 plain sentences (e.g. "AAPL is up 62.4% over the
      past year. That's beating the S&P 500 by 46.2%"). This is the one
      place this dashboard synthesizes rather than just formats — kept
      honest by generating every sentence from a **fixed, documented
      threshold** on a real field already in the bundle (e.g. "P/E premium
      > 15% → 'trading at a premium'"), never an LLM call or inferred
      claim, and the footer disclaimer says so explicitly. If you add a
      glance rule, keep it mechanical and threshold-based for the same
      reason — this is not the place to start editorializing.
    - Also fixed two small pre-existing formatting bugs found while testing
      this pass: the "Dividend yield" tile for non-payers literally rendered
      the string `"None"` instead of "No dividend"; `fmt_usd()` on a
      negative number rendered `$-392.00M` instead of `-$392.00M` (sign
      landed after the currency symbol). Both caught by an automated
      `>None<` / leaked-value grep across the generated HTML, not by eye —
      re-run that grep after any formatting-helper change.

26. **Fixed a real bug the user spotted by eye**: the "Return vs. benchmark &
    sector" chart's bars were ALL rendered in `var(--series-1)` (blue),
    regardless of whether the bar was Stock/S&P 500/Sector — `bar_chart_horizontal`
    hardcodes a single color, so it was never capable of the per-series
    coloring the chart's own legend implied. Testing also turned up a second,
    related bug in the same chart: `bar_chart_horizontal` draws
    `w = abs(v)/max_v` and always grows the bar rightward, so a negative
    return (MBLY's numbers are mostly negative) rendered as a rightward bar
    indistinguishable in shape from a positive one — only the text label
    said otherwise. Fixed by adding `grouped_bar_horizontal()`: bars grow
    from a shared center baseline in the correct left/right direction for
    the value's sign (like `diverging_bar_horizontal`), but colored by
    series identity (categorical, like `bar_chart_horizontal`) rather than
    by sign — this chart's job is "which is bigger," not "is it good," so
    identity color is correct here even though the values can be negative.
    `section_relative_performance` now builds `groups = [("20-day return",
    [(name, color, value), ...]), ("1-year return", [...])]` instead of
    flattening everything into single-series `bar_chart_horizontal` items.
    `bar_chart_horizontal` itself is unchanged and still correct for its
    remaining two callers (price-vs-moving-averages, quarterly buyback
    spend) — both are genuinely single-series, all-comparable-sign
    magnitude comparisons, which is exactly what it's for.

27. **Fixed a second real bug, again spotted by the user from a screenshot**:
    on the just-fixed relative-performance chart, MBLY's "Stock — 1-year
    return: -42.6%" label rendered directly on top of that row's own
    "Stock" name label. Root cause: both `diverging_bar_horizontal` and
    `grouped_bar_horizontal` place a bar's value label just *outside* its
    tip, at a fixed 6px offset — safe normally, but when a bar's magnitude
    is close to the chart's max (here, -42.58 WAS the max across both
    groups, so its bar filled nearly the entire available half-width), the
    "just outside the tip" position lands almost exactly where the
    row-label column sits, and the two overlap. Neither function had any
    check for this because the layout math only reserves space on the
    *far* side from the row-label column (`tail_w` in `bar_chart_horizontal`)
    — the near side (where negative/center-based bars grow) had no
    equivalent reservation. Fixed with `_diverging_value_label()`: bars
    below `MIN_BAR_WIDTH_FOR_INSIDE_LABEL` (46px) keep the old outside
    placement (harmless — short bars never reach near the row-label
    column regardless); bars at or above that width place the label
    *inside* the bar instead (white text, semibold, anchored so it sits
    within the painted fill), which by construction can never collide with
    the row-label column since the bar itself stops well short of it in
    every case except this one, which is now handled correctly. Shared by
    both diverging-style chart functions since they have the identical
    center-baseline layout; if a third chart function grows this same
    center/diverging pattern, reuse `_diverging_value_label()` rather than
    re-copying the plain "outside" placement.

28. **Added a second real entrypoint: `webapp/app.py` (Flask), packaged as a
    private Home Assistant add-on.** User wants to run StockLLM from inside
    HA — pick a ticker in a web page, toggle dry-run, see the dashboard —
    without giving up the CLI. Key decisions, in case any of this needs
    revisiting:
    - **Add-on files live at the repo ROOT** (`repository.yaml`,
      `config.yaml`, `Dockerfile`, `run.sh`), not in a subfolder, even
      though the multi-add-on convention puts them in one. Reason: Docker's
      build context for an add-on is whatever folder its `Dockerfile`
      lives in — if that were a subfolder, the `Dockerfile` couldn't `COPY`
      `data/`/`agents/`/`dashboard/`/`webapp/` living one level up without
      duplicating them. Root-level keeps the build context = the whole
      repo. This is the standard "single add-on repository" layout, valid
      specifically because this repo will only ever contain one add-on.
    - **Genuinely private repo + PAT-in-URL** (user's explicit choice over
      "public but unlisted"): HA Supervisor clones add-on repos with a
      plain unauthenticated `git clone`, so a real private repo needs
      `https://<fine-grained-PAT>@github.com/bakshtb/StockLLM` pasted into
      HA's Repositories dialog — spelled out step-by-step in `DOCS.md`.
      Token should be fine-grained, Contents: Read-only, scoped to just
      this repo.
    - **Local build, not a pre-built registry image**: no `image:` key in
      `config.yaml`, so Supervisor builds the `Dockerfile` directly on the
      user's HA host on install/update. Slower than pulling a pre-built
      image but needs no CI/registry — matches "private" and keeps the
      whole thing self-contained in the repo.
    - **Ingress (`ingress: true` + `ingress_port: 8099`), not an exposed
      host port** — the add-on's page appears directly in the HA sidebar,
      already behind HA's own login, no separate auth/port to manage.
    - **`webapp/app.py` reuses `data.bundle.build_research_bundle` and
      `agents.pipeline.run_pipeline` directly — no pipeline logic is
      duplicated.** It's a second entrypoint into the exact same functions
      `main.py`'s `check` command already calls, just triggered by a POST
      instead of argv.
    - **HA's per-add-on config (the Configuration tab) reaches the
      container as `/data/options.json`, not a `.env` file** (`.env`
      doesn't exist inside the container). `webapp/app.py`'s
      `_load_ha_options()` reads that file (if present) and populates
      `os.environ` **before** anything imports `config.py` — Python only
      executes a module's top-level code once, so this ordering is load-
      bearing; if you ever refactor imports at the top of `webapp/app.py`,
      keep `_load_ha_options()` as the very first thing that runs.
    - **`OUTPUT_DIR` (new in `config.py`, alongside the now-also-env-
      overridable `DB_PATH`) is what makes the `output/` restructure and
      the add-on's persistent storage the same mechanism**: CLI defaults to
      a plain `output/` folder next to the repo; `run.sh` overrides it to
      `/data/output` (HA's persistent per-add-on volume, survives restarts/
      updates) so add-on-generated files never touch the git checkout
      Supervisor used to build the image.
    - **New dashboard section, `section_ai_recommendation()`**: until this
      change, the dashboard only ever rendered the raw data bundle — there
      was no way to see the actual judge/bull/bear/skeptic output anywhere.
      Necessary once the add-on lets someone choose a full (non-dry-run)
      check, since otherwise spending money on a full run would render the
      identical page as a free dry run. `build_dashboard(bundle,
      pipeline_result=None)` — omit the second argument (as `--dry-run`
      does) and it doesn't render. **This is also, incidentally, the first
      time this whole project's live 4-agent pipeline will actually run
      against the real Anthropic API** (see "What has been tested" above —
      no API key has been used in any session before this one) — watch the
      first real full run closely for JSON schema drift from what
      `agents/prompts/*.md` specify.
    - **Ticker input is validated against `^[A-Z0-9.\-]{1,10}$` before
      anything else in `webapp/app.py`'s `/run` handler** — this isn't just
      input validation, it's the security boundary: the ticker becomes
      part of an output filename (`f"{ticker}.json"`), so rejecting
      anything with a path separator or `..` up front avoids ever needing
      to reason about path traversal in the filename construction. Don't
      relax this regex without re-checking that reasoning.
    - **`app.run(..., debug=False)` is deliberate**, not an oversight —
      Flask's debug mode ships an interactive in-browser debugger that can
      execute arbitrary code, not appropriate even behind HA's ingress
      proxy.
    - **Bump `version:` in `config.yaml` on every future change that
      should ship** — that's the only thing that makes HA's "Auto update"
      toggle actually notice something changed. A code change without a
      version bump sits invisible to installed add-on instances until
      someone happens to reinstall it. **This was originally just a
      written reminder here, and it got forgotten twice in a row within
      the same session** (the Ingress fix and the mobile-responsive fix
      both shipped without a version bump, silently) — see item 31 below
      for the actual enforcement that replaced relying on memory for this.
    - Verification note: no Docker and no real HA instance were available
      in the environment this was built in. Verified as much as possible
      without them — `docker build` itself was NOT run; the Dockerfile/
      run.sh were reviewed by hand and `run.sh`'s shell syntax was checked
      with `bash -n`, but an actual local `docker build` + `docker run` (or
      a real HA install) is still worth doing before fully trusting this
      packaging works end-to-end.

29. **Fixed a real bug found on the first actual HA install** (exactly the
    kind of thing #28 above flagged as unverified): submitting the form
    produced a blank page with nothing in the add-on's log — no `POST /run`
    at all, meaning the request never reached the Flask app. Root cause:
    HA's Ingress proxy mounts an add-on's UI at a dynamic sub-path (e.g.
    `/api/hassio_ingress/<token>`), not the domain root, but
    `webapp/app.py` hardcoded root-relative paths (`action="/run"`,
    `redirect("/output/...")`, the recent-runs `href`s) — a browser resolves
    those against the *domain root*, so the POST went straight past the
    add-on to HA core itself instead. Fixed with `_ingress_prefix()`,
    reading the `X-Ingress-Path` header HA sets on every proxied request
    (empty string when not behind ingress — e.g. `python -m webapp.app`
    directly, or bare `docker run` without HA — so local/docker testing is
    unaffected) and prefixing all three generated URLs with it. Verified
    both branches with Flask's test client (with and without the header
    set) before pushing this time, rather than relying on the Docker/HA
    testing gap #28 already flagged. **If any future route/link/redirect
    is added to `webapp/app.py`, it needs the same `_ingress_prefix()`
    treatment** — this isn't a one-off fix, it's a standing constraint on
    every URL this app generates for itself.

30. **Fixed a real mobile-responsive-design bug, reported with a phone
    screenshot**: the whole dashboard page rendered wider than the
    viewport on a phone (iPhone Safari), clipping content on the right
    with no way to see it short of scrolling horizontally. Root cause: the
    page-level `.grid` (arranges section cards) used
    `grid-template-columns: repeat(auto-fit, minmax(460px, 1fr))` — a
    460px floor per column that's simply wider than most phone viewports
    (commonly 375-430 CSS px), so the grid had no choice but to overflow.
    Several sections also used **inline** `style="grid-template-columns:
    repeat(N,1fr)"` (fixed N-column KPI rows, two-column sub-panel splits)
    which don't respond to viewport width at all.
    - Converted every inline grid override to a named class
      (`.kpi-row.cols-2/3/4`, `.split-2col`) specifically so a mobile media
      query could target them — inline styles can't be overridden by a
      later CSS rule without `!important` fighting inline specificity, so
      this wasn't optional cleanup, it was required to make the fix work
      at all.
    - Added `@media (max-width: 700px)` collapsing `.grid` to one column,
      all fixed-column `.kpi-row` variants to 2 columns, and `.split-2col`/
      `.rec-thesis-grid` to one column, plus a tighter
      `@media (max-width: 420px)` collapsing KPI rows further to one
      column for small phones. Also fixed a secondary issue found while
      auditing this: `.info-pop` (the info-icon popover) had a fixed
      `width: 240px` that could overflow a narrow viewport if the icon it's
      attached to sits near the right edge — added
      `max-width: min(240px, calc(100vw - 32px))` as a safety net (this
      doesn't reposition the popover if it's near the right edge, just
      caps its width so it can't blow past the viewport; a fully correct
      fix would need JS-based edge-aware positioning, not attempted here
      since the known info-icon placements are all near the left of their
      row).
    - `webapp/app.py` needed no separate fix — it imports `CSS_STYLE`
      directly from `dashboard/generate_dashboard.py`, so it inherited all
      of this automatically. If `webapp/app.py` ever adds its OWN
      fixed-column grid layout outside of what `CSS_STYLE` provides, it
      will need the same treatment.
    - Verified with the BeautifulSoup structural checks across all 6
      bundle files (svg counts, no leaked values) plus confirming the
      media query text is actually present in the generated output — still
      no real browser/device available to visually confirm the fix beyond
      that, so it's worth another look on an actual phone.

31. **Replaced "remember to bump the version" with an actual enforced
    check** — a written reminder (item 28/30 above) got forgotten twice in
    a row in the same session, so it clearly wasn't sufficient. Two layers,
    same underlying logic (diff the changed files against the previous
    commit; if anything outside `README.md`/`HANDOFF.md`/`CHANGELOG.md`/
    `DOCS.md`/`output/`/`.github/`/`.githooks/` changed, `config.yaml`'s
    `version:` field must have changed too):
    - **`.github/workflows/version-check.yml`** — the authoritative one.
      Runs on every push/PR to `main` regardless of local setup; fails the
      GitHub check (visible on the commit/PR) if code shipped without a
      version bump.
    - **`.githooks/pre-commit`** — the immediate-feedback one. Blocks the
      commit locally *before* it's even made, with a clear message telling
      you what to do. Requires a one-time
      `git config core.hooksPath .githooks` per checkout (git doesn't
      auto-install hooks from a plain clone — already run in this
      environment's checkout, but a fresh clone elsewhere needs it again).
      `--no-verify` bypasses it deliberately, for the rare case a change
      genuinely shouldn't need a version bump.
    - Both tested live before trusting them: confirmed the hook blocks a
      commit that touches `main.py` without touching `config.yaml`, and
      confirmed it allows a commit touching only excluded paths (this very
      commit, which only added `.github/`/`.githooks/` files, went through
      without needing a version bump — correct, since neither path
      changes the running add-on itself).
    - **If this check ever needs adjusting** (e.g. a new file/directory
      that shouldn't require a version bump), update the exclude pattern
      in BOTH files — they're deliberately kept as two independent copies
      of the same logic rather than one script both call, since the
      workflow runs in GitHub's environment and the hook runs in whatever
      local environment is doing the committing; don't let them drift
      apart silently if only one gets edited.

32. **Fixed a second, more subtle mobile bug** (reported via a follow-up
    phone screenshot after #30's fix already improved things): individual
    charts — not the whole page anymore — were still overflowing past the
    phone viewport, specifically the SVG bar charts rendering at their raw
    ~620-unit `viewBox` width as if it were literal pixels, ignoring the
    `.viz-svg { width: 100%; height: auto; }` CSS meant to scale them down.
    Root cause: none of the 8 SVG-generating functions set explicit
    `width`/`height` attributes on the `<svg>` root, only `viewBox`. Some
    mobile WebKit/Safari versions need BOTH `viewBox` and explicit
    intrinsic `width`/`height` attributes present to reliably compute the
    aspect ratio `height: auto` depends on for CSS-driven responsive
    scaling — with only `viewBox`, the fallback behavior can render at an
    undefined or raw-unit intrinsic size instead. Fixed by adding
    `width="{W}" height="{H}"` (matching each chart's own `viewBox`
    dimensions) to every `<svg viewBox="0 0 {W} {H}" ...>` tag — this is
    the standard, well-established technique for reliable cross-browser
    responsive SVG (same principle as an `<img>` with both `width`/`height`
    attributes AND a CSS override — the attributes give the intrinsic
    size/aspect-ratio, CSS still fully controls the rendered size). If a
    9th chart function is ever added, it needs the same `width="{W}"
    height="{H}"` on its `<svg>` tag — this isn't optional boilerplate,
    it's what makes the responsive CSS actually take effect on mobile.
    Verified: all 9 real (non-empty-state) SVGs across both example
    dashboards now carry explicit dimensions; the handful of bare
    `<svg></svg>` empty-state placeholders in thinner/older bundles
    (QQQ, an ETF with little fundamental data) are intentional and
    unrelated — confirmed those are the existing "no data for this chart"
    fallback, not a regression.

33. **Fixed a THIRD mobile overflow bug — #32's own fix caused this one.**
    After #32 (adding explicit `width="{W}" height="{H}"` to every `<svg>`
    for mobile Safari's benefit), a follow-up screenshot showed the
    longest bar in a chart (the one with the highest value — by
    construction the one whose bar+label reaches furthest right) still
    running off the phone screen with no visible label, while every
    shorter bar in the same chart rendered correctly. That specific
    pattern — the *rest* of the chart properly responsive, only the
    *widest* content clipped — is the signature of a completely different
    CSS mechanism than #32's bug, not a leftover of the same one:
    - **CSS Grid items default to `min-width: auto`**, which resolves to
      the item's *content-based minimum size* as long as `overflow` is
      `visible` (the default — true here). For a **replaced element**
      (`<svg>`, `<img>`, etc.) with explicit width/height attributes, that
      content-based minimum is its intrinsic size — i.e. exactly the
      `width="620"` I added in #32. So a `.card` (a direct child of the
      page-level `.grid`, i.e. an actual CSS Grid item) containing an SVG
      with `width="620"` gets a **hard 620px floor** on its own minimum
      width, completely independent of the `.viz-svg { width: 100%; }`
      CSS meant to shrink it — `width: 100%` controls the *rendered* size
      after layout, `min-width: auto` constrains what the *grid track
      itself* is allowed to shrink to in the first place. This is a
      well-documented, common CSS Grid gotcha (often called "grid
      blowout"), and #32's fix (necessary and correct on its own) is
      exactly the kind of change that triggers it.
    - Fixed with `min-width: 0` on every actual grid-item class in this
      page: `.card` (child of the page grid), `.stat-tile` (child of
      `.kpi-row`), `.split-2col > div` and `.rec-thesis` (children of
      their respective two-column grids). This is the standard fix for
      this exact issue — explicitly overriding the `auto` default lets
      the grid track shrink freely; the descendant's own `width: 100%`
      (or text wrapping, for non-SVG content) then actually takes effect
      instead of being overridden by the track's content-based floor.
      Also added `max-width: 100%` to `.viz-svg` itself as a second,
      independent safety net.
    - **If a new `display: grid` container is ever added to this page,
      its direct children need `min-width: 0`** (or `overflow` other than
      `visible`) as a matter of course, *especially* if they might contain
      a replaced element (svg/img/video/canvas) with explicit intrinsic
      dimensions — don't wait for a fourth screenshot to rediscover this.
    - Honest note on why this took three rounds: each fix was individually
      correct and tested as thoroughly as this environment allows (no
      real browser/device, only structural HTML checks), but CSS Grid's
      interaction with replaced-element intrinsic sizing is a genuinely
      non-obvious mechanism that structural checks (svg counts, leaked
      values) can't catch — only an actual rendered viewport can, which is
      exactly why the user's phone screenshots kept finding things a
      "does the HTML look reasonable" pass didn't.

34. **Replaced every hand-rolled inline-SVG chart with Apache ECharts** (0.9.0)
    — the direct payoff of the whole 0.8.1-0.8.8 stretch above: every one of
    those bugs (clipping, label collision, diverging-bar overflow on skewed
    data, inconsistent margins between neighboring charts) was hand-tuned
    pixel geometry fighting a fundamentally manual approach, and each fix
    only ever covered the specific case a screenshot happened to catch. User's
    call to stop patching and move to a real charting framework, choice of
    library delegated to Claude. Hybrid architecture, not a rewrite — Flask/
    CLI still just call `build_dashboard(bundle, pipeline_result)` for one
    HTML string; only the ~10 chart-generating functions changed internally.
    - **Vendored, not CDN-loaded**: `dashboard/assets/echarts.min.js` (full
      build, Apache-2.0) + a new hand-written `dashboard/assets/dashboard.js`
      runtime, copied next to every generated dashboard by
      `dashboard/assets.py`'s `ensure_vendored_assets(dest_dir)` — called
      from every site that writes a dashboard HTML file (`webapp/app.py`'s
      `/run` handler; `main.py`'s `dashboard` command, after all 3 of its
      output-path branches resolve to one `output_path`), same reasoning as
      item 28's Ingress work: this add-on may run with no internet egress at
      request time, and a relative asset path resolves correctly under
      Ingress, plain Flask, or a bare `file://` open with zero extra
      routing/prefix logic.
    - **Chart functions keep their exact signatures**, still do all data
      shaping/formatting in Python (every datapoint gets a pre-formatted
      `fmt` string via the existing `fmt_usd`/`fmt_pct`/`fmt_price`/
      `fmt_compact` helpers — JS never re-derives display text from a raw
      number) — only the return value changed, from an SVG string to
      `(div_html_or_None, table[, legend])`. `register_chart(option,
      height_px, aria_label)` allocates an id, stores the option in a
      per-`build_dashboard()`-call registry, and returns the placeholder
      div; the registry gets serialized once as `window.__CHARTS__` near the
      end of the page.
    - **Colors and formatters never travel through the option dict as real
      values** — colors stay as literal `"var(--xxx)"` strings (the same CSS
      custom property names used everywhere else) and formatters are one of
      a small set of string tokens (`__tooltipFmt__`, `__labelFmt__`, etc.).
      `dashboard.js`'s `hydrateOption()` is the one place that resolves both
      into real values/functions, called fresh before every `setOption()` —
      this is also what makes dark-mode re-theming trivial
      (`reapplyTheme()`: re-run `hydrateOption` against the *original*
      stored option, `setOption(..., true)` so nothing stale lingers) with
      zero per-chart-type special-casing anywhere.
    - **RSI gauge is a deliberate visual-form change**, not just a
      re-implementation: native `type: "gauge"` (semicircular dial) instead
      of the old horizontal zone-strip-with-a-dot. This is the idiomatic
      ECharts way to render "single value + zones + a big number," and it's
      what made the old headline-clipping-against-the-SVG-edge bug (item
      30/32) structurally impossible rather than papered over with more
      offset math.
    - **Empty-state contract**: chart functions return `(None, empty_state())`
      for no/invalid data (not an empty `"<svg></svg>"` string) —
      `viz_card()` treats `chart_html=None` as "table only, no toggle
      button, table visible immediately" (`.viz-table-only` CSS class).
      **Three call sites were found still passing a literal `"<svg></svg>"`
      for their empty-data branch** (EPS surprise history, quarterly
      revenue/income, buyback spend) — fixed to pass `None`; before the fix,
      a ticker with no data for one of these would show a blank chart pane
      behind a live-but-pointless "View as table" toggle instead of the "No
      data" message immediately. **Two more real bugs, same root cause, one
      level up**: two call sites (the recommendation-trend small-multiples
      loop in `section_analyst`, and the fair-value-range block in
      `section_ai_recommendation`) interpolate a chart function's return
      value directly into an f-string instead of going through `viz_card()`,
      so they never got its `None` guard — a period with no analyst-
      recommendation data, or a Judge response with an inverted/equal
      `fair_value_low`/`fair_value_high` range (plausible LLM schema drift —
      see "STILL NOT tested end-to-end" above), would leak the literal text
      "None" onto the page. Both fixed (skip/fallback instead of leaking).
      **Only partially caught by the existing `assert_no_leaked_values`
      test** (`tests/test_dashboard_build.py`, regex-based, checks for
      `>None<` among other patterns): the `<svg></svg>` bugs weren't a
      `None`/`nan` leak at all so the regex never had a chance; the
      fair-value one *is* a `None` leak but the interpolated `{fv_svg}` sits
      on its own line between two `<div>` tags, not contiguous with `><`, so
      even that regex missed it. If a future chart call site skips
      `viz_card()` for a custom layout, guard its `None` return explicitly —
      don't assume the leaked-value test will catch it.
    - Verified: full `pytest` suite (306 tests) green; all 6 committed
      `output/*.json` fixtures render with no leaked `None`/`nan`; the three
      fixed empty-data paths and the two fixed `None`-leak paths all
      re-verified directly with synthetic inputs after the fix; a real
      `python main.py dashboard ... -o <arbitrary path>` run confirmed
      `ensure_vendored_assets()` actually places both JS files next to an
      explicit `-o` output path, not just the default `OUTPUT_DIR`.
      **Still NOT verified** (no real browser available in the environment
      this was fixed in, same gap noted throughout items 25-33): an actual
      Playwright pass (console errors, real rendered chart size, dark-mode
      re-coloring, the table/chart toggle) and a direct look at the RSI
      gauge's new semicircular form. Do both before fully trusting this on
      a real phone/browser.

## Known limitations (stated honestly to the user already — don't silently "fix"
## these by faking data; if addressing them, do it for real or flag the tradeoff)

- **Institutional ownership** (`fetch_institutional.py`) is still a current
  snapshot only (top holders, % institutional/insider) — NOT a true
  quarter-over-quarter 13F delta. `fetch_beneficial_ownership.py` (13D/13G)
  now covers >5% stakes with amendment tracking, which is a real
  improvement, but it's a different, narrower thing than a full 13F trend.
- **DEF 14A proxy and the combined 10-K/10-Q/8-K text are not both digested
  down.** Only `filings_raw` (10-K/10-Q/8-K) gets a Haiku digest step;
  `proxy_raw` is fetched in full but currently sits in the bundle
  un-summarized — the agents still see it (everything in the bundle is
  visible to them), it's just not pre-condensed the way filings/news are.
- **Earnings call transcripts were explicitly evaluated and declined**, not
  just "not gotten to." SEC filings never contain them (not a regulatory
  requirement); free options are fragile/ToS-grey scraping (e.g. Motley
  Fool) and reliable options are paid APIs (FMP, Finnhub premium, AlphaSense).
  Decision: financial statements (now much more complete — see above) are
  sufficient; revisit only if live recommendations turn out to miss
  something that only shows up in call commentary/tone.
- **News full-text fetching** (`fetch_news.py` → `_fetch_article_text`) will
  fail for many paywalled/blocked sources by design; it falls back to
  headline + snippet for those. Expected, not a bug to "fix" by trying
  harder to bypass paywalls.
- **No real analyst reports.** Institutional research products aren't
  accessible for free anywhere; using yfinance's analyst rating/price-target
  aggregates as a thinner free proxy.
- **Backtesting is not built.** `backtest/` is an empty placeholder. Do NOT
  trust any live recommendation until this exists and has been run over
  historical data with strict point-in-time data discipline (no lookahead
  bias — a backtest for date X must only use news/filings/prices that
  existed as of date X).

## What has been tested, and how (important: read before assuming things work)

**Verified working against REAL live services this session** (previously only
unit-tested against synthetic data — this is a meaningful upgrade in
confidence):
- Full `python main.py check TICKER --dry-run` end-to-end run — confirmed
  clean (no errors, no warnings) for AAPL and MBLY.
- Every `yfinance`-backed module (price/technicals incl. RSI/MACD,
  fundamentals, short interest, balance sheet, income statement, institutional
  holders, news headlines) — confirmed against live Yahoo Finance data.
- Every SEC EDGAR-backed module — CIK lookup, submissions JSON, Form 4/144
  XML parsing, 13D/13G XML parsing (incl. namespace handling), 10-K/10-Q/8-K
  fetch + text extraction (incl. MD&A section targeting and 8-K exhibit
  discovery), DEF 14A fetch — confirmed against live SEC EDGAR responses for
  both AAPL and MBLY, plus spot-checks against several other tickers
  (MSFT, PG, KO, JPM, NVDA, META, TSLA, GOOGL, IBM, V) to validate edge cases
  like non-earnings 8-Ks and non-standard exhibit filenames.
- Real bugs found and fixed via this live testing (not hypothetical):
  a trailing NaN price row from yfinance breaking all technicals; Form 4's
  primaryDocument pointing at a pre-rendered HTML viewer instead of raw XML;
  Form 4 title parsing missing the `"true"/"false"` flag convention; a hidden
  inline-XBRL metadata block consuming the entire filing-text budget before
  reaching any real prose; the MD&A "2nd occurrence" heuristic landing on the
  wrong spot for some filers; 8-K exhibit filenames not containing "ex99" at
  all for some filers.

**STILL NOT tested end-to-end** (the actual gap remaining):
- **Real Anthropic API calls** — the four reasoning agents (bull/bear/skeptic/
  judge) and the two digest calls (`filings_digest`, `news_digest`) have never
  executed against the live model in any session so far. No API key has been
  used yet. This is the single biggest untested surface. Verify the JSON
  schemas the models actually return match what the parsing code expects —
  prompts ask for exact schemas but models sometimes drift.
- **Full `python main.py check TICKER` (no `--dry-run`)** — never completed
  successfully, same reason.

## Automated test suite (`tests/`, `pytest.ini`, CI)

Added after a long stretch of everything being validated by hand (ad hoc
Python one-liners, manual BeautifulSoup checks, Flask test-client calls
typed into Bash). Two tiers:

- **Tier 1 — `pytest` (default), runs in CI on every push/PR
  (`.github/workflows/tests.yml`)**: pure functions and anything that can
  use a fixture instead of a live network call. 160 tests across
  formatting (`test_formatting.py`), SVG chart generation
  (`test_charts.py`), full dashboard assembly against every committed
  `output/*.json` bundle (`test_dashboard_build.py`), the agent JSON
  parser (`test_agents_client.py`), Flask routes including the Ingress
  path-prefix bug and the ticker-validation security boundary
  (`test_webapp.py`), CLI output-path resolution (`test_main_cli.py`),
  config/cost-estimation (`test_config.py`), and SQLite storage
  (`test_storage_db.py`).
- **Tier 2 — `pytest -m live`, never run in CI**: one shape-only test per
  `data/fetch_*.py` module against a real AAPL fetch
  (`test_live_fetchers.py`). Excluded by default via `pytest.ini`'s
  `addopts = -m "not live"`. Slow, network-dependent, not something CI
  should ever gate on.

A real bug was found writing these: `diverging_bar_horizontal`'s
empty-input branch returned a 2-tuple instead of the 3-tuple every other
chart function returns (never triggered in production — its one call
site already guards against empty input — but would crash on direct
use). Fixed in `dashboard/generate_dashboard.py`, shipped as 0.1.4.

`.githooks/pre-commit` and `.github/workflows/version-check.yml`'s
exclude lists were extended to cover `tests/`, `pytest.ini`, and
`requirements-dev.txt` — dev-only files that shouldn't force an add-on
version bump (they're also excluded from the Docker build via
`.dockerignore`).

## Optional data sources (FRED, FMP, Finnhub signals)

Three data sources beyond the original set, all genuinely optional -- each
degrades gracefully to null fields + a note if its key isn't set, matching
the existing pattern for every other optional fetch in this codebase:

- **FRED** (`FRED_API_KEY`, `data/fetch_macro_context.py`) -- free forever,
  no paid tier exists. Adds CPI inflation (YoY), unemployment rate, the fed
  funds rate, and the 10y-2y yield curve spread to `macro_context`,
  alongside the existing VIX/10Y-Treasury fields.
- **FMP** (`FMP_API_KEY`, `data/fetch_fmp_valuation.py`) -- free tier, 250
  calls/day. New `fmp_valuation` bundle section: a DCF fair-value estimate
  and a PEG ratio. The DCF value is a second, independent valuation anchor
  alongside yfinance's own analyst targets -- Bull/Bear/Judge's fair-value
  estimate (see "fair-value range" above) now cites it too. Built against
  FMP's `/api/v3/` endpoints since those are the most consistently
  documented; FMP has been migrating toward a newer `/stable/` namespace,
  so if this stops working, that's the first thing to check.
- **Finnhub** (`FINNHUB_API_KEY`, `data/fetch_finnhub_signals.py`) -- same
  key already used for the news source. New `finnhub_signals` bundle
  section: Insider Sentiment (MSPR -- Finnhub's own aggregated "were
  insiders net buying or selling this month" score, a summary on top of
  the raw Form 4 transactions already pulled from SEC EDGAR) and
  Recommendation Trend (monthly aggregate analyst buy/hold/sell counts
  over time, different from the individual firm-level actions already
  pulled from yfinance).

All three have since been verified live against real API keys (never
committed anywhere -- entered only as local environment variables for a
one-off test, then discarded). Two real bugs were found and fixed this way:
- FMP's `/api/v3/discounted-cash-flow` and `/api/v3/ratios-ttm` returned
  403 Forbidden even with a valid key -- v3 is dead, not just "legacy."
  Fixed to use FMP's newer `/stable/...` namespace (query-param `symbol=`
  instead of a path param). Also: the field FMP calls "PEG" was renamed
  from `pegRatioTTM` (v3) to `priceToEarningsGrowthRatioTTM` (stable).
- FRED's CPI YoY calculation used a fixed list position (`obs[12]`) to find
  "12 months ago," which broke when CPIAUCSL had a one-off missing month
  (October 2025 came back `"."` -- FRED's marker for a not-yet-published
  observation, likely a government-shutdown-delayed release). Fixed to
  match by actual date (closest observation to exactly 365 days before the
  latest one) with a few extra months of buffer, so a single gap doesn't
  silently misalign the whole calculation.

## Explicitly deferred (do not build unless asked)

- Telegram notifications (design was sketched earlier: only notify on
  buy/sell with confidence ≥ threshold, never on hold/insufficient_data —
  documented in earlier chat, not in any file yet)
- Watchlist automation / scheduler / cron
- Backtesting implementation (folder exists, empty)
- Auto-trading / broker integration — permanently out of scope, not just deferred
- Web UI
- Earnings call transcripts — evaluated and declined, see "Known limitations" above

## Suggested next steps

1. **The actual next milestone**: add a real `ANTHROPIC_API_KEY` to `.env` and
   run `python main.py check AAPL` (no `--dry-run`) — the first real test of
   the 4-agent pipeline and the two digest calls against the live API. Watch
   closely for JSON schema drift from what `agents/prompts/*.md` specify.
2. Once that works reliably, sanity-check whether the combined 10-K/10-Q/8-K
   digest and the news digest are giving good signal-to-noise — may be worth
   tuning `MAX_FILING_CHARS` or the digest prompts based on what actually
   comes back.
3. Consider whether `proxy_raw` (DEF 14A) is worth a digest step of its own,
   same pattern as `summarize_filing`/`summarize_news`.
4. Only after the above work reliably: discuss backtesting before touching
   Telegram/scheduler, per the person's own stated priority order.
