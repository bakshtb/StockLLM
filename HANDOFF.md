# StockLLM — Handoff to Claude Code

This document captures everything decided and built so far in a separate chat
(claude.ai), before the person switched to Claude Code to continue development.
Read this fully before making changes — it explains *why* things are built the
way they are, not just what's in the code.

## Project goal

A personal research tool: give it a stock ticker, it gathers real data
(price/technicals, fundamentals, balance sheet, insider transactions,
institutional ownership, SEC filings, news) and runs it through a multi-agent
LLM pipeline (Bull / Bear / Skeptic / Judge) that produces a structured
buy/sell/hold recommendation with confidence and reasoning, printed to the
terminal.

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
│   ├── fetch_fundamentals.py      # P/E, market cap, analyst targets (free, yfinance)
│   ├── fetch_balance_sheet.py     # debt, cash, free cash flow (free, yfinance)
│   ├── fetch_insider.py           # SEC Form 4 insider transactions (free, SEC EDGAR)
│   ├── fetch_institutional.py     # institutional holder snapshot (free, yfinance)
│   ├── fetch_filings.py           # 10-Q/10-K/8-K fetch + Haiku digest (SMALL LLM COST)
│   ├── fetch_news.py              # headlines (free) + full-article Haiku digest (SMALL LLM COST)
│   ├── edgar_utils.py             # shared SEC EDGAR helpers (CIK lookup, rate-limited requests)
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
├── main.py                        # CLI entrypoint: `python main.py check TICKER [--dry-run]`
├── backtest/                      # empty placeholder, not built yet
├── requirements.txt
├── .env.example
└── README.md
```

## Key design decisions and why

1. **Deterministic data layer vs. LLM reasoning layer are strictly separated.**
   Everything in `data/` except `fetch_filings.py` and the digest half of
   `fetch_news.py` makes zero LLM calls — pure API/data fetching. This keeps
   inputs reproducible and debuggable.

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
   API key required in this mode. This was added specifically because the person
   couldn't pay for Claude Pro/API access yet and wanted to validate the data
   layer for free first.

7. **Data completeness expansion** (the most recent work session): the person
   pushed back that the original data bundle (just price + headlines + basic
   fundamentals) wasn't "the full picture" compared to what a real analyst uses.
   Added, in order of person's stated priority: insider transactions, balance
   sheet health, SEC filings digest, full news article digest, technical
   indicators, institutional ownership. All six were built in this pass.

## Known limitations (stated honestly to the user already — don't silently "fix"
## these by faking data; if addressing them, do it for real or flag the tradeoff)

- **Institutional ownership** (`fetch_institutional.py`) is a current snapshot
  only (top holders, % institutional/insider), NOT a true quarter-over-quarter
  13F delta. Real "who's been buying" trend tracking would require diffing
  consecutive 13F filings from SEC EDGAR over time — not implemented.
- **News full-text fetching** (`fetch_news.py` → `_fetch_article_text`) will
  fail for many paywalled/blocked sources by design; it falls back to
  headline + snippet for those. This is expected, logged via
  `articles_with_full_text` count in the digest result, not a bug to "fix" by
  trying harder to bypass paywalls.
- **No real analyst reports.** Institutional research products aren't
  accessible for free anywhere; using yfinance's analyst rating/price-target
  aggregates as a thinner free proxy.
- **Backtesting is not built.** `backtest/` is an empty placeholder. The person
  was told explicitly: do NOT trust any live recommendation until this exists
  and has been run over historical data with strict point-in-time data
  discipline (no lookahead bias — a backtest for date X must only use news/
  filings/prices that existed as of date X).

## What has been tested, and how (important: read before assuming things work)

The environment these were built in (claude.ai's sandboxed tool) has network
access to `api.anthropic.com` but NOT to Yahoo Finance, SEC EDGAR, or general
websites (locked-down egress allowlist). This means:

**Verified working (unit-tested with synthetic/mocked data in that sandbox):**
- RSI and MACD math (`data/fetch_prices.py`) — tested against synthetic
  uptrend/downtrend price series, confirmed RSI >70 on uptrend, <30 on
  downtrend, MACD histogram sign matches trend direction.
- Form 4 XML parsing (`data/fetch_insider.py` `_parse_form4_xml`) — tested
  against a realistic sample Form 4 XML structure, correctly extracts owner
  name, title, transaction direction (buy/sell), shares, price.
- HTML-to-text stripping for filings (`data/fetch_filings.py` `_strip_html`) —
  confirmed scripts/styles are removed, body text preserved.
- JSON extraction from LLM responses (`agents/client.py` `_extract_json`) —
  tested against clean JSON, markdown-fenced JSON, and JSON with stray
  surrounding text.
- Prompt templating for skeptic/judge (placeholder substitution) — verified no
  leftover `{{...}}` placeholders after filling.
- Full pipeline wiring (`agents/pipeline.py` `run_pipeline`) — ran against a
  synthetic bundle with a fake `run_id`; confirmed it fails at exactly the
  expected point (missing `ANTHROPIC_API_KEY`) with correct error wrapping,
  meaning all the logic before the actual API call (db writes, cost
  accumulation via `starting_cost_usd`, run_id threading) is sound.
- All modules import cleanly and compile without syntax errors.

**NOT tested end-to-end against real services** (because the build environment
couldn't reach them):
- `yfinance` calls (price, fundamentals, balance sheet, institutional holders,
  news headlines) — should work fine on a normal internet connection, but has
  not been run against live Yahoo Finance data.
- SEC EDGAR calls (`edgar_utils.py`, insider transactions, filings fetch) — CIK
  lookup, submissions JSON parsing, and document fetching are implemented per
  SEC's documented API structure but not verified against live responses.
  Watch for: EDGAR's real JSON structure sometimes has quirks not visible from
  documentation alone (e.g. array alignment between `form`, `accessionNumber`,
  `primaryDocument` in the "recent" filings block).
- Actual Anthropic API calls with a real API key — the four reasoning agents
  and the two digest calls have never actually executed against the live model.
  Verify the JSON schemas the models actually return match what the parsing
  code expects (agent prompts ask for exact schemas but models sometimes drift).
- Full end-to-end `python main.py check TICKER` run (no `--dry-run`) — never
  completed successfully since no API key has been available yet in any
  session so far.

**The person's very next step was going to be**: run `python main.py check AAPL
--dry-run` locally (free, no API key) to validate the expanded data layer, then
add their Anthropic API key and run a real full check for the first time.

## Explicitly deferred (do not build unless asked)

- Telegram notifications (design was sketched earlier: only notify on
  buy/sell with confidence ≥ threshold, never on hold/insufficient_data —
  documented in earlier chat, not in any file yet)
- Watchlist automation / scheduler / cron
- Backtesting implementation (folder exists, empty)
- Auto-trading / broker integration — permanently out of scope, not just deferred
- Web UI

## Suggested next steps for this Claude Code session

1. Run `python main.py check AAPL --dry-run` for real and fix whatever breaks —
   this is the first real-world test of yfinance + SEC EDGAR calls.
2. Once dry-run is clean, help the person get their Anthropic API key set up and
   run one real full check — this is the first real test of the 4-agent
   pipeline and the digest steps against the live API. Watch closely for JSON
   schema drift from what the prompts specify.
3. Only after both of those work reliably: discuss backtesting before touching
   Telegram/scheduler, per the person's own stated priority order.
