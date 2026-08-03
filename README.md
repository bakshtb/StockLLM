# StockLLM

A multi-agent LLM research tool: give it a stock ticker, it deterministically
gathers price/news/fundamentals data, then runs a Bull / Bear / Skeptic / Judge
agent pipeline and prints a structured recommendation to the terminal.
Available as both a CLI and a Home Assistant add-on with a web UI
(see "Home Assistant add-on" below) — the CLI keeps working unchanged either way.

**This is a research/decision-support tool. It is NOT financial advice, and it
never places trades. Nothing here is a substitute for your own judgment or a
licensed financial advisor.**

## Setup

1. Install Python 3.10+ if you don't have it.
2. Open a terminal in this folder and install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env`:
   ```
   copy .env.example .env
   ```
   (On Windows Command Prompt; use `cp` on Mac/Linux.)
4. Get an Anthropic API key from https://console.anthropic.com (Settings → API Keys),
   and put it in `.env`:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
5. Set `SEC_EDGAR_USER_AGENT` in `.env` to your name + email (SEC requires this
   to identify who's making requests -- no key/signup needed, just an honest
   contact string, e.g. `SEC_EDGAR_USER_AGENT=YourName your@email.com`).
6. (Optional) Get a free Finnhub API key from https://finnhub.io to supplement
   news coverage. Not required — yfinance's free news feed works without it.

## Usage

```
python main.py check AAPL                # full run: data + digests + 4-agent pipeline
python main.py check AAPL --dry-run       # raw data fetch only, no LLM calls, free
python main.py dashboard AAPL             # fetch fresh (dry-run) + write an HTML dashboard
python main.py dashboard output/mobileye.json  # or build one from an existing bundle JSON file
```

Generated JSON bundles and HTML dashboards land in `output/` by default
(`--output`/`-o` overrides; a bare filename still resolves inside `output/`,
an explicit path elsewhere is respected as given).

**Full run** fetches:
- Price history + technical indicators (RSI, MACD, moving averages) — free
- Fundamentals (P/E, market cap, analyst targets) — free
- Analyst rating actions (individual firm upgrades/downgrades/reiterations,
  last ~60 days) — free
- Earnings surprise history (actual vs. estimated EPS, last 4 quarters) and
  forward EPS/revenue estimate trends + revisions — free
- Relative performance vs. the S&P 500 and the ticker's sector ETF — free
- Dividend yield/history and recent quarterly buyback spend — free
- Options-market sentiment (put/call ratio, implied volatility skew) — free
- Analyst target price range/dispersion, and institutional/insider ownership
  % (both fixed/added to existing free fields) — free
- Macro backdrop: VIX level and 10-year Treasury yield, with 20-day change — free
- Stock's trailing P/E vs. the S&P 500's and its sector ETF's P/E (valuation
  premium/discount, distinct from return comparison) — free
- Social/crowd sentiment: bullish vs. bearish tag counts from recent public
  StockTwits posts — free
- Balance sheet health (debt, cash, free cash flow) — free
- Insider transactions (SEC Form 4 filings) — free
- Institutional ownership snapshot (top holders) — free
- Backtests of 7 well-known trading rules against the ticker's own multi-year
  price history (win rate, return vs. buy & hold, max drawdown per rule) — free
- **Filings digest**: latest 10-Q/10-K/8-K summarized by a cheap model — small cost
- **News digest**: recent articles (full text where fetchable) summarized by a cheap
  model — small cost

...then runs the 4-agent reasoning pipeline (bull/bear/skeptic/judge) on all of it,
and prints the recommendation, confidence, reasoning, key risks, and a data quality
caveat to the terminal.

**`--dry-run`** skips all LLM calls entirely (including the digest steps) and just
prints the raw fetched data plus a quick health check of what came back — no API
key needed, completely free. Good for testing the data layer before spending anything.

Every full run is logged to a local SQLite database at `storage/stockllm.db`,
including the full research bundle and every agent's (and digest's) raw output and
cost — nothing is thrown away, so you can review the reasoning behind any past
recommendation later.

## Dashboard

`python main.py dashboard TICKER` (or point it at any existing bundle JSON file,
e.g. `python main.py dashboard mobileye.json`) generates a single self-contained
`.html` file — no server, no build step, no internet connection needed to view it,
just open it in a browser. It renders every section of the research bundle as
charts/tables: price & technicals, analyst ratings + estimates, relative
performance & valuation, financials, ownership, dividends/buybacks/options/
macro/sentiment, news, filings, and a data-quality-notes panel. Supports light/dark
mode (persisted across opens) and a "view as table" toggle on every chart.

Built for readers with no finance background: an "At a Glance" panel at the top
translates the numbers into plain-language sentences ("AAPL is up 62.4% over the
past year — beating the S&P 500 by 46.2%"), every metric has a small "i" you can
click for a jargon-free explanation, and directional values (returns, earnings
beats/misses, profit/loss, sentiment) are colored green/red. Genuinely ambiguous
numbers (P/E premium, insider selling) stay neutral with an explanation rather
than a forced good/bad color. See `dashboard/generate_dashboard.py` — it's a
pure rendering layer over the bundle JSON, no network calls of its own; the one
exception is the At a Glance panel, which is templated from fixed thresholds on
real fields, never an LLM call or inferred claim.

When a full (non-dry-run) check has been run, the dashboard also shows an
**AI Recommendation** panel — the 4-agent pipeline's actual verdict
(recommendation, confidence, reasoning, key risks, bull/bear theses, the
skeptic's flagged concerns), clearly marked as the one section that's an AI
opinion rather than raw data. `build_dashboard(bundle, pipeline_result)`
takes an optional second argument for this; omit it (as `--dry-run` does)
and that panel just doesn't render.

## Home Assistant add-on

StockLLM can also run as a Home Assistant add-on: install it from this
GitHub repo, configure your API key once in the add-on's Configuration
tab, and get a web page in the HA sidebar to pick a ticker, toggle
dry-run, and view the dashboard — no terminal needed. See `DOCS.md` for
the full install walkthrough and `HANDOFF.md` for the packaging decisions
behind it. The add-on is just a second entrypoint (`webapp/app.py`, a
small Flask app) into the exact same `data/`, `agents/`, and `dashboard/`
code the CLI uses — nothing
is duplicated, and the CLI keeps working exactly as before regardless of
whether the add-on is installed.

**If you're developing on this repo**: run `git config core.hooksPath
.githooks` once per checkout. Home Assistant only notices an add-on update
when `config.yaml`'s `version:` field changes, so a pre-commit hook (and a
GitHub Actions check on every push, as a backstop) both block/flag any
commit that changes add-on-relevant files without bumping it.

## Cost control

`config.py` / `.env` has `MONTHLY_SPEND_LIMIT_USD` (default $50). The CLI checks
total spend for the current calendar month before each full run and refuses to run
if you're over the limit. Actual cost per run (digests + reasoning pipeline combined)
is printed after each run and stored in the database.

## Known limitations (being upfront about these)

- **Institutional ownership** is a current snapshot (top holders, % institutional),
  not a true quarter-over-quarter 13F change. Real "who's been buying" trend
  tracking would need diffing consecutive 13F filings over time — not built yet.
- **News full-text fetching** will fail for many paywalled/blocked sources; the
  digest falls back to headline + snippet for those, which is expected behavior,
  not a bug.
- **Analyst reports** (the real institutional research products) aren't accessible
  for free anywhere — we use yfinance's analyst rating/price-target aggregates
  instead, which is a reasonable free proxy but thinner than a real analyst note.

## Project structure

- `data/` — data fetching. Most of this is deterministic/free (price, fundamentals,
  balance sheet, insider transactions, institutional ownership). Two files
  (`fetch_filings.py`, and the digest half of `fetch_news.py`) make small LLM calls
  to summarize long text — clearly marked in their docstrings.
- `agents/` — the 4 reasoning agents (bull, bear, skeptic, judge), their prompts,
  and the shared Anthropic API client (handles prompt caching + JSON parsing + retries).
- `storage/` — SQLite schema and helper functions.
- `dashboard/` — the HTML dashboard generator (used by both the CLI and the add-on).
- `webapp/` — the Flask web UI the Home Assistant add-on runs; a second
  entrypoint into the same `data`/`agents`/`dashboard` code, not a separate
  implementation.
- `output/` — generated JSON bundles and HTML dashboards land here by
  default (both CLI and add-on; the add-on redirects this to its own
  persistent `/data` volume instead, see `run.sh`).
- `main.py` — the CLI entrypoint.
- `repository.yaml`, `config.yaml`, `Dockerfile`, `run.sh` — Home Assistant
  add-on packaging (see "Home Assistant add-on" above and `DOCS.md`).
- `backtest/` — runs a fixed set of well-known technical trading rules (RSI
  mean-reversion, MACD crossover, moving-average crossover, Bollinger Band
  reversion, 20-day breakout, a trend-filtered dip buy, and relative strength
  vs. the S&P 500) against a ticker's own multi-year price history, using the
  `backtesting` library. Deterministic, no LLM involved -- see
  `backtest/strategies.py` for the rule definitions and
  `research/02-backtesting-and-screening-tools.md` for why these specific
  ones were picked. Results show up in the dashboard's "Strategy Backtests"
  section for every run (full or dry-run).

## What's deliberately NOT built yet

- Telegram notifications
- Watchlist automation / scheduling

These are documented in the original project spec and can be added once you've
run the CLI on real tickers for a while and are comfortable with how it reasons.

## Troubleshooting

- **"No price history found for ticker"** — check the symbol is correct (use the
  exchange ticker, e.g. `AAPL` not `Apple`).
- **Agent JSON parsing errors** — the client retries once automatically; if it
  still fails, it's usually a model hiccup, just re-run.
- **Hitting the monthly spend limit unexpectedly** — check `storage/stockllm.db`
  (table `runs`) to see your run history, or raise `MONTHLY_SPEND_LIMIT_USD` in `.env`.
