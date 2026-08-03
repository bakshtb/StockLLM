# LLM Multi-Agent Projects — Research Notes (1 of 3)

This is file 1 of a 3-part research series documenting real, hands-on findings from
cloning other people's projects and actually reading their source code — not just
their READMEs. The other two files in the series cover backtesting/screening tools
and RL/sentiment tools. The goal of all three files is the same: find concrete
patterns or code we could adapt into StockLLM's own `data/`, `agents/`, or
`dashboard/` pipeline. This file covers six projects, three of which are big
LLM multi-agent trading/research systems (TradingAgents, ai-hedge-fund, FinRobot),
and three of which are tiny personal alert/screener scripts.

---

## TradingAgents (⭐ 95,453)
**Link:** https://github.com/TauricResearch/TradingAgents

**What it does:** A big simulated trading-firm pipeline built with LangGraph
(a library for wiring LLM "agents" together as nodes in a graph). Data
analysts gather market/news/social/fundamentals info, a Bull and a Bear
researcher debate the stock, a Research Manager decides who won, a Trader
proposes a plan, three risk personas (Aggressive/Neutral/Conservative) argue
about it, and a Portfolio Manager makes the final call.

**What we found after actually reading the code:** The debate isn't some
clever back-and-forth memory system — it's dead simple. Look at
`tradingagents/graph/conditional_logic.py`, function `should_continue_debate`:
it just keeps a counter (`investment_debate_state["count"]`) and a running
text blob (`history`). Every time Bull or Bear runs, it appends its whole
argument (prefixed `"Bull Analyst: ..."` or `"Bear Analyst: ..."`) onto that
shared `history` string, and the *next* agent's prompt just gets handed the
entire `history` string plus the single last message
(`current_response`) to specifically rebut. The router
(`should_continue_debate`) alternates: if the last speaker was Bull, next is
Bear, and vice versa, until `count >= 2 * max_debate_rounds`, then it exits to
the Research Manager. So "multi-round debate" = a while-loop over two prompts
that both read a growing shared transcript, gated by a plain counter. No
fancy state machine.

The genuinely surprising bit: `tradingagents/default_config.py` sets
`max_debate_rounds: 1` by default. That means out of the box, TradingAgents
runs exactly ONE Bull turn and ONE Bear turn — i.e. it's shipped configured
almost the same as our current single-pass setup! The "multi-round debate"
is a feature you have to explicitly turn up (via `TRADINGAGENTS_MAX_DEBATE_ROUNDS`
env var), not something baked in as essential. The graph wiring itself
(`tradingagents/graph/setup.py`) is also worth noting: it's a `StateGraph`
with `workflow.add_conditional_edges(...)` — after Bull or Bear runs, LangGraph
looks up `should_continue_debate`'s return value in a `path_map` dict to decide
where to route next. It's literally an if/else router bolted onto a shared
mutable state object (`AgentState`), nothing more exotic than that.

The Research Manager (`tradingagents/agents/managers/research_manager.py`,
their Judge-equivalent) reads the full `history` string and outputs a
structured `ResearchPlan` (rating: Buy/Overweight/Hold/Underweight/Sell) via
Pydantic schema binding — same idea as our Judge outputting structured JSON.

**What we can take or use:** The "second pass" pattern is realistic and
cheap to bolt on: after our Bull and Bear each argue once (as today), add ONE
more round where each gets the other's argument and writes a short rebuttal
before the Judge sees everything. This is exactly what
`should_continue_debate` does at `max_debate_rounds=2`. Concretely: in
`agents/pipeline.py`, after both `bull_agent.py` and `bear_agent.py` run
once, feed Bear's output into a second Bull call (and vice versa) with a
prompt like "here's the other side's argument, rebut it specifically" —
this mirrors their `current_response` / `history` fields. Given our LLM-spend
cap, we'd want to cap this at exactly one extra round each (2 total per
side), same as their sensible default.

**Should we use the project directly, or just borrow an idea from it?**
Don't adopt the project or LangGraph — it's way more machinery than a
single-ticker personal tool needs — but borrow the "one extra rebuttal round,
gated by a simple counter" idea for `agents/bull_agent.py` and
`agents/bear_agent.py`.

---

## ai-hedge-fund (⭐ 62,615)
**Link:** https://github.com/virattt/ai-hedge-fund

