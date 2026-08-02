# Changelog

## 0.8.3

- Fix: HA Supervisor logged a warning on every add-on update/restart --
  "App StockLLM did not handle SIGTERM ... exit code 143" -- because
  Flask's `app.run()` is a development server with no signal handling of
  its own, so Supervisor's stop request killed it via Python's default
  SIGTERM disposition instead of a clean shutdown. Switched to waitress
  (a small pure-Python production WSGI server -- no new process-
  supervision layer, still one plain process) and added an explicit
  SIGTERM handler that exits 0. Verified live: sending SIGTERM to the
  running process now exits 0 immediately instead of being killed with
  code 143.

## 0.8.2

- Fix two real mobile bugs found from iPhone screenshots:
  - **Illegible chart text.** Every chart shares one fixed 620-unit-wide
    SVG viewBox; `width: 100%` scaled that down to fit a ~300px mobile
    card, which shrank every label/value proportionally along with the
    geometry -- 10.5-12px authored text was rendering at roughly 5-6px on
    a phone, confirmed by measuring actual rendered SVG width (scale
    0.485) in a headless browser. Charts now stay pinned to their native
    size on mobile and scroll horizontally within their own card instead
    (same trade-off already made for wide tables) -- verified the fix
    brings the render scale back to 1.0 with zero page-level overflow.
  - **The whole page could be dragged sideways**, revealing clipped
    content. A desktop/Chromium layout check shows zero page overflow at
    every phone width tested, which points at iOS Safari's known
    subpixel-rounding quirk: overflow invisible to Chromium's rounding
    can still be nonzero under WebKit's, and any nonzero page overflow
    lets iOS elastically drag the *entire* page. Added the standard
    safety net, `overflow-x: hidden` on html/body -- every intentional
    inner scroll region (tables, the section nav, now charts too) already
    sets its own `overflow-x`, so this doesn't clip anything real.

## 0.8.1

- Fix a real chart-form problem in "Price & Technicals," found from a
  screenshot: 52w Low/High, MA200/MA50/MA20, and Current all sit within
  a narrow band relative to their own price (e.g. $201-$340), so a
  zero-anchored bar chart rendered all six as near-identical-length bars
  -- the actual relative positions (is price above or below its moving
  averages? where in the 52-week range?) were nearly impossible to read
  at a glance. Replaced with `range_position_plot`, a dot plot on one
  shared axis (same visual language as the existing analyst-target-range
  meter): a track from 52w low to high, dots for each moving average,
  and a distinct triangle marker for the current price. Includes
  collision-avoiding label stagger for moving averages that land only a
  few cents/dollars apart.

## 0.8.0

- Dashboard UX/UI redesign, mobile-first. Four changes:
  - **Mobile-safe tables**: every table cell now carries a `data-label`
    attribute; on phones, tables render as stacked "label: value" cards
    instead of a cramped table (previously the worst offender was the
    `.split-2col` sections -- two dense tables side by side that became
    unreadable once squeezed onto an iPhone). Pure CSS, no JS.
  - **Analyst recommendation trend is now a chart, not a bare table**:
    Strong Sell/Sell/Hold/Buy/Strong Buy per period is an ordered-scale
    share, which the dataviz skill's guidance calls for as a diverging
    stacked bar centered on neutral -- generalized the existing sentiment
    chart (`diverging_stacked_sentiment`) into `diverging_stacked_ordinal`,
    which supports any number of segments per side (graduated opacity,
    not new hues, keeps it colorblind-safe) and renders one small-multiple
    bar per period, most recent first. Raw numbers stay one click away via
    the existing table-view toggle.
  - **Hero block**: ticker's current price now renders at true hero size
    right under the top bar, with its 20-day move and the AI
    recommendation badge (when a full run was made) -- one clear focal
    point before any scrolling, instead of the price being just one of
    seven equal-weight KPI tiles.
  - **Mobile section-jump nav**: a sticky pill bar under the top bar links
    to each of the 8 major sections, so a phone reader can jump directly
    instead of scrolling through the whole page.
  - Color system, chart forms, and section function signatures are
    unchanged -- this was a presentation-layer pass, not a data-layer one.
  - Added test coverage for all of the above (`tests/test_charts.py`,
    `tests/test_dashboard_build.py`): the new chart function's empty/
    lopsided/end-label-sum cases, hero block presence and rec-badge
    wiring, nav anchors resolving to real section ids, and data-label
    presence on every table cell across every committed fixture.

## 0.7.1

