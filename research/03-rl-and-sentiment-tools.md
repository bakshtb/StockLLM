# RL and Sentiment Tools — Hands-On Code Review

This is the third file in a three-part research series for StockLLM. The other two
cover LLM multi-agent projects (like TradingAgents and ai-hedge-fund) and
backtesting/screening tools. All three files document *hands-on* findings — we
actually cloned each project into a scratch folder, opened the real source files,
and read the code that matters, instead of repeating what the README claims. This
file specifically exists to answer one question: is a reinforcement-learning (RL)
"voice" — an agent that outputs its own buy/hold/sell opinion learned from trial
and error on historical data, as one more input alongside our Bull/Bear/Skeptic/Judge
agents — worth adding to StockLLM's pipeline? We already did a web-search-only pass
on this earlier and landed on "build it cautiously if at all." This file is the
follow-up where we actually opened the code to check whether that caution holds up.
Quick jargon note up front: a **reward function** is the formula that tells an RL
agent whether the thing it just did was good or bad (like a score after every move),
and the **action space** is the list of moves the agent is allowed to make (e.g.
buy, sell, hold).

## FinRL (⭐ 15,905)
**Link:** https://github.com/AI4Finance-Foundation/FinRL
**What it does:** A full research framework for training reinforcement-learning
trading agents. It gives you a pre-built "stock trading environment" (the
simulated world the agent trades in) and wires it up to standard RL algorithms
so you don't have to write the training loop yourself.

**What we found after actually reading the code:** We read
`finrl/meta/env_stock_trading/env_stocktrading.py`, the actual `StockTradingEnv`
class, top to bottom (about 570 lines).

- **State vector** (what the agent "sees" each step, built in `_initiate_state`/
  `_update_state`): `[cash balance] + [close price of each stock] + [number of
  shares currently held of each stock] + [technical indicators for each stock]`,
  all flattened into one long list of numbers. The default technical indicators,
  set in `finrl/config.py`, are `macd, boll_ub, boll_lb, rsi_30, cci_30, dx_30,
  close_30_sma, close_60_sma` — MACD, Bollinger bands, RSI, CCI, directional
  index, and two moving averages. That's a very similar indicator set to what
  StockLLM's `data/` layer already computes (we already have RSI, MACD, moving
  averages), which is reassuring — it means we wouldn't need new indicator code
  to feed an RL model, just to reshape what we already have.
- **Action space**: `spaces.Box(low=-1, high=1, shape=(stock_dim,))` — a
  *continuous* number between -1 and 1 for each stock, not discrete buy/sell/hold
  buttons. In `step()`, that number gets multiplied by `hmax` (a max-shares-per-trade
  cap) and truncated to a whole number of shares — positive means buy that many
  shares, negative means sell. So the agent is really learning "how many shares to
  buy or sell," and holding is just what happens when it lands near zero.
- **Reward** — literally line 360 of `env_stocktrading.py`:
  `self.reward = end_total_asset - begin_total_asset`, i.e. the raw dollar change
  in total portfolio value (cash + stock value) from before the trade to after it,
  then multiplied by a `reward_scaling` constant on the next line. It's about as
  simple as a reward function gets — no risk adjustment, no penalty for
  volatility, no Sharpe ratio built in (Sharpe is only computed afterward, for
  reporting, not fed back into learning).
- **Stable-Baselines3 wrapper**: `finrl/agents/stablebaselines3/models.py`
  defines a `DRLAgent` class. `get_model()` is a thin dictionary lookup
  (`MODELS = {"a2c": A2C, "ddpg": DDPG, "td3": TD3, "sac": SAC, "ppo": PPO}`) that
  just instantiates the Stable-Baselines3 class with default hyperparameters from
  `config.py`. `train_model()` is literally `model.learn(...)`. So yes, the
  tutorials aren't lying — calling `.get_model("ppo")` then `.train_model(...)`
  really is that shallow a wrapper. The real complexity FinRL hides isn't in this
  wrapper, it's in getting the environment/data setup right (turbulence
  thresholds, multi-stock ensembling in `DRLEnsembleAgent`, transaction cost
  modeling) — that part is genuinely intricate, 700+ lines just for the ensemble
  trainer.
