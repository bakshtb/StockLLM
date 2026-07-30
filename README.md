# StockLLM (v1 — CLI only)

<!-- push test: verifying cross-machine git push works -->

A multi-agent LLM research tool: give it a stock ticker, it deterministically
gathers price/news/fundamentals data, then runs a Bull / Bear / Skeptic / Judge
agent pipeline and prints a structured recommendation to the terminal.

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
```

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
- Balance sheet health (debt, cash, free cash flow) — free
- Insider transactions (SEC Form 4 filings) — free
- Institutional ownership snapshot (top holders) — free
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
- `main.py` — the CLI entrypoint.
- `backtest/` — placeholder for later; not built in v1.

## What's deliberately NOT built yet

- Telegram notifications
- Watchlist automation / scheduling
- Backtesting

These are documented in the original project spec and can be added once you've
run the CLI on real tickers for a while and are comfortable with how it reasons.

## Troubleshooting

- **"No price history found for ticker"** — check the symbol is correct (use the
  exchange ticker, e.g. `AAPL` not `Apple`).
- **Agent JSON parsing errors** — the client retries once automatically; if it
  still fails, it's usually a model hiccup, just re-run.
- **Hitting the monthly spend limit unexpectedly** — check `storage/stockllm.db`
  (table `runs`) to see your run history, or raise `MONTHLY_SPEND_LIMIT_USD` in `.env`.