**What it does:** A simulated hedge fund where each "analyst" is a famous
investor persona (Warren Buffett, Charlie Munger, Michael Burry, etc.) that
gives a bullish/bearish/neutral signal with a confidence score. A Risk
Manager agent then works out how much of each stock is safe to hold, and a
Portfolio Manager agent turns all of that into a final buy/sell/hold decision
with a share quantity.

**What we found after actually reading the code:** The single most useful
finding in this whole batch: the Risk Manager
(`src/agents/risk_manager.py`, function `risk_management_agent`) has **zero
LLM calls in it**. Grepped the whole file for `invoke`/`llm`/`ChatOpenAI` —
nothing. It's 100% deterministic Python/numpy/pandas math:

1. Pulls price history for every ticker, computes daily returns and
   annualized volatility (`calculate_volatility_metrics`).
2. Maps volatility to a position-size ceiling as a percent of portfolio
   (`calculate_volatility_adjusted_limit` — low vol stocks get up to 25% of
   the portfolio, very high vol stocks get capped at ~10%. It's a simple
   piecewise linear function, no ML).
3. Also builds a correlation matrix across all held/candidate tickers and
   shrinks the position limit further if a stock is highly correlated with
   what's already held (`calculate_correlation_multiplier` — correlation
   ≥0.8 cuts the limit to 70%, correlation <0.2 actually gives a small
   bonus).
4. Combines volatility limit × correlation multiplier × total portfolio
   value = a hard dollar ceiling (`remaining_position_limit`) written into
   shared state as plain JSON.

The Portfolio Manager (`src/agents/portfolio_manager.py`) is the one that
actually calls an LLM, but it doesn't get to override the risk numbers — it
reads `remaining_position_limit` from the Risk Manager's output, divides by
current price to get `max_shares`, and passes that as a hard ceiling into
the LLM's decision prompt (a Pydantic-typed `PortfolioDecision` with
`action`/`quantity`/`confidence`/`reasoning`). So the LLM only picks a
number *within* a boundary that pure math already computed — the LLM never
invents the risk limit itself.

Also worth noting: this whole thing has no "debate." The persona agents
(Buffett, Munger, Burry, etc.) all run in parallel, fanning out from a
`start_node` and fanning back into `risk_management_agent` then
`portfolio_manager` (see `src/main.py`, the `workflow.add_node`/`add_edge`
calls). Structurally this is actually very close to what StockLLM already
does — Bull/Bear/two Skeptics running once each, then a Judge — except they
add one more deterministic-math step (the Risk Manager) before the final
LLM call.

**What we can take or use:** This is the most directly applicable idea in
the whole batch. We don't have a Risk Manager step at all right now — our
Judge just outputs a recommendation + confidence + key risks. We could add a
tiny, fully deterministic `agents/risk_checker.py` (no LLM call, following
the same rule FinRobot uses — see below) that:
- Pulls recent volatility (we already compute this-ish via our RSI/MACD
  technicals code in `data/`).