- **Dependencies**: `requirements.txt` is large and pulls in things far beyond
  what you'd need to just use `StockTradingEnv` + Stable-Baselines3: `ray[default]`,
  `ray[tune]`, `TA-lib` (needs a separate system-level C library install),
  `selenium`, `wrds`, `sphinx`, `gputil`, `elegantrl`, `alpaca-py`. This is a
  research framework, not a lean library — installing the whole `finrl` package
  on a Raspberry Pi is a bad idea and would drag in a lot of dead weight.
- **Exporting a trained model for lightweight inference**: this is the good
  news. `DRLAgent.train_model()` returns a plain Stable-Baselines3 model object,
  and SB3 models support the standard `.save("model.zip")` / `Algo.load("model.zip")`
  pattern (we saw this used directly in `DRLEnsembleAgent.train_model`, which
  calls `model.save(...)`, and in `DRL_prediction_load_from_file`, which calls
  `MODELS[model_name].load(cwd)`). That means you do **not** need the `finrl`
  package installed at inference time — you only need `stable-baselines3` (which
  needs PyTorch) and `gymnasium` to load the `.zip` and call `model.predict(obs)`.
  You'd still need to hand-write ~50 lines to build the same state vector
  yourself (copying the relevant bits out of `_initiate_state`/`_update_state`),
  but that's very doable. The catch: PyTorch itself is still not a trivial
  install on a Pi (it works on ARM these days, but it's a few hundred MB and slow
  to install), so "lightweight" is relative — it's lightweight compared to
  training, not lightweight compared to, say, a scikit-learn model.

**What we can take or use:** We would not install the `finrl` pip package. But
the actual `StockTradingEnv` reward/state logic is short enough (~150 lines
excluding boilerplate) that if we ever build an RL agent, copying and adapting
that file directly — swapping in our existing RSI/MACD/moving-average
data instead of `stockstats` — is more practical than depending on the full
framework. Training would happen off-device (e.g. free Colab), and we'd only
ship the resulting SB3 `.zip` plus a small prediction script to the Pi.

**Should we use the project directly, or just borrow an idea from it?** Borrow
the environment design (state vector, action scaling, reward line) and the
SB3-save/load pattern — don't install the `finrl` package itself.

## TensorTrade (⭐ 6,611)
**Link:** https://github.com/tensortrade-org/tensortrade
**What it does:** Another RL trading framework, more modular than FinRL — it
splits a trading environment into swappable pieces (data feed, action scheme,
reward scheme, observer) that you mix and match instead of getting one
big fixed environment class.

**What we found after actually reading the code:** We read
`tensortrade/env/default/rewards.py` in full. There's a clean abstract base
class, `TensorTradeRewardScheme`, with one method you must implement:
`get_reward(self, portfolio) -> float`. Four ready-made reward schemes are
registered in a lookup dictionary (`_registry = {'simple': SimpleProfit,
'risk-adjusted': RiskAdjustedReturns, 'pbr': PBR, 'advanced-pbr': AdvancedPBR}`),
retrievable by name via `rewards.get('risk-adjusted')`:

- `SimpleProfit` — reward is just the percentage change in net worth over a
  sliding window (`net_worths[-1] / net_worths[-window] - 1.0`).
- `RiskAdjustedReturns` — same idea, but divides by volatility. It actually
  implements both **Sharpe ratio** (`mean(returns) / std(returns)`) and
  **Sortino ratio** (same idea but only penalizes downside volatility, not
  all volatility) as swappable sub-strategies, chosen with a string argument
  (`'sharpe'` or `'sortino'`).
- `PBR` (position-based returns) and `AdvancedPBR` (adds a trading-frequency
  penalty and a "hold bonus" for staying put during flat/uncertain markets) —
  both stream-based, showing how you'd combine multiple signals into one reward.

