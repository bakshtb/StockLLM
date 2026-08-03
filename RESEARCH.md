# Research notes — what other projects taught us

This is a set of notes from actually cloning other stock-related projects on GitHub and
reading their real source code (not just their README marketing copy), to find concrete
ways to improve StockLLM. Written in plain English for a solo developer, not a research
committee.

There are three detail files, one per topic:

- **[research/01-llm-multi-agent-projects.md](research/01-llm-multi-agent-projects.md)**
  — other "AI agents debate a stock" projects (TradingAgents, ai-hedge-fund, FinRobot,
  plus a few small Telegram/screener hobby tools).
- **[research/02-backtesting-and-screening-tools.md](research/02-backtesting-and-screening-tools.md)**
  — backtesting libraries, free SEC 13F ownership data, GitHub-Actions-based automated
  scanning, non-AI scoring approaches, and a gradient-boosting reference repo.
- **[research/03-rl-and-sentiment-tools.md](research/03-rl-and-sentiment-tools.md)**
  — Reinforcement Learning (RL) trading frameworks, and sentiment tools (FinBERT,
  Reddit/WallStreetBets scrapers).

This followed an earlier round of research (web search only, no cloning) that produced
a first-pass list of ~20 candidate projects — this round went deeper on the ones that
looked genuinely useful, by actually opening their code.

## Quick-reference table