- Outputs a plain "how much of a typical position size this deserves"
  number or a caution flag (e.g. "volatility percentile: 92, treat
  conviction with more skepticism").
- Feeds that number into the Judge's prompt as one more piece of context,
  the same way ai-hedge-fund feeds `max_shares` into the Portfolio Manager.

Since StockLLM never places trades, we wouldn't need position-sizing exactly
— but a volatility/risk-percentile number that adjusts how much weight the
Judge gives to a "Strong Buy" call is a very cheap, zero-LLM-cost addition
(it's just numpy math, no extra API spend).

**Should we use the project directly, or just borrow an idea from it?**
Don't run the project (multi-ticker portfolio management is out of scope for
us), but definitely borrow the deterministic Risk Manager pattern — it's a
near-zero-cost, high-value addition to `agents/`.

---

## FinRobot (⭐ 7,716)
**Link:** https://github.com/AI4Finance-Foundation/FinRobot

**What it does:** A financial-analysis agent toolkit built on Microsoft's
AutoGen framework (a library for LLM agents that can call Python functions
as "tools"). It produces things like equity research reports, backtests, and
valuations (DCF, EV/EBITDA comps) by having an LLM call out to Python
functions for the actual math.

**What we found after actually reading the code:** The "LLM never computes
numbers, Python always does" claim holds up — we verified it two different
ways in two different parts of the codebase:

1. `finrobot_equity/core/src/modules/valuation_engine.py` has a
   `ValuationEngine` class with methods like `calculate_dcf_valuation` and
   `calculate_ev_ebitda_valuation`. These are plain Python: pull EBITDA and
   historical multiples from a pandas DataFrame, do arithmetic
   (`ev = ebitda * target_multiple`, discount future cash flows by a WACC —
   "weighted average cost of capital," a discount rate used in DCF models),
   and return a `ValuationResult` dataclass with a number and a
   `description` string. No LLM call anywhere in that file. One nuance
   worth flagging for later: their WACC is a hardcoded default assumption
   (`'wacc': 0.10`) rather than computed from the company's actual capital
   structure — a simplification we should be aware of if we ever borrow
   this, not a knock against the "no LLM math" claim.

2. The core `finrobot/` package (the older, more general part of the repo)
   uses AutoGen's tool-calling pattern directly:
   `finrobot/toolkits.py`'s `register_toolkits` function wraps every
   Python function with `stringify_output` and registers it via AutoGen's
   `register_function(caller=..., executor=...)`. This means the LLM
   ("caller" agent) can only *request* a function call by name; a separate
   "executor" agent actually runs the Python and returns a string result.
   The LLM literally cannot compute a number itself — it can only ask a
   tool to compute one, then write prose describing what came back. E.g.
   `finrobot/functional/quantitative.py`'s `BackTraderUtils.back_test`
   runs an actual `backtrader` backtest and returns real numbers; the LLM
   just narrates them.

The other interesting architectural thing: FinRobot's agents are configured
declaratively. `finrobot/agents/agent_library.py` + `workflow.py`'s
`FinRobot` class build each agent's system prompt from a config dict
(`title`, `responsibilities`, `toolkits`) rather than hand-writing a prompt
string per agent file. It's a reasonable way to keep many similar agents
consistent, though for our 6-agent pipeline it'd probably be over-engineering.

**What we can take or use:** We already follow the "LLM never computes
numbers" rule (our `data/` layer is deterministic Python for RSI, MACD,
etc., and agents only get numbers handed to them in the prompt) — this
confirms we're already doing the right thing, no code change needed. The
one thing worth stealing conceptually: their `ValuationResult` dataclass
pattern (`method`, `target_price`, `low_estimate`, `high_estimate`,
`assumptions`, `confidence`, `description`) is a clean, reusable shape for
any deterministic calculation whose result needs to be both machine-readable
(for the dashboard) and human-narratable (for the agent prompt/output). If
we ever add more calculated fields (e.g. a fair-value estimate), this shape
is worth copying.

