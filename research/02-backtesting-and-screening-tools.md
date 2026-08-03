# Backtesting and Screening Tools

This is file 2 of a 3-file research series. All three document real hands-on findings
from actually cloning outside projects and reading their source code (not just their
READMEs), done to find concrete ways to improve StockLLM. This file covers backtesting
libraries, 13F ownership-change tracking, screener automation, and non-AI scoring
approaches. (The other two files cover LLM multi-agent projects, and RL/sentiment
tools.)

---

## kernc/backtesting.py (⭐ 8,752)
**Link:** https://github.com/kernc/backtesting.py

**What it does:** A small Python library for testing "if I had followed this trading
rule, would I have made money?" on historical price data for one asset at a time. You
write a small class describing your buy/sell rule, hand it a price history, and it
simulates trades bar-by-bar and spits out a stats report (win rate, drawdown, Sharpe
ratio, etc.).

**What we found after actually reading the code:** The core package is small —
`backtesting/backtesting.py` (1,778 lines), `backtesting/lib.py` (helper strategies and
indicators), `backtesting/_stats.py` (the stats calculator). Two classes matter:
`Strategy` (abstract base — you override `init()` to precompute indicators and `next()`
to decide what to do on each new bar) and `Backtest` (you give it a DataFrame + your
Strategy subclass and call `.run()`).

The `Backtest` constructor is explicit about what it wants: a `pandas.DataFrame` with
columns exactly named `Open`, `High`, `Low`, `Close`, and optionally `Volume`
(capitalized), indexed by a `DatetimeIndex` (or a plain increasing integer index). It
even raises a clear `ValueError` if the columns don't match, and warns (rather than
silently failing) if the index isn't sorted or isn't a real datetime index. This is
*exactly* the shape of DataFrame that `yfinance`'s `tk.history(period="1y")` returns —
which is what our own `data/fetch_prices.py` already calls today (it just doesn't keep
the raw `hist` DataFrame around; it summarizes it into a dict of scalars for the
indicator computation and throws the DataFrame away).

Inside your `Strategy.init()`, you declare indicators by wrapping any function in
`self.I(...)`, e.g. `self.sma1 = self.I(SMA, self.data.Close, 10)`. The library ships a
`crossover(series1, series2)` helper in `backtesting/lib.py` for the extremely common
"line A crosses above line B" pattern. Their canonical example strategy,
`SmaCross`, is literally:

```python
class SmaCross(Strategy):
    n1 = 10
    n2 = 20
    def init(self):
        self.sma1 = self.I(SMA, self.data.Close, self.n1)
        self.sma2 = self.I(SMA, self.data.Close, self.n2)
    def next(self):
        if crossover(self.sma1, self.sma2):
            self.position.close(); self.buy()
        elif crossover(self.sma2, self.sma1):
            self.position.close(); self.sell()
```

`Backtest(data, SmaCross).run()` returns a `pandas.Series` with ~25 fields: Start/End
dates, Exposure Time %, Equity Final, Return %, Buy & Hold Return % (a benchmark
comparison for free), Sharpe Ratio, Sortino Ratio, Calmar Ratio, Max Drawdown %,
# Trades, Win Rate %, Best/Worst/Avg Trade %, Profit Factor, and more — plus a
`_trades` DataFrame with every individual trade if you want to inspect them.

Dependencies (from `setup.py`): `numpy`, `pandas`, and `bokeh` (their plotting engine).
Bokeh is a real, somewhat heavy dependency (it's a full interactive-plotting stack with
its own JS assets) — but it's only imported when you call `.plot()`. If we never call
`.plot()` and instead just read the stats `Series` (which is all we'd want, since we
already have our own ECharts dashboard), bokeh still gets installed via pip but doesn't
need to do any work at runtime. On a Pi-class host that's an extra ~30-40MB install, not
nothing, but not a dealbreaker either — it's a normal `pip install backtesting` with no
compiled/native extensions beyond what numpy/pandas already pull in. License is
AGPL-3.0, which mostly matters if you distribute a modified copy of the library over a
network; for a personal, non-distributed tool this is a non-issue, but worth remembering
if this project were ever shared publicly as a hosted service.