Compare this to FinRL: in FinRL, the reward is one hardcoded line
(`end_total_asset - begin_total_asset`) buried inside a 130-line `step()`
method — to change it, you'd edit FinRL's core environment file. In
TensorTrade, swapping `SimpleProfit` for `RiskAdjustedReturns` (or writing
your own risk-adjusted reward) is a one-line change (`reward_scheme='risk-adjusted'`)
because the reward logic is a genuinely separate, pluggable object. The
earlier research's claim that TensorTrade's design is cleaner for this specific
thing checks out — we saw it directly in the code, not just the docs.

One thing worth flagging: TensorTrade is a moving target under the hood. The
current version (last commit was recent, actively maintained) requires
**Python 3.12+** and pulls in `tensorflow>=2.15.1` as a hard dependency even
though most of its own tutorials use PyTorch-based RL libraries — that's an odd
mismatch and a heavier footprint than expected for something billed as modular.

**What we can take or use:** Not the framework itself (still heavy, still
assumes you build a full env/feed/broker setup). But the *pattern* — a small
abstract base class with one required method, plus a name-keyed registry
dict — is worth copying directly into any RL code we write ourselves. It would
let us start with `SimpleProfit`-style reward and swap to a Sharpe-based one
later without touching the environment code, which matters for the
"shadow-mode experiment" style of testing we're planning.

**Should we use the project directly, or just borrow an idea from it?** Borrow
the reward-scheme-as-pluggable-object design pattern; don't depend on the
package.

## gym-anytrading (⭐ 2,381)
**Link:** https://github.com/AminHP/gym-anytrading
**What it does:** A minimal "toy" RL trading environment built directly on top
of Gymnasium (the standard RL environment interface), meant for learning RL
basics on stock/forex data rather than for anything production-grade.

**What we found after actually reading the code:** We read
`gym_anytrading/envs/trading_env.py` and `stocks_env.py` in full — together
under 300 lines. Confirmed: `Actions` is a 2-value enum, `Sell = 0` and
`Buy = 1` — there is no explicit "Hold" action. Positions (`Short`/`Long`) persist
between steps; if the agent's action matches its current position (e.g. it
says "Buy" while already Long), nothing happens — that's the de facto hold.
The README actually explains this design choice directly, and it's worth
quoting because it's a real design opinion, not an oversight: *"after months
of work, I finally found out that these actions just make things complicated
with no real positive impact... an action like Hold will be barely used by a
well-trained agent because it doesn't want to miss a single penny. Therefore
there is no need to have such numerous actions and only Sell=0 and Buy=1
actions are adequate."* The reward function (`_calculate_reward` in
`stocks_env.py`) is also dead simple: it only pays out a reward when a trade
that closes a Long position happens, and the reward is just the raw price
difference between the entry and exit price — no percentage, no position
sizing, no cash tracking beyond a simple running "total profit" multiplier.