| Project | Stars | Verdict |
|---|---|---|
| kernc/backtesting.py | 8,752 | **Use it directly** — small `pip install`, expects the exact same price data shape we already fetch. Best pick for our missing backtest feature. |
| ProsusAI/finBERT (the Hugging Face model, not the repo) | 2,201 (repo dead, model still gets 5.7M downloads/month) | **Use it directly** — free offline sentiment scoring in 3 lines of code, no LLM call needed. |
| TauricResearch/TradingAgents | 95,453 | Borrow the idea — their Bull/Bear "debate" is just a counter + growing text transcript, and even they default to 1 round like us. Cheap to add a rebuttal round. |
| virattt/ai-hedge-fund | 62,615 | Borrow the idea — their Risk Manager agent is pure math (numpy/pandas), zero LLM calls, sets a hard position-size ceiling. Worth copying as a free deterministic check. |
| AI4Finance-Foundation/FinRobot | 7,716 | No change needed — confirms we already follow their "LLM never computes numbers" rule. |
| AI4Finance-Foundation/FinRL | 15,905 | Borrow the code pattern, don't depend on the package — their actual trading environment is ~150 lines; copy that logic if we ever build the RL agent, rather than installing the whole framework. |
| tensortrade-org/tensortrade | 6,611 | Borrow the idea — cleanly swappable "reward function" design, nicer than FinRL's for experimenting. |
| AminHP/gym-anytrading | 2,381 (stale) | Fine for learning RL basics on a toy example, not for production. |
| stefan-jansen/machine-learning-for-trading | 20,257 | Reference only — confirms gradient boosting is the go-to model family for this kind of data, and that "walk-forward" testing (never test on data older than what you trained on) is the right way to validate any model we build. |
| toddwschneider/sec-13f-filings | 430 | Borrow the technique, not the code (it's a Ruby/Rails app) — shows exactly how to pull real institutional-ownership data free from SEC EDGAR. |
| RyanJHamby/stock-screener | 33 | Borrow the idea — runs entirely on GitHub's free scheduler (Actions), no server of our own needed. Good model for a watchlist feature. |
| xang1234/stock-screener | 265 | Borrow the idea — clean weighted-score + percentile-rank formula for a non-AI "Quant Score." |
| franklinjtan/Portfolio-Diversification-... | 4 | Borrow the idea — correlation check between stocks is 3 lines of pandas. |
| asircar/nifty-swing-screener | 2 | Borrow the idea — showing *why* each factor scored the way it did (not just the number) is a nice transparency touch for a dashboard. |
| MarkMcKinney/asset-alert | 0 | Not needed — we already run on the Home Assistant add-on, which has its own automations/notifications built in. No reason to bolt on a separate Telegram bot. |
| legendkong/StockHiker | 1 | Skip — built around polling for chat commands, wrong shape for us. |
| RyanElliott10/wsbtickerbot | 134 (archived) | Skip — the code is actually broken today (a dependency it used shut down in 2024). |
| wbollock/wsbtrends | 5 | Borrow the idea only — its simpler approach still works, but it's a tiny personal script. |

## What actually looks worth building, final list

Six items, in priority order. FinBERT and the RL "voice" were both considered and
dropped — the reasoning for both is preserved in "Follow-up findings" below, but
neither is on the active list anymore.

### 1. Backtesting

Install `kernc/backtesting.py` for real (a normal `pip install`, not a big lift) and
feed it the same price DataFrame `data/fetch_prices.py` already gets from
`yfinance` — confirmed by actually reading the library's code that its `Backtest`
class wants exactly the `Open`/`High`/`Low`/`Close` + `DatetimeIndex` shape yfinance
already returns, so no reshaping work is needed. Write a `Strategy` subclass around
signals we already compute (e.g. "buy when RSI-14 crosses below 30, sell when it
crosses back above 70").

**Info/benchmarks:** this isn't a predictive model, so there's no accuracy
benchmark to cite — it's a testing tool, and its value is procedural. It comes with
real, standard stats built in for free (Sharpe, Sortino, Calmar ratios, win rate,
max drawdown, profit factor, and a "Buy & Hold Return%" baseline for automatic
comparison), all confirmed by reading the library's actual stats calculator, not
assumed from its docs. **Effort:** small, roughly a day — it's a dependency, not a
from-scratch build.

### 2. Real quarter-over-quarter institutional ownership tracking

Build a new `data/fetch_institutional_13f.py` using the exact technique confirmed by
reading `toddwschneider/sec-13f-filings`'s real code: SEC publishes a free bulk
index file per quarter (`.../full-index/{year}/QTR{q}/master.idx`) listing every
13F filing, then each filer's holdings live in a separate XML file you fetch and
parse (CUSIP, share count, dollar value per holding). Store this quarter's and last
quarter's snapshot in our existing SQLite, diff the share counts ourselves.

**Info/benchmarks:** not applicable — this is factual government data, not a
prediction, so there's nothing to benchmark. Two operational facts worth knowing,
both confirmed directly in their code: (1) SEC requires a descriptive `User-Agent`
header identifying who's asking, or it blocks you (we already do this correctly for
other EDGAR calls via `SEC_EDGAR_USER_AGENT` in `config.py`); (2) SEC does
rate-limit (HTTP 429) if you go too fast, so real backoff handling is needed, not
just a blind retry. **Effort:** roughly a day of new code — the technique is fully
mapped out, nothing to figure out from scratch.

### 3. A deterministic risk/volatility check

A new, zero-LLM-cost step modeled on `virattt/ai-hedge-fund`'s actual
`risk_manager.py` — confirmed by reading it directly that it contains zero LLM
calls, just numpy/pandas math. Their concrete method: compute annualized volatility
per stock, map it to a position-size ceiling via a simple piecewise-linear rule
(low-volatility stocks get a higher ceiling, high-volatility ones get capped much
lower — roughly 25% vs. 10% of a hypothetical position in their code), then reduce
that further if the stock is highly correlated with other things already held
(correlation ≥0.8 cuts the limit to 70% in their implementation).

**Info/benchmarks:** volatility-adjusted position sizing and correlation-based risk
reduction are standard, textbook portfolio risk management techniques, not
something this project invented — its value to us is a concrete, already-working
code shape to copy, not a novel finding. We'd repurpose "position size" as a
"how much weight should the Judge give this call" signal instead, since StockLLM
never actually holds positions. **Effort:** small — pure math over data we already
fetch, feeds into the Judge's prompt as one more context field.

### 4. A non-AI "Quant Score" panel

Either a hand-weighted score (`xang1234/stock-screener`'s approach: pick metrics we
already have — RSI, MACD signal, relative performance vs. sector/S&P500, earnings
surprise direction — assign fixed weights, percentile-rank the composite) or, as a
later upgrade, a small gradient-boosting model (XGBoost/LightGBM) trained on the
same features.

**Info/benchmarks:** on model choice, the literature leans fairly consistently one
way. `stefan-jansen/machine-learning-for-trading`'s benchmark chapter found
gradient boosting is generally the strongest model family for this kind of tabular
financial data, ahead of plain linear models and newer tabular deep-learning
approaches. But worth holding that loosely — the same 2026 systematic review we
found while researching RL found model sophistication *in general* barely
correlates with real-world results (p≈0.499 in their meta-analysis), meaning
feature/label design likely matters more than which model family wins. If we ever
build the ML version, it must use **walk-forward validation** (train on older data,
test only on newer data the model never saw) rather than a random train/test split
— a random split would overstate accuracy for exactly the same reason it does in
every other quant discipline we researched (backtest overfitting). **Effort:** the
hand-weighted version is small, a day or two; the gradient-boosting version is a
bigger lift (needs a training/validation harness) but is a natural upgrade once the
simple version proves useful. This is the recommended **first** non-LLM "extra
voice" to build.

### 5. One extra Bull/Bear debate round

Modeled on `TauricResearch/TradingAgents`'s actual mechanism, confirmed by reading
`conditional_logic.py`: their "multi-round debate" is just a counter plus a growing
shared text transcript — each side's full argument gets appended, and the next
speaker's prompt gets the whole transcript plus the single last message to rebut.
Nothing more exotic than that.

**Info/benchmarks:** an important honest gap — despite TradingAgents' paper
claiming "extensive experiments," it never actually publishes a benchmark
comparing 1 round vs. 2 vs. more; that specific ablation doesn't exist in the
published paper. What real users do report (not the authors) is cost: roughly
$0.20–$0.80 per ticker for a single round with a GPT-4o-class model mix, and cost
scales close to linearly — **doubling debate rounds roughly doubles cost.** We
confirmed this applies to us directly: `agents/bull_agent.py`/`bear_agent.py` call
Gemini through a client path with **no prompt-caching support** (unlike the
Judge's Anthropic path, which does cache), so a second round gets no cache
discount and would roughly double just the Bull+Bear portion of a run's cost.
**Effort:** small code change, real recurring cost — cap at exactly one extra
round, and consider adding caching to the Gemini client at the same time to blunt
the added cost.

### 6. Correlation check between watchlist tickers — NOT FOR NOW

**Deferred, not scheduled.** This only makes sense once StockLLM has some kind of
watchlist/checklist feature (tracking more than one ticker at a time), which
doesn't exist yet. Revisit this item once that feature is built — until then it's
just notes, not something to pick up.

Modeled on `franklinjtan/Portfolio-Diversification-...`'s approach: daily
`.pct_change()` on price history, then pandas' `.corr()` for a full pairwise
correlation matrix — three lines of code, nothing fancier.

**Info/benchmarks:** their actual notebook has **no programmatic "too correlated"
threshold at all** — confirmed by reading it, the "detection" is just eyeballing a
color-coded heatmap. We'd have to pick our own cutoff; a common rule of thumb in
general portfolio-management practice is to flag pairs above roughly 0.7–0.8
correlation, but that's a convention, not a benchmarked finding from this project
or any study we found. **Effort:** trivial once it's relevant — but it only becomes
relevant once we have a personal watchlist tracking more than one ticker, so this
is naturally gated behind that not-yet-built feature.

---

~~Watchlist automation via GitHub Actions~~ and ~~Telegram alerts~~ — dropped. We
already run on the Home Assistant add-on, which has its own scheduling
(automations) and notification system — no need to bolt on GitHub Actions or a
separate Telegram bot for either of these.

None of this has been built yet — these are notes to work from, not commitments.

## Follow-up findings (from questions asked after the first pass)

**FinBERT vs. just asking our existing cheap LLM:** genuinely mixed in the
literature — some studies favor FinBERT, some favor modern LLMs, it depends on
the exact text and prompt. FinBERT's real advantage isn't accuracy, it's that
it's free per call and fully offline. Since we already make cheap Gemini calls
elsewhere, it may be simpler to just ask that same model to also score
sentiment in one small extra call, rather than installing `transformers`+`torch`
(a few hundred MB) for a model that isn't clearly more accurate. Worth deciding
based on dependency weight, not on an assumed accuracy win.

**The extra Bull/Bear debate round — real cost, not just "cheap to add":**
TradingAgents' own users report cost scales roughly linearly with debate
rounds — doubling rounds roughly doubles cost. We checked our own code:
`agents/bull_agent.py`/`bear_agent.py` call Gemini through a client with **no
prompt-caching support** (unlike the Judge's Anthropic path, which does cache).
That means a second round gets no cache discount — it would roughly double just
the Bull+Bear portion of a run's cost. Still worth doing, but cap it at exactly
one extra round, and consider adding caching to the Gemini client at the same
time to blunt the cost.

**Reinforcement Learning — the reality check, with real numbers:**
- Buying strong compute (a GPU) doesn't fix RL's actual problems. Training a
  small single-stock policy already takes minutes on ordinary CPU — compute was
  never the bottleneck. A 2026 meta-analysis found model sophistication barely
  correlates with real results (p=0.499) — a fancier model just overfits faster.
- We would not be first, not close. This is one of the most heavily-researched
  areas in quant finance — well-funded hedge funds, an annual academic
  competition (FinRL Contest, 200+ teams/100+ institutions), and FinRL itself
  (15,900+ stars) have all already tried this extensively.
- Published self-reported numbers look great (FinRL's own paper: Sharpe 2.81,
  52% annual return, beating the Dow). Independent checks tell a different
  story: the FinRL Contest's real, independent 200+-team competition found RL
  strategies got *worse* actual profitability than just holding the Dow Jones
  Index, despite better risk-adjusted numbers on paper. One study states over
  90% of academic trading strategies fail once tested with real capital — a
  pattern RL falls squarely inside.
- **Combining LLM knowledge with RL is a real, published research area** (not
  novel to us) — FinRL-DeepSeek feeds LLM-extracted news sentiment/risk scores
  into a risk-aware RL agent (CVaR-PPO). Important finding: naively feeding LLM
  signals into a *plain* RL agent actually **hurt** performance (the agent
  overreacted to news noise) — it only helped once paired with the risk-aware
  training method. Lesson for us: if we ever feed our own LLM digests into an
  RL agent's state, it needs a risk-capping training approach, not a naive
  injection, or it will likely make things worse.
- **No usable pretrained RL model exists to shortcut this.** Hugging Face's
  entire "stock-market" RL category has exactly 3 models total; the most-used
  one (142 downloads) is the same suspicious overfit demo already flagged
  earlier ("7,243% returns" claim, no real validation). Any real RL agent would
  have to be trained by us, off-device, not downloaded.

**Bottom line on RL, unchanged but now with real evidence behind it:** build
the Quant Score first. If RL ever happens, it's a shadow-mode experiment (logged,
never trusted) using FinRL's own ~150-line environment logic, not the framework
itself — see `research/03-rl-and-sentiment-tools.md` for the full detail.

**We already log almost everything a future RL/Quant-Score effort would need.**
Checked `storage/db.py` and `outcomes.py`: every full run already saves the
complete data bundle, every agent's raw output, the final recommendation, and —
via `outcomes.py` — the price 7 and 30 days later, with a WIN/LOSS grade
already computed. This already lives on the Home Assistant add-on's persistent
`/data` volume (confirmed in `run.sh`), so it survives restarts/updates and has
been quietly accumulating since the add-on started running. Considered adding
free scheduled dry-run snapshots for denser history, but decided against it:
dry-run skips the LLM pipeline entirely, so it would be missing exactly the
part that's actually irreplaceable (the recommendation and the LLM's read on
that day's news) — the raw price/technical data it would add is cheaply
re-fetchable later anyway, so it wasn't worth the added complexity. Left as-is:
data accumulates naturally every time a real check is run.