**What we can take or use:** Concretely: `pip install backtesting`, take the raw `hist`
DataFrame that `data/fetch_prices.py` already gets from `yf.Ticker(ticker).history(...)`
(currently discarded after computing summary stats), pass it straight into
`Backtest(hist, MyStrategy)`. Write a `Strategy` subclass around our existing signals —
e.g. "buy when RSI-14 crosses below 30, sell when it crosses back above 70" or "buy on
MACD histogram crossing zero" — reusing the exact same RSI/MACD math we already have in
`_compute_rsi`/`_compute_macd` in `data/fetch_prices.py` (just fed in via `self.I()`
instead of computed once at the end). This would populate the currently-empty
`backtest/` folder with a real, working "would this rule have worked historically"
feature, single-ticker, no server needed, on-demand rather than continuously running.

**Should we use the project directly, or just borrow an idea from it?** Use it directly
as a real pip dependency — it's small, well-scoped to exactly our single-ticker
use case, and expects the same DataFrame shape our data layer already produces.

---

## toddwschneider/sec-13f-filings (⭐ 430, last updated 2024)
**Link:** https://github.com/toddwschneider/sec-13f-filings

**What it does:** A website (not a library) that lets you browse institutional
investors' quarterly 13F filings — which stocks big funds hold, and how those holdings
changed from quarter to quarter — pulled from SEC EDGAR.

**What we found after actually reading the code:** This is a full **Ruby on Rails**
web application, not a Python script or library — Rails MVC structure
(`app/models`, `app/controllers`, `app/views`), PostgreSQL via `db/schema.rb` and
raw SQL views in `db/views/*.sql`, background jobs (`clock.rb`, `Procfile.clockandworker`
suggest a `delayed_job`-style worker), and a JS frontend (Tailwind, DataTables). There
is nothing here we can `pip install` — but the actual SEC-fetching *technique* is fully
readable and worth stealing.

The key file is `app/lib/sec_client.rb`. It does two things:
1. **Bulk discovery** — for a full quarter's worth of filings, it downloads
   `https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{quarter}/master.idx`, a
   plain pipe-delimited text file SEC publishes (columns: `cik|company_name|form_type
   |date_filed|filename`), and filters rows where `form_type` is `13F-HR` or
   `13F-HR/A`. This is the free, no-API-key bulk index SEC provides for every filing
   type, every quarter, going back years.
2. **Per-filing parsing** — once it has a filer's filing directory URL, it fetches the
   directory listing (HTML), finds the `.xml` files inside (there are always two: a
   "primary doc" with filer info, and an "information table" with the actual
   holdings), and parses each with Nokogiri (an XML parser) — pulling out CUSIP
   (a 9-character security ID), issuer name, dollar value, share count, and voting
   authority per holding.

Two operational details we'd need to copy exactly: (a) SEC **requires** a custom
`User-Agent` header identifying your app/contact info on every request — the code
raises an explicit error if `ENV["SEC_USER_AGENT"]` isn't set, citing SEC's webmaster
FAQ; get this wrong and SEC blocks you. (b) it explicitly handles HTTP 429 (rate
limited) as a distinct exception (`SecClient::RateLimited`) — meaning in practice they
found SEC does throttle you and you need to back off, not just retry blindly.

Quarter-over-quarter change isn't computed as a single precomputed "% change" field
anywhere — it's done by simply pulling two `ThirteenF` filings for the same manager
(`compare_holdings` action in `app/controllers/thirteen_fs_controller.rb`) and letting
the view/JS diff the two holdings tables. So the "trend" feature is really just "fetch
this quarter's snapshot and last quarter's snapshot and diff them yourself" — there's no
clever trend math to borrow, just the fetching/parsing mechanics.

**What we can take or use:** Not the code itself (wrong language, wrong architecture —
a whole Rails+Postgres web app for what we need is way overkill). But the *approach* is
directly portable into a new file like `data/fetch_institutional_13f.py`: (1) hit the
same `master.idx` bulk index URL per quarter with a proper `User-Agent` header (must
include contact info per SEC rules), (2) find the filer's info-table XML, (3) parse out
CUSIP + share count + value with Python's `xml.etree` or `lxml`, (4) since our
`data/fetch_institutional.py` already tracks a snapshot, store two snapshots (this
quarter + previous quarter) in our SQLite storage layer and diff share counts ourselves
to get real quarter-over-quarter ownership change — closing the gap we already knew
about. This is maybe a day of focused work, not a big lift, but it is new code we'd
have to write and test ourselves, not something to import.