Last commit was August 2023, confirming this project is stale — no bug fixes
or updates since. The README itself even points newer users toward a more
complete fork (`DI-engine`'s version) for anything beyond learning basics.

**What we can take or use:** Nothing for production, but it's a genuinely good
learning example if anyone on this project wants to understand what a minimal
RL trading loop looks like before touching FinRL's much bigger surface area —
the whole environment fits in your head. We do NOT think this reflects a
sensible action space for a real "advisory" RL agent — a "no explicit hold"
design makes sense for *always-long-or-short* strategies (forex, futures) but
is a poor fit for our use case, where "don't trade this ticker right now" is a
completely valid and common opinion.

**Should we use the project directly, or just borrow an idea from it?** Neither,
really — it's a teaching toy. Confirmed framing: fine for learning, not a
starting point for anything we'd ship.

## finBERT (⭐ 2,201)
**Link:** https://github.com/ProsusAI/finBERT
**What it does:** A version of the BERT language model that's been fine-tuned
specifically on financial text, so it can label a sentence as positive,
negative, or neutral about a stock/company — a free, offline alternative to
asking an LLM to judge sentiment.

**What we found after actually reading the code:** The repo's own code
(`scripts/predict.py`) is old — it uses `AutoModelForSequenceClassification.from_pretrained(args.model_path, ...)`
from Hugging Face's `transformers` library, pointed at a *local* model
directory, and the README says it still relies on `pytorch_pretrained_bert`,
an early ancestor of today's `transformers` library, for training/fine-tuning.
The repo hasn't been touched since February 2022 and its own training code is
genuinely stale.

But — and this is the important distinction the task asked us to check — the
**pretrained weights are separate from the repo's training code**, and they've
held up fine. We fetched the model's page on Hugging Face Hub
(`https://huggingface.co/ProsusAI/finbert`, exact model ID `ProsusAI/finbert`)
directly: it shows about **5.7 million downloads in the last month alone**, and
its model card demonstrates the modern, simple usage pattern:
```python
from transformers import pipeline
pipe = pipeline("text-classification", model="ProsusAI/finbert")
```
That's it — three lines, no need to touch the old repo's code at all. The
model card doesn't spell out exact hardware requirements, but a `pipeline()`
call like this defaults to CPU when no GPU is present, and finBERT is a
BERT-base-sized model (~110 million parameters, roughly 400-440 MB on disk for
the full precision weights) — squarely in "runs fine on CPU, a few hundred ms
per short snippet" territory, not something that needs a GPU. That fits a
Pi-class box for *inference*, especially at StockLLM's scale (a handful of
headlines/StockTwits posts per run, not a firehose).

**What we can take or use:** Skip the GitHub repo entirely — clone nothing, use
`pip install transformers torch` and `pipeline("text-classification",
model="ProsusAI/finbert")` directly against Hugging Face Hub. This could be a
free, local, no-API-cost supplement or cross-check for StockLLM's sentiment
reads (e.g. running finBERT over the news headlines and StockTwits captions we
already pull, right alongside our LLM-based reads, for comparison rather than
replacement).

**Should we use the project directly, or just borrow an idea from it?** Use the
downloadable model directly via `transformers` — it's a legitimately usable,
free, offline tool today; just ignore the repo's own (stale) training code.

## wsbtickerbot (⭐ 134)
**Link:** https://github.com/RyanElliott10/wsbtickerbot
**What it does:** An old bot that scanned r/wallstreetbets posts and comments,
counted how often each stock ticker was mentioned, ran basic sentiment
scoring on the surrounding text, and posted a daily "top tickers" leaderboard
back to the subreddit.

**What we found (quick look):** `wsbtickerbot.py` uses `praw` (Python Reddit
API Wrapper) to log into Reddit and pull posts/comments, then a mix of
regex (`extract_ticker`) to catch `$TICKER`-style mentions and a plain
all-caps-word scan (with a hardcoded blacklist of common all-caps words like
"CEO", "LOL", "USA" to cut down false positives) for bare-word mentions. To
confirm a matched word is really a stock ticker (not just some acronym), it
calls out to the IEX Cloud API via the `iexfinance` library on every
candidate word. Sentiment is scored with a bundled, hand-modified copy of
VADER (a rule-based, non-ML English sentiment tool — not finBERT, nothing
finance-specific). Last commit: October 2018.

Two separate problems make this code non-runnable today, not just "outdated":
(1) **IEX Cloud itself shut down entirely on August 31, 2024** — the
`iexfinance` library it depends on for ticker validation has no backend left
to call, full stop, regardless of Reddit access. (2) Reddit's API access
changed in 2023 (see below) — PRAW itself still works, but you now need to
register an app and stay under stricter rate limits.

**What we can take or use:** The regex-plus-blacklist approach to spotting
ticker mentions in free text is still basically sound and is the same
technique modern tools use — nothing about that part has aged badly. But the
IEX ticker-validation step would need replacing (e.g. against a static list of
known tickers, same as `wsbtrends` below does) and the sentiment scoring
would be a good place to actually plug in finBERT instead of VADER, given what
we found in the previous section.