- Fix a real bug: insider transactions were labeled "buy" based only on
  whether an insider's holdings went up, which conflated real open-market
  purchases (their own cash, a genuine confidence signal) with routine
  stock grants/awards and option exercises (compensation, not a purchase
  decision). Found live on real data -- a CEO's scheduled RSU vesting
  (millions of shares, no price) was showing on the dashboard as "insiders
  have been buying... a vote of confidence," which wasn't true.
  `data/fetch_insider.py` now reads SEC's actual transaction-reason code
  (previously parsed but silently discarded) and adds `transaction_code`,
  `transaction_nature`, and `is_open_market`. The dashboard's "At a Glance"
  insider-buying claim and the transactions table now only treat genuine
  open-market purchases as a confidence signal.

## 0.7.0

- Decouple the filings digest's reading budget from what actually lands in
  the shared bundle every reasoning agent sees. Previously one 15,000-char
  cap applied to both -- meaning the one-time digest step could never read
  more of a filing than the 6 expensive reasoning agents also had to pay to
  see. Now: `MAX_FILING_CHARS` (15,000, unchanged) still caps what's stored
  in `filings_raw`; a new `MAX_FILING_CHARS_FOR_DIGEST` (60,000) is a
  separate, much larger window only the digest step reads, discarded before
  the bundle is assembled.
- Move the filings digest from Gemini Flash to Qwen3.7-Plus to make that
  bigger window affordable: reading 4x more of the actual document now
  costs *less* than the old smaller Gemini call did (Qwen's per-token price
  is roughly 4.7x cheaper). News digest stays on Gemini Flash.
- Each filing is still fetched from EDGAR exactly once -- both windows are
  derived from that same fetch, not two network calls.

## 0.6.3

- Set default values for `finnhub_api_key`, `fred_api_key`, and
  `fmp_api_key` in `config.yaml` so new installs don't need to re-enter
  them manually. Repo is private as of this version -- done at the
  user's explicit request after being informed this only belongs in a
  private repo (defaults here are visible to anyone with repo read
  access).

## 0.6.2

- Fix: the AI Recommendation dashboard section never actually displayed
  the independent second Skeptic (Qwen) or the Quant Checker's output --
  both were fully wired into the pipeline and into Judge's reasoning, but
  the dashboard template itself was never updated to show them. Now shows
  both skeptic reviews side by side (and calls out when they flag the
  same claim, a stronger signal than either alone), plus any numeric
  claims the Quant Checker flagged as not checking out against the
  bundle's own figures.

## 0.6.1

- Fix: FMP's DCF and PEG endpoints returned 403 Forbidden against a real
  key -- their `/api/v3/...` paths are dead, not just legacy. Switched to
  `/stable/...`, and picked up the PEG field's new name
  (`priceToEarningsGrowthRatioTTM`, was `pegRatioTTM`). Found and fixed by
  testing live against a real FMP key.
- Fix: FRED's CPI year-over-year calculation used a fixed list position to
  find "12 months ago," which silently misaligned by a month when
  CPIAUCSL had a one-off missing observation (a government-shutdown-
  delayed release). Now matches by actual date instead of list position.
  Found and fixed by testing live against a real FRED key.

## 0.6.0

- Add three optional data sources, each free-tier and each degrading
  gracefully (null fields + a note, never a crash) if its key isn't set:
  - **FRED** (free forever, no paid tier) -- adds CPI inflation, unemployment
    rate, fed funds rate, and the 10y-2y yield curve spread to
    `macro_context`.
  - **Financial Modeling Prep** (free tier, 250 calls/day) -- new
    `fmp_valuation` section: a DCF fair-value estimate (a second,
    independent valuation anchor Bull/Bear/Judge's fair-value estimate now
    cites alongside analyst targets) and a PEG ratio.
  - **Finnhub** (same key already used for news) -- new `finnhub_signals`
    section: Insider Sentiment (MSPR) and analyst Recommendation Trend.
  New optional config: `FRED_API_KEY`, `FMP_API_KEY` (`.env.example`, add-on
  Configuration tab). Dashboard shows all three when present, hides them
  cleanly when not.

## 0.5.0