**Should we use the project directly, or just borrow an idea from it?** Just borrow the
technique (bulk EDGAR index + per-filing XML parsing + required User-Agent header) —
the project itself is a full Rails app we can't depend on.

---

## RyanJHamby/stock-screener (⭐ 33)
**Link:** https://github.com/RyanJHamby/stock-screener

**What it does:** A Python screener that scans thousands of US stocks every weekday
morning looking for buy/sell setups, entirely on GitHub's free infrastructure — no
server of your own needed. Results get emailed and saved as a report.

**What we found after actually reading the code:** The actual workflow file is
`.github/workflows/daily_screening_git_storage.yml`. It's triggered by
`schedule: - cron: '0 12 * * 1-5'` — 7am Eastern, Monday-Friday only (skips weekends,
smart since markets are closed). It also supports manual runs via
`workflow_dispatch`. The job: checks out the repo (shallow clone), sets up Python
3.11 with pip caching, installs `requirements.txt`, then runs
`python run_optimized_scan.py --conservative --git-storage`.

The rate-limit-avoidance approach is genuinely clever and is fully visible in
`run_optimized_scan.py`: it uses a small thread pool (2-5 workers, configurable via
`--conservative`/`--aggressive` flags) where each worker sleeps a fixed delay
(0.3-1.0 seconds) between requests — e.g. `--conservative` gives 2 workers x 1
request/second = ~2 requests/second total, deliberately slow to stay under free-tier
API limits while scanning ~3,800 stocks (they estimate 15-30 minutes total runtime).
The bigger trick for cost/rate control is `--git-storage`: it caches each ticker's
fundamentals as a JSON file under `data/fundamentals_cache/<TICKER>_fundamentals.json`,
and — this is the interesting part — the workflow **commits that cache directory back
into the git repo itself** at the end of every run (see the "Commit updated
fundamental cache" step, which does `git add data/fundamentals_cache/` and pushes).
That means tomorrow's run starts with yesterday's fundamentals already warm in the
checked-out repo, so it only needs to re-fetch fundamentals for tickers that actually
had new data (they claim a 74% reduction in API calls this way). Price data is
re-fetched fresh every run since prices change daily, but fundamentals (P/E, earnings)
change quarterly so caching them in git avoids most of the API traffic.

Delivery/storage: results go to a plain text report (`data/daily_scans/*.txt`), which
gets attached to the GitHub Actions run via `actions/upload-artifact` (kept 90 days),
and separately there's `automated_position_report.py` which emails a summary using
SMTP credentials stored as GitHub Actions secrets (`EMAIL_FROM`, `EMAIL_PASSWORD`,
`EMAIL_TO` — Gmail SMTP by default). No database, no server — the git repo doubles as
both the code host and the results/cache store.

**What we can take or use:** The workflow file structure ports over almost directly.
For our case (a personal single-ticker watchlist, not 3,800 tickers) we don't need
the parallel worker/rate-limit complexity at all — we could write a much simpler
`.github/workflows/nightly-check.yml` with `cron: '0 12 * * 1-5'`, checkout, set up
Python, `pip install -r requirements.txt`, then loop
`python main.py check TICKER --dry-run` over a short watchlist (a handful of tickers,
not thousands, so no rate-limit engineering needed). We could commit results/logs
back to the repo the same way if we want a free historical record, or just rely on
our existing `storage/` SQLite logging plus GitHub Actions artifacts for the run
output. The email-via-SMTP-secrets pattern is also directly reusable if we ever want a
morning digest without keeping the Pi running.

**Should we use the project directly, or just borrow an idea from it?** Just borrow the
idea (a cron-scheduled GitHub Actions workflow calling our own `main.py`) — this
project's code (the screener logic, universe-wide scanning, VCP pattern detection) is
irrelevant to us since we only care about a small personal watchlist, not the whole
market.

---

## xang1234/stock-screener (⭐ 265)
**Link:** https://github.com/xang1234/stock-screener

**What it does:** Originally a simple IBD-style ("Investor's Business Daily" stock
rating methodology) stock screener; as of this clone (mid-2026) it has grown into a
large full-stack app (FastAPI/Celery backend with Alembic migrations, a static-site
frontend, theme extraction, group rankings) — much bigger and more complex than the
"⭐265 simple screener" the star count suggests. We focused only on its scoring/rating
logic, which is the part relevant to us.

**What we found after actually reading the code:** Two scoring modules matter:

1. `backend/app/services/eps_rating_service.py` computes an "EPS Rating" (an
   IBD-style earnings-quality score). The formula is explicit and simple:
   `raw_score = 0.40 * CAGR_5yr + 0.50 * avg(Q1_YoY, Q2_YoY) + 0.10 * (Q1_YoY - Q2_YoY)`
   — i.e. 40% weight on 5-year earnings growth, 50% weight on recent quarterly YoY
   growth, and a 10% "acceleration bonus" that rewards earnings growth speeding up
   (Q1 growth minus Q2 growth). All three weights (`ALPHA=0.40`, `BETA=0.50`,
   `GAMMA=0.10`) are hardcoded class constants, not user-configurable. Extreme
   values get capped (growth clamped to -100%/+500%) so one crazy outlier doesn't
   blow up the score. Critically, this **raw score alone isn't the final rating** —
   `calculate_percentile_ranks()` takes the raw scores of every stock in your
   universe and converts each one into where it ranks from 0-99 (percentile), which
   is the actual "EPS Rating" IBD-style number. So a stock's score is always relative
   to everything else you scanned, not an absolute number.

2. `backend/app/domain/relative_strength/calculator.py` computes an "RS Rating"
   (relative strength vs. the market) the same way but across five time horizons:
   1-month, 3-month, 6-month, 9-month, 12-month excess return (stock return minus
   benchmark return), weighted 20%/30%/20%/15%/15% respectively (heaviest weight on
   the 3-month window). Each horizon's excess-return values are percentile-ranked
   (1-99) across the universe *first*, then those five percentile ranks are combined
   with the horizon weights into one composite number, and *that* composite is
   percentile-ranked *again* to get the final 1-99 RS Rating. So it's a two-step
   percentile-of-percentile approach specifically so no single horizon with a wild
   scale dominates the others — a cleaner way to combine multiple differently-scaled
   metrics than plain min-max or z-score normalization.

Both scoring services are pure, self-contained Python functions with no ML —
straightforward weighted sums plus percentile ranking, easy to read in an afternoon.

**What we can take or use:** The technique — not the code, since it's tightly wired
into their FastAPI/Celery/Postgres stack — but the pattern is directly buildable in
our `data/` layer as a new lightweight `data/compute_quant_score.py`: pick our
existing metrics (RSI, MACD signal, moving-average trend, relative performance vs
S&P500/sector ETF that `data/fetch_relative_performance.py` already computes,
analyst rating direction, earnings surprise), assign hardcoded weights the way they
do, and since we only ever look at one ticker at a time (not a universe), we can't
literally percentile-rank against other stocks scanned in the same run — but we could
percentile-rank against that same ticker's own trailing history (e.g. "is today's
composite score higher than 80% of this stock's readings over the last year?") to get
a similar 0-99 "how favorable is this setup relative to normal for this stock" number.
That would give us a genuine non-AI "Quant Score" panel to sit next to the LLM
verdict as a sanity check, exactly the gap we identified.

**Should we use the project directly, or just borrow an idea from it?** Just borrow the
idea (weighted composite score + percentile-rank normalization) — the project itself
has become a large multi-service app we have no reason to depend on.

---

## franklinjtan/Portfolio-Diversification-Correlation-Risk-Management-with-Python (⭐ 4)
**Link:** https://github.com/franklinjtan/Portfolio-Diversification-Correlation-Risk-Management-with-Python

**What it does:** A small Jupyter notebook that checks whether the assets in a
portfolio move together too much (over-concentration risk) by looking at how
correlated their daily price moves are.

**What we found after actually reading the code:** It's a single notebook,
`Correlation Matrix.ipynb`, plus a folder of downloaded CSV price histories (SPY,
AMZN, GOOG, a handful of sector ETFs like FHLC/FIDU/FSTA, GLD, OXY, CNQ, SPHQ, VYM).
The actual calculation is exactly as simple as it sounds — no fancy math:
1. For each asset, compute daily % change from `Adj Close`
   (`df['pct'] = df['Adj Close'].pct_change()`).
2. For each asset vs. SPY, run `scipy.stats.linregress(spy, asset)` to get beta
   (market sensitivity) and the correlation coefficient (`r_value`).
3. For the full group, build one DataFrame of all the % change series and call
   pandas' built-in `.corr()` to get a full pairwise correlation matrix in one line.
4. Plot the matrix as a `seaborn.heatmap()`, color-coded, with the correlation
   numbers annotated on each cell.

There is **no programmatic "too correlated" threshold anywhere in the code** — no
`if corr > 0.8: flag as risky` logic. The "detection" is entirely visual: you look at
the heatmap and eyeball which cells are dark/high. It's a nice illustration notebook,
not a decision-making tool.

**What we can take or use:** If we ever wanted a lightweight "how correlated is this
new ticker to stuff I already hold" check, the whole technique is 3 lines of pandas:
pull daily closes for the candidate ticker and whatever's already in a personal
watchlist, `.pct_change()`, then `.corr()`. No dependency needed beyond pandas, which
we already use everywhere. We would have to pick our own threshold (something like
"flag if pairwise correlation > 0.7") since the source project doesn't supply one.

**Should we use the project directly, or just borrow an idea from it?** Just borrow the
idea — it's three lines of pandas, not worth depending on a notebook for, and we'd
need to add our own threshold logic since none exists in the source.

---

## stefan-jansen/machine-learning-for-trading (⭐ 20,257)
**Link:** https://github.com/stefan-jansen/machine-learning-for-trading

**What it does:** The companion code repo for a well-known book comparing linear
models, tree ensembles, gradient boosting, deep learning, and reinforcement learning
for generating trading signals from financial data. This is a reference/teaching
resource, not a library you'd install.

**What we found after actually reading the code:** This is a much bigger, more
modern repo than the "book from a few years ago" framing suggests — as cloned, it's
organized into numbered chapter folders, and Chapter 12
("Gradient Boosting and Advanced Tabular Models", see its own
`12_gradient_boosting/README.md`) is the directly relevant one for our "non-AI
Quant Score" idea. It systematically benchmarks sklearn's HistGradientBoosting,
XGBoost, LightGBM, and CatBoost against each other, and separately against newer
tabular deep-learning approaches (TabPFN, TabM, TabR) and a plain linear model, on
real financial panels (an ETF panel, and an academic "firm characteristics" dataset).

The headline conclusion (spelled out directly in the chapter README) is exactly what
our earlier shallow research suggested: **gradient boosting remains the default
choice for most financial tabular problems** — the deep-learning tabular alternatives
are only sometimes worth their added complexity, and the chapter frames this as "the
real edge often comes from matching model, label, horizon, and evaluation design,"
not from picking a fancier model family. It also stresses **walk-forward validation**
(train on the past, test on data the model never saw, moving the window forward in
time) as essential — a plain train/test split overstates how good the model looks,
because it lets the model "peek" at a period statistically similar to what it trained
on.

One important caveat: **this specific clone is a heavy, modernized rewrite**, not the
original book's lightweight code. The gradient-boosting benchmark notebook alone
(`02_gbm_comparison.py`) is documented as needing ~52GB peak memory and a GPU for its
full run, uses a custom internal `ml4t.diagnostic` package, Docker images
(`ml4t-gpu`), and Optuna-based hyperparameter search across multiple libraries. None
of that scale is something we'd run — it's built for someone benchmarking model
families across huge datasets, not for training one small model on one ticker's
technical indicators on a Raspberry Pi.

**What we can take or use:** Not the code or the environment (wrong scale entirely
for our use case) — but two ideas port over cleanly: (1) if we ever build the
"Quant Score" idea from `xang1234/stock-screener` above using an actual ML model
instead of hand-picked weights, gradient boosting (via plain `lightgbm` or
`xgboost`, tiny pip installs, CPU-only, no GPU needed for a small feature set) is the
literature-backed choice over anything fancier; (2) whatever model we train, evaluate
it with walk-forward validation (train on older data, test on newer data the model
never saw, roll the window forward) rather than a random train/test split — this
matters just as much for the RL-agent idea from our other research file as it does
here.

**Should we use the project directly, or just borrow an idea from it?** Just borrow
the ideas (gradient boosting as the default choice, walk-forward validation as the
correct way to test it) — it's a teaching repo built at a scale and complexity far
beyond what we'd ever run ourselves.

---
