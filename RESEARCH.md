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
| MarkMcKinney/asset-alert | 0 | Borrow the idea — simple one-shot Telegram push after a run, exactly the shape we'd want. |
| legendkong/StockHiker | 1 | Skip — built around polling for chat commands, wrong shape for us. |
| RyanElliott10/wsbtickerbot | 134 (archived) | Skip — the code is actually broken today (a dependency it used shut down in 2024). |
| wbollock/wsbtrends | 5 | Borrow the idea only — its simpler approach still works, but it's a tiny personal script. |

## What actually looks worth building, in rough priority order

1. **Backtesting** — install `backtesting.py` for real, feed it the price data we
   already fetch, write a strategy around our existing RSI/MACD signals.
2. **A free offline sentiment score** — use the FinBERT model from Hugging Face
   alongside our existing StockTwits sentiment.
3. **A deterministic Risk/position-size check** — a new, zero-LLM-cost step inspired
   by ai-hedge-fund's Risk Manager, feeding into the Judge's input.
4. **Real quarter-over-quarter institutional ownership tracking** — pull 13F data
   free from SEC EDGAR the way sec-13f-filings does, store two quarters in our
   SQLite, diff them.
5. **A non-AI "Quant Score" panel** — a weighted, percentile-ranked score (like
   xang1234's) to sit next to the LLM's opinion as a sanity check.
6. **Watchlist automation** — a GitHub Actions workflow running our own `main.py`
   on a schedule, plus a Telegram push at the end (asset-alert's pattern).
7. **One extra Bull/Bear debate round** — cheap to add, inspired by TradingAgents.
8. **An RL "voice"** — lowest priority, and only after trying gradient boosting
   first; see `research/03-rl-and-sentiment-tools.md` for the full reasoning.

None of this has been built yet — these are notes to work from, not commitments.
