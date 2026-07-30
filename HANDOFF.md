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

2. **Model assignment per agent role (not all Opus):**
   - Bull, Bear, and the digest steps (filings/news summarization) → Haiku 4.5
     (`claude-haiku-4-5-20251001`) — cheap, these are first-pass/mechanical tasks.
   - Skeptic → Sonnet 5 (`claude-sonnet-5`) — needs to actually critique reasoning.
   - Judge → Opus 5 (`claude-opus-5`) — the call that matters most, reserve the
     strongest model for it.
   These model ID strings are in `config.py` (`MODEL_BULL`, `MODEL_BEAR`,
   `MODEL_SKEPTIC`, `MODEL_JUDGE`, `MODEL_DIGEST`) — update there if Anthropic
   renames/replaces models, not scattered through the codebase.

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