- Add outcome tracking: every full (non-dry-run) check now records the
  stock's price on the day of the call. A new `python main.py performance`
  command checks the price again for any call now 7 or 30 days old (free --
  one yfinance lookup, no LLM calls) and prints a track record: what was
  called, what actually happened, and a win rate for buy/sell calls (hold
  isn't scored win/loss, since it makes no directional claim). This is the
  first real step toward measuring whether the system's calls are actually
  good, instead of just plausible-sounding.
- Uses the `outcomes` table that's existed in the schema since the first
  commit but was never wired up until now.

## 0.4.0

- Add a fair-value range to the AI recommendation, alongside the existing
  buy/sell/hold call. Bull and Bear each estimate what the stock would be
  worth if their case is right (grounded in the bundle's own analyst
  targets and sector valuation, not invented); Judge weighs both into a
  final low/high range for today -- deliberately not a forecast of a
  future price, since that's a different (and much less reliable) claim
  than "what is this business worth right now." Shown on the dashboard
  using the same range-meter chart already used for analyst price
  targets, so the AI's own range and the analysts' range are visually
  comparable.

## 0.3.0

- Move Bull, Bear, and both digest steps (news + filings) from Claude to
  Gemini, picked per-role from benchmarks matched to each role's actual job
  rather than using one provider everywhere: Bull/Bear need strict grounding
  (best faithfulness/calibration benchmarks), digests need faithful
  extraction with no reasoning (best summarization-faithfulness benchmark,
  and the cheapest/fastest tier). Skeptic (original) stays on Claude Sonnet
  (best LLM-as-judge/critique benchmark) and Judge stays on Claude Opus
  (best confidence-calibration benchmark) -- see config.py for the reasoning
  behind each pick.
- New shared `agents/compat_client.py` for any OpenAI-compatible provider
  (used by both Qwen and Gemini) -- `agents/qwen_client.py` and the new
  `agents/gemini_client.py` are now thin wrappers around it.
- Fix: digest cost logging (webapp and CLI) hardcoded "claude-haiku..." as
  the model name regardless of what actually ran -- harmless before since
  digests really were on Haiku, but would have mislabeled every digest call
  in the database once digests moved providers. Now logs the real model.
- New required config for a full (non-dry-run) check: `GEMINI_API_KEY`
  (`.env.example`, and the add-on's Configuration tab), alongside the
  existing `ANTHROPIC_API_KEY` and `QWEN_API_KEY`. Dry runs are unaffected.

## 0.2.0

- Add two new agents on Qwen (Alibaba Cloud Model Studio, OpenAI-compatible
  API): an independent second-opinion Skeptic (same task/schema as the
  existing Claude Skeptic, run on a different model so it can catch blind
  spots the first one shares with itself) and a Quant Checker (verifies
  every specific number/percentage/ratio claimed by Bull/Bear against the
  bundle's raw figures). The full pipeline is now 6 agent calls instead of
  4: Bull, Bear, Skeptic (Claude), Skeptic (Qwen), Quant Checker, Judge.
- Judge's prompt (`agents/prompts/judge.md`) now explicitly weighs both
  skeptic reviews (agreement = stronger signal, disagreement = noted
  explicitly) and discounts any claim the quant checker flagged, rather
  than just receiving the extra JSON as decoration.
- New required config for a full (non-dry-run) check: `QWEN_API_KEY`
  (`.env.example`, and the add-on's Configuration tab). Dry runs are
  unaffected. `qwen_api_key` added to `config.yaml`'s options/schema.

## 0.1.4

- Add a pytest test suite (`tests/`) covering formatting, chart SVG
  generation, dashboard assembly, the agent JSON parser, webapp routes
  (including the Ingress path-prefix and ticker-validation security
  boundary), the CLI's output-path resolution, config, and storage --
  wired into a new CI workflow (`.github/workflows/tests.yml`) that runs
  on every push/PR. Live-API tests (yfinance/SEC EDGAR/StockTwits) are
  marked `@pytest.mark.live` and excluded from CI by default.
- Fix: `diverging_bar_horizontal`'s empty-input case returned a 2-tuple
  instead of the 3-tuple every other chart function returns, found while
  writing its test. Never triggered in production (its one call site
  already guards against empty input), but would crash on direct use.

## 0.1.3

- Fix: the longest bar in a chart (e.g. 52-week high) still ran off the
  phone screen after 0.1.2's fix -- a CSS Grid "min-width: auto" quirk
  meant the SVG's explicit width attribute (added in 0.1.2) set a hard
  620px floor on its card's grid track, overriding the responsive CSS.
  Fixed with min-width: 0 on every grid-item class on the page.

## 0.1.2

- Fix: individual charts still overflowed the phone viewport after 0.1.1's
  page-layout fix -- the SVG charts had no explicit width/height attributes,
  which some mobile Safari versions need (alongside viewBox) to reliably
  apply responsive CSS scaling. Found via a follow-up phone screenshot.

## 0.1.1

- Fix: Ingress path handling. The form, redirects, and "recent runs" links
  used root-relative URLs, so submitting a ticker under real Ingress went
  straight past the add-on instead of back into it (blank page, nothing in
  the log). Found on the first real install.
- Fix: dashboard page overflowed the viewport on phones (a 460px column
  floor on the section grid, plus several inline fixed-column layouts that
  couldn't respond to screen width). Added mobile breakpoints.
- Docs updated for a public repo (no Personal Access Token needed).

## 0.1.0

- Initial Home Assistant add-on release: web UI (ticker + dry-run toggle),
  Ingress panel, dashboard output, AI recommendation section for full runs.