**Should we use the project directly, or just borrow an idea from it?** Borrow
the ticker-spotting regex idea only — the code as a whole won't run without a
real rewrite (dead data dependency, old Reddit auth flow).

## wsbtrends (⭐ 5)
**Link:** https://github.com/wbollock/wsbtrends
**What it does:** A smaller, similar WallStreetBets ticker-mention tracker
that logs counts into a MongoDB database over time, meant to show mention
trends rather than a one-off daily snapshot.

**What we found (quick look):** Also uses `praw`. Its ticker-matching approach
is actually a bit more sound than wsbtickerbot's: it uses a straightforward
regex for 3-5 letter all-caps words (`\b[A-Z]{3,5}\b`), subtracts the same
blacklist of common acronyms (openly credited/copied from wsbtickerbot's
code), and then validates matches against a **local pre-downloaded text file
of real NYSE tickers** (`stocks/NYSE.txt`) instead of calling any external
API. That's a meaningfully better design choice for a hobby project — no
dependency on a live validation API that can disappear (like IEX Cloud did).
Last commit: February 2021, so also unmaintained, but the core logic doesn't
depend on anything that's since died the way wsbtickerbot's does — it would
mostly still run today (its `pymongo`/MongoDB dependency is the main thing
we'd swap out, easy to replace with SQLite given StockLLM already uses
SQLite for storage).

**What we can take or use:** The "match against a static local ticker list
instead of an external API" idea is the one worth keeping — it's simpler,
free, and has no external service that can shut down on us.

**Should we use the project directly, or just borrow an idea from it?** Borrow
the local-ticker-list validation idea; the code itself is too small/dated to
use wholesale but wouldn't need much rework.

## A note on Reddit access for both WSB tools

We checked Reddit's current API terms since this affects whether "add Reddit
sentiment" is realistically still a free option. Reddit started charging for
API access in April 2023 after a well-publicized dispute with third-party app
developers, but **a free tier still exists for small, non-commercial,
personal-use projects** — roughly 100 requests/minute (some sources report a
practical ~60/minute working limit through PRAW) once you register a free
Reddit developer app. Paid commercial tiers exist too ($0.24 per 1,000 calls,
or enterprise contracts) but a solo hobby project like StockLLM checking
mention counts for one ticker at a time would stay well within the free
tier. So: PRAW itself still works and is still free for our use case — the
two bots above are broken for other reasons (dead IEX dependency, old auth
code, stale MongoDB setup), not because Reddit locked hobbyists out entirely.

## Overall RL verdict after actually looking at the code

Reading the real source code mostly **confirms** our earlier cautious
recommendation, and sharpens it in one useful way. FinRL's actual
`StockTradingEnv` is simpler under the hood than its polished tutorials
suggest — state vector, action scaling, and reward are all straightforward
once you strip away the framework packaging — but the *packaging itself*
(the `finrl` pip install, with `ray`, `TA-lib`, `selenium`, `wrds`, and friends)
is genuinely unfit for a Pi and not something we'd want to depend on even for
occasional use. The good news we didn't fully appreciate before opening the
code: a trained Stable-Baselines3 model saves down to a portable `.zip` file
that only needs `stable-baselines3` + `gymnasium` (no `finrl` package) to load
and run predictions, which makes the "train off-device on Colab, run
inference on the Pi" plan realistic — assuming we're willing to install
PyTorch on the Pi, which is still a heavier ask than anything else in
StockLLM's current stack. TensorTrade's reward-scheme pattern is worth
stealing as a *design idea* regardless of whether we ever touch RL, since a
pluggable, swappable scoring function is generally good practice. None of
this changes the bottom line: gradient boosting is still the right first
move — it's dramatically lighter to train and run, doesn't need a simulated
trading environment to get right, and doesn't carry PyTorch as a Pi-side
dependency. If we do eventually add an RL "voice," it should be a
shadow-mode experiment (logged but not shown/trusted) built by copying the
~150 lines of actual environment logic we now understand from FinRL — not by
installing the framework — and it should almost certainly happen after
gradient boosting has proven whether a simpler model can already do the job.