**Should we use the project directly, or just borrow an idea from it?**
Not directly usable (AutoGen is a heavyweight dependency for a Pi-class
box, and most of FinRobot is US-equity-report generation we don't need),
but it's a good confirmation that our existing "Python computes, LLM
narrates" rule is the right call — no architecture change needed here.

---

## StockHiker (⭐ 1)
**Link:** https://github.com/legendkong/StockHiker

**What it does:** A tiny personal Telegram bot that replies to chat commands
with stock prices pulled from Yahoo Finance.

**What we found after actually reading the code:** It's genuinely small —
one file, `TelegramBot/main.py`, ~64 lines. Uses the `telebot` library
(pyTelegramBotAPI) with `@bot.message_handler(commands=[...])` decorators,
and calls `bot.polling()` at the bottom, which means it sits in a loop
waiting for someone to type a command like `/wsb` or `price TSLA` in the
chat, then replies. There's also a GitHub Actions workflow
(`.github/workflows/tg-notify.yml`) but that just pings Telegram whenever
someone pushes a commit to the repo — it's a CI notification, not a stock
alert feature, so not relevant to us.

**What we can take or use:** Confirms the obvious approach — a Telegram
bot is genuinely just a `telebot.TeleBot(API_KEY)` object plus decorated
handler functions. But note this repo's *polling* pattern
(`bot.polling()`, reacting to user-typed commands) is the wrong shape for
us: we don't want a chat bot that waits for us to ask it something, we want
something that pushes a message out automatically after each run
completes. See asset-alert below for that pattern instead.

**Should we use the project directly, or just borrow an idea from it?**
Not directly usable (wrong interaction model — polling/chat-command bot,
not a push notifier), but confirms `telebot`/python-telegram-bot is the
right library family if we build a Telegram feature.

---

## asset-alert (⭐ 0)
**Link:** https://github.com/MarkMcKinney/asset-alert

**What it does:** A tiny one-shot script (written in Go, not Python) that
checks a list of assets' price change since yesterday and sends a single
Telegram message with the results. No chat interaction at all.

**What we found after actually reading the code:** The whole thing is one
file, `asset_alert.go`, ~130 lines. It's the "push" pattern we actually
want: no polling loop, no command handlers. It runs once, computes
yesterday-vs-today percent change per asset (`getAssetAction`), builds one
text message, and calls `bot.Send(msg)` on a hardcoded `receiverID` (read
from an `.env` file: `TELEGRAM_BOT_API_KEY`, `ASSETS`, `RECEIVER`) — then
exits. That's it. This is meant to be triggered by an external
scheduler (cron, GitHub Actions, etc.), not to run continuously.

**What we can take or use:** This is the right shape for a StockLLM
Telegram notifier: after `main.py` finishes a run and the Judge produces its
final recommendation, do one HTTP POST (or one `telebot`/`python-telegram-bot`
`bot.send_message(chat_id, text)` call) with a summary, then exit — no
polling loop needed since we already run on a schedule via Home Assistant.
Concretely: add a small `notify/telegram.py` with one function
`send_summary(chat_id, text)` that does exactly this, called at the end of
`main.py` after the dashboard is generated.

**Should we use the project directly, or just borrow an idea from it?**
Don't use the Go code directly (wrong language for our stack), but borrow
the "one-shot push message after a run" pattern almost exactly as-is — it's
a 10-line addition to `main.py` using `python-telegram-bot`'s
`bot.send_message()`.

---

## nifty-swing-screener (⭐ 2)
**Link:** https://github.com/asircar/nifty-swing-screener

**What it does:** A rules-based (no AI at all) stock screener that scores
candidates for swing trading using a weighted checklist of technical
factors, and ranks them.

**What we found after actually reading the code:** The scoring logic lives
in `src/swing/analysis/scorer.py`, function `compute_score`. It's a clean,
simple pattern worth understanding fully:

1. First, `src/swing/analysis/signals.py`'s `detect_signals` runs hard
   pass/fail filters (price above 200-day EMA, minimum price, minimum
   average volume) — if any filter fails, the stock is thrown out
   entirely before scoring even starts.
2. Then it computes 5 independent factor scores, each normalized to a
   0–100 scale on its own terms:
   - **Signal count** (how many of 5 boolean technical signals fired,
     e.g. EMA bullish alignment, RSI oversold recovery — scored as
     `count/total * 100`)
   - **Risk/reward ratio** of the trade setup (scored against a "4.0 is
     perfect" ceiling)
   - **Volume** (today's volume vs. its moving average, scored against a
     surge-factor ceiling)
   - **Trend strength** (EMA20/50/200 stacking order, worth 33/33/34
     points for each pairwise condition met — literally hardcoded to sum
     to 100)
   - **RSI positioning** (a bell-curve-ish scoring: 40–60 RSI is "ideal"
     and scores 100, extreme oversold/overbought score lower, with a
     special case bumping overbought RSI back up to 100 if the trend is
     still strongly bullish)
3. Finally it combines them with fixed weights from `config.py`:
   `SCORE_WEIGHTS = {"signals": 0.30, "risk_reward": 0.25, "volume": 0.15,
   "trend": 0.15, "rsi": 0.15}` (they sum to exactly 1.0). So it's just
   `total = sum(factor_score * factor_weight for each factor)` — a plain
   weighted average, nothing fancier. No normalization tricks, no z-scores,
   just percentages times fixed weights.

The nice UX detail: every factor comes with a human-readable `reason`
string (e.g. `"RSI 45 — ideal swing zone (40–60)"`) stored right alongside
the score, so the breakdown is fully explainable without re-deriving it
later.

**What we can take or use:** This "explainable weighted score with a reason
string per factor" pattern would be a good addition to our
`dashboard/generate_dashboard.py` — right now our dashboard shows the
Judge's confidence number, but doesn't show a factor-by-factor breakdown of
*why*. We could add a small deterministic scoring table (in `data/` or a
new small module) that scores things like RSI positioning, trend alignment,
volume confirmation the same way, purely as an extra transparency panel on
the dashboard — separate from and not replacing the LLM Judge's reasoning.
Not urgent, but cheap to build since we already compute RSI/MACD/moving
averages in `data/`.

**Should we use the project directly, or just borrow an idea from it?**
Not applicable as a screener (we already pick one ticker at a time, we're
not screening a universe of stocks), but the weighted-factor-with-reasons
scoring pattern is a nice, cheap idea to reuse for dashboard transparency.
