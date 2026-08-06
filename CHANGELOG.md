# Changelog

## 0.9.37

- Fix: no favicon was showing at all -- only `apple-touch-icon` (iOS
  home-screen bookmarks) was declared, never a real `<link rel="icon">`,
  so browsers fell back to requesting `/favicon.ico`, which doesn't
  exist. Added a proper favicon link (reusing the existing
  `assets/icon.png`) to both the webapp form pages and every generated
  dashboard. See HANDOFF.md item 60.

## 0.9.36

- Fix: a phantom horizontal scrollbar under the RSI gauge (and
  potentially any other chart/trend-line, same rule) with nothing to
  actually scroll to -- a "defensive" `overflow-x: auto` meant to catch
  charts wider than their card, but every chart is already `width: 100%`
  of its container so none should ever legitimately overflow. Changed to
  `overflow-x: hidden`, which keeps the same defensive intent without
  ever surfacing a scrollbar. See HANDOFF.md item 59.

## 0.9.35

- Remove: the chart's visible date-range slider (the horizontal bar with
  draggable handles below the x-axis) -- user request. Wheel/pinch zoom
  still works, just with no persistent widget for it.
- Add: the range buttons (1M/3M/6M/1Y/2Y/All) now show the % price
  change over their own window -- computed with the same index math the
  buttons' own zoom action uses, so the number always matches what's
  actually on screen after clicking. See HANDOFF.md item 58.

## 0.9.34

- Change: the price chart is now always visible above the tab bar
  (was buried inside the "Price & Technicals" tab), and simplified to
  just the price line + gradient fill (dropped the MA20/50/200 overlay
  and volume subplot) -- user request, matching a phone stock app
  reference. MA values are still shown elsewhere (the "Price vs. moving
  averages" plot); volume trend is still stated as text.
- Fix: a real bug found while verifying the above, not assumed from the
  diff -- the chart's container was silently rendering a *different*
  chart's data due to an id collision (a chart-registering function was
  being called after the id counter had already been reset), while still
  reporting as successfully hydrated. See HANDOFF.md item 57 for the
  full mechanism.

## 0.9.33

- Remove: the "Data Quality Notes" dashboard section, per user request.
  The separate "Data Quality Notes" section in the "Download for AI
  Chat" Markdown export is a different feature and untouched, as is the
  underlying data itself. See HANDOFF.md item 56.

## 0.9.32

- Fix: the KPI row and At a Glance panel were pinned above the tab bar,
  so they stayed visible no matter which tab was open -- read exactly
  like "the same content repeats on every tab" even though nothing was
  technically duplicated. Moved both into the Price & Technicals tab
  itself (the default/first one); every other tab now shows only its
  own content. See HANDOFF.md item 55.

## 0.9.31

- Add: replaced the app icon (`dashboard/assets/icon.png`, the
  `apple-touch-icon` used across the dashboard and webapp) with the
  user's own ADELE logo -- cropped and resized programmatically from the
  supplied artwork to a clean 180x180 icon. Not to be confused with the
  per-ticker company logo (0.9.30's logo.dev integration), a different
  thing entirely. See HANDOFF.md item 54.

## 0.9.30

- Change: company logo switched from Google's favicon service to
  logo.dev (user's preference) -- ticker-native (no more domain-guessing
  from yfinance's `website` field) and genuinely theme-aware, matching
  the dashboard's own light/dark toggle instead of one static image.
  Confirmed logo.dev returns a clean auto-generated placeholder for an
  unknown ticker rather than a broken image, so the local fallback badge
  now only covers a real network failure. Uses a hardcoded API token, an
  informed choice the user made after being told this repo is public.
  See HANDOFF.md item 53.

## 0.9.29

- Change: renamed the app's display branding from "StockLLM" to "ADELE"
  (Agent-Driven Evaluation LLM Engine) across the dashboard and webapp UI
  -- page titles, the footer disclaimer, the AI Recommendation tooltip,
  the Markdown export, both form pages, and `config.yaml`'s display
  name. The add-on's technical slug, the GitHub repo, and the on-disk
  folder name are unchanged (the user is pointing a new domain at the
  existing instance himself). See HANDOFF.md item 52.

## 0.9.28

- Fix: the company logo used Clearbit's free logo API, which the user
  caught was discontinued December 1, 2025 -- not a DNS blocklist as
  speculated in 0.9.27, the service is simply gone. Replaced with
  Google's public favicon service (`google.com/s2/favicons`), also free
  and keyless -- also checked logo.dev (the user's suggestion), but its
  real API requires an account + token, not actually keyless. Same
  graceful fallback to an initial-letter badge either way. See
  HANDOFF.md item 51.

## 0.9.27

- Add: a back-to-search button in the header; a real company logo (via
  Clearbit's free logo API, with a graceful initial-letter fallback if
  there's no website on file or the logo can't load); a humanized,
  absolute "Aug 5, 2026 · 6:14 PM UTC" timestamp instead of a raw
  ISO8601 string; the redundant disclaimer text dropped from the header
  (the footer already has a fuller one).
- Fix: the top KPI row now fits on one line on desktop (was wrapping its
  7th tile onto a lonely second row).
- Change: the long single-page scroll of ~9 section cards is now
  page-level tabs (Price & Technicals, Analyst, Backtests, Performance,
  Financials, Ownership, Dividends & More, News, Filings) -- the same
  tab component already used inside Ownership/Dividends & More, applied
  one level up. Caught and fixed a real bug in the underlying component
  while verifying: clicking a tab highlighted the button but didn't
  switch the content, because the JS found panels via DOM adjacency,
  which broke once the tab bar needed to live in the sticky header
  separately from its panels.
- Note: the new company logo is the one external network call this
  otherwise self-contained dashboard makes. Verified it degrades cleanly
  to an initial-letter badge if unavailable -- discovered live that this
  environment's own DNS won't resolve Clearbit's domain specifically
  (unrelated domains resolve fine), plausibly consistent with a
  DNS-level ad/tracker blocklist (common on home networks/Pi-hole
  setups). Real logos may not load depending on your own network. See
  HANDOFF.md item 50.

## 0.9.26

- Fix: 3 real accessibility/UX issues found via an ad-hoc audit against
  Vercel's public Web Interface Guidelines checklist -- keyboard focus was
  being suppressed (`outline: none` with no replacement) on section-nav
  links and the "i" info-icons, now a real focus-visible ring; the login
  password field and ticker field both had `autofocus`, popping the
  on-screen keyboard the instant either page loads on mobile, now
  removed; the Run button's "Running..." used literal dots instead of
  the real ellipsis used everywhere else in the same file. See
  HANDOFF.md item 49.

## 0.9.25

- Change: page order is now KPI row, then the price chart, then At a
  Glance (was KPI, At a Glance, then chart). The price chart's area fill
  is now a real theme-aware gradient (was flat opacity), with a filled
  dot marking the latest close, and the range tabs (1M/3M/.../All) lost
  their resting border for a more minimalist look -- matched against a
  Google Finance screenshot the user sent as the visual target. See
  HANDOFF.md item 48.

## 0.9.24

- Change: page order is now hero price, KPI row, At a Glance, then a
  full-width Price & Technicals (was: hero, At a Glance, KPI row, then a
  half-width Price & Technicals sharing a row with empty space). Also
  replaced the price chart's candlesticks with a colored area line
  (green/red by net change), keeping the MA20/50/200 overlays, volume,
  zoom, and crosshair tooltip unchanged -- user request. See HANDOFF.md
  item 47.

## 0.9.23

- Fix: real regression from 0.9.22's KPI-tile flattening -- on mobile,
  every `.kpi-row` collapses to a single column, and with no border/
  shadow left on `.stat-tile`, six stacked stats ran together into one
  unbroken block of text (caught by the user on the live site, a phone
  screenshot of stocks.baksht.org). Added a bottom-only divider, the
  same convention already used by `.news-item`/`.filing-row` elsewhere
  on the page -- stays flat, restores clear separation. See HANDOFF.md
  item 46.

## 0.9.22

- Add: UI/UX overhaul Phase 3 -- redesigned against a real screenshot
  comparison with Google Finance (captured its Overview/Analysis/Earnings/
  Financials/Holdings tabs for a live AAPL quote). The actual gap turned
  out to be chrome density, not data usage or chart sophistication (both
  already ahead of Google's on this dashboard): flattened every `.stat-
  tile` to bare typography (no border/shadow) to match Google's borderless
  KPI rows, added a reusable segmented pill sub-tabs component to split
  the Ownership and Dividends/Buybacks/Options/Sentiment sections out of
  a dense 2-column wall into focused views, and switched News to a
  2-column grid. All client-side/CSS, no backend or data changes -- see
  HANDOFF.md item 45.

## 0.9.21

- Add: UI/UX overhaul Phase 2 -- `/run` no longer blocks the request for
  the whole research pipeline (data fetch, backtests, and the sequential
  AI recommendation calls). It now returns almost immediately and
  redirects to a `/progress/<job_id>` page that polls a JSON status
  endpoint and shows real, non-fabricated pipeline stages (via a
  background thread + in-memory job registry) using the Phase 1 shimmer
  skeleton to sketch the eventual dashboard layout. See HANDOFF.md item
  44 for the full breakdown, including two real bugs found and fixed
  while verifying (a test-isolation bug from re-importing `threading`,
  and an unstyled progress page caused by a relative asset path at an
  extra URL depth).

## 0.9.20

- Add: UI/UX overhaul Phase 1 -- CSS/JS moved out of Python string
  constants into a real `webui/` Vite project (multi-stage Dockerfile,
  Node only in a throwaway build stage, no Node in the shipped image), plus
  a Material Design visual layer: card elevation, a dependency-free ripple
  effect, a chart-loading shimmer skeleton, and a restyled "Download for AI
  Chat" button. No section markup or dashboard behavior changed -- see
  HANDOFF.md item 43 for the full breakdown, including two real bugs found
  and fixed while verifying (an invalid CSS selector that broke the new
  build, and a pre-existing missing import in the CLI's `main()`).

## 0.9.19

- Add: `CLAUDE.md` behavioral guidelines (from multica-ai/andrej-karpathy-
  skills, MIT) -- think before coding, simplicity first, surgical changes,
  goal-driven execution. Documentation only, no functional changes --
  version bumped solely to satisfy this repo's pre-commit/CI convention.

## 0.9.18

- Fix: real, user-reported data accuracy bugs on MBLY -- dashboard showed
  $7.94/$2.04B while the real numbers were $8.08/$6.87B. Current price now
  prefers a live quote (yfinance's `fast_info`) over `.history()`'s last
  daily bar, which can lag by up to a session -- fixed in both
  `data/fetch_prices.py` and a second, independent copy of the same bug in
  `backtest/engine.py`. Market cap was silently understated ~3.4x for
  Mobileye specifically because it has a dual-class share structure
  (252M publicly-traded Class A, 598M Class B held entirely by Intel and
  never traded) that yfinance's own fields don't account for -- new
  `data/fetch_shares_outstanding.py` reads the real total from the actual
  10-Q/10-K balance sheet on SEC EDGAR and corrects market cap when a
  genuine multi-class structure is found, with a data-quality note
  explaining the correction. See HANDOFF.md item 42.

## 0.9.17

- Add: a "Download for AI Chat" button on the dashboard, exporting the
  entire bundle as a Markdown file with instructions for a free LLM chat
  (Claude.ai, ChatGPT, etc.) to follow -- the same grounding rules
  (only use facts in the document, not training-data knowledge) and
  bull/bear/fair-value structure our own paid agents use, condensed into
  one instructions block. Since a dry run is free and the full AI pipeline
  costs a little, this lets someone get an equivalent independent analysis
  for free via a chat UI instead. Deliberately excludes StockLLM's own AI
  Recommendation, to keep the outside read genuinely independent. See
  HANDOFF.md item 41 for several real field-name bugs caught and fixed
  during manual review before this shipped.

## 0.9.16

- Add: a real, interactive price chart to the Price & Technicals section --
  candlesticks, a volume panel, MA20/50/200 overlay lines, a crosshair
  tooltip, drag-to-zoom (mouse wheel/pinch + a slider), and 1M/3M/6M/1Y/2Y/
  All range-preset buttons. The section previously had no historical price
  chart at all, only single-point stats. Reuses the same price history
  already fetched once for the Strategy Backtests section -- no second
  download. Verified in a standalone headless-chromium harness against the
  real vendored ECharts library before wiring in, then re-verified against
  the actual generated dashboard end-to-end. See HANDOFF.md item 40.

## 0.9.15

- Update: add an "i" info tooltip to the Win Rate stat in each Strategy
  Backtests card, explaining in plain English what it means and -- since a
  low win rate doesn't automatically mean a bad strategy (a trend-following
  rule can lose most of its trades and still come out far ahead on the rare
  big winners) -- explicitly pointing readers to check Return alongside it
  rather than judging a strategy on win rate alone.

## 0.9.14

- Update: Strategy Backtests UI polish. Each strategy now sits in its own
  clearly-bordered card (recessed against the section background, matching
  the same visual treatment already used for mobile table rows) instead of
  a bare list. The 4-number stat row (Return/Buy & Hold/Win Rate/Trades)
  now stays a fixed 2-column grid at every screen width -- previously it
  collapsed to 1 column on narrow phones, stacking 4 short numbers
  full-width each and wasting vertical space. Return and Buy & Hold are now
  color-coded (green/red by sign); Win Rate and Trades stay neutral since
  they aren't inherently good or bad on their own.

## 0.9.13

- Update: restyle each strategy's "what would this rule do right now"
  readout in the Strategy Backtests section from a plain text line into a
  proper styled box -- a shaded panel with a holding/not-holding badge, the
  current reading and its trigger as two clear stat tiles, and a short
  caption explaining when it fires.

## 0.9.12

- Add: each strategy in the Strategy Backtests dashboard section now shows
  its current live status (holding or not, and what price/reading would
  trigger the next buy or sell) plus a collapsible chart marking every real
  historical buy (green triangle) and sell (red diamond) on the price line.
  Both additions reuse data a backtest run already produces internally --
  no extra price-history downloads. Fixed a real accuracy gap found during
  manual review: the Trend-Filtered Dip strategy's status only reflected
  its RSI condition, silently omitting that its 200-day trend filter was
  the actual blocker on a real MBLY check -- now flagged explicitly when
  that's the case. See HANDOFF.md item 39.

## 0.9.11

- Fix: the "Buy & Hold" column in the Strategy Backtests dashboard section
  was showing a different number per strategy row, for the same ticker.
  Root cause: `backtesting.py`'s own `Buy & Hold Return [%]` stat is
  computed from each strategy's own indicator-warmup point (day ~14 for
  RSI, day ~200 for a 200-day moving average), not from the same starting
  day for every strategy -- so each row was silently comparing itself
  against a different baseline. Now computed once, from the full raw price
  history, and reused as the same shared number across every strategy's
  row -- an honest apples-to-apples comparison. Added a regression test
  (`test_buy_hold_return_is_identical_across_every_strategy`) so this can't
  silently reappear.

## 0.9.10

- Add: real backtesting. A new `backtest/` package runs 7 well-known
  technical trading rules (RSI mean-reversion, MACD crossover,
  moving-average crossover, Bollinger Band reversion, 20-day breakout, a
  trend-filtered dip buy, and relative strength vs. the S&P 500) against
  each ticker's own 6-year price history via the `backtesting` library --
  deterministic, no LLM involved. Closes the "Backtesting" item that was
  explicitly listed as not built yet. New "Strategy Backtests" dashboard
  section shows each rule's name, plain-English explanation, return vs.
  buy & hold, win rate, trade count, and a result badge. Runs on every
  full and dry run alike (it's free/local). See HANDOFF.md item 37 and
  `research/02-backtesting-and-screening-tools.md` for the full reasoning,
  including why this is a fixed deterministic panel rather than an
  LLM-callable tool.

## 0.9.9

- Update: revise `RESEARCH.md`'s build priority list based on follow-up
  research -- dropped FinBERT and the RL "voice" from the active list
  (reasoning preserved in "Follow-up findings"), dropped GitHub Actions/
  Telegram in favor of Home Assistant's own automations/notifications, and
  expanded each remaining item with real benchmark/cost info where it
  exists (e.g. confirmed our Gemini client has no prompt-caching, so an
  extra Bull/Bear debate round would roughly double that portion of a
  run's cost). Documentation only, no functional changes -- version
  bumped solely to satisfy this repo's pre-commit/CI convention.

## 0.9.8

- Add: `RESEARCH.md` plus `research/` -- notes from cloning and reading the
  source of 18 other stock-related open-source projects (LLM multi-agent
  trading systems, backtesting libraries, RL frameworks, sentiment tools),
  looking for concrete patterns worth adopting into StockLLM's own
  `data`/`agents`/`dashboard` pipeline. Documentation only, no functional
  changes to the add-on itself -- version bumped solely to satisfy this
  repo's own pre-commit/CI convention that every commit touching tracked
  files gets a version bump, not because anything the add-on does changed.

## 0.9.7

- Add: password protection for the direct port added in 0.9.6. New
  `web_password` option (`config.yaml`, `schema` type `password?`) gates
  every route except `/login`/`/assets/*` behind a session-cookie login
  form -- chosen over HTTP Basic Auth specifically because Basic Auth's
  native browser prompt is known to be unreliable inside an iOS
  "standalone" PWA launched from a home-screen icon, exactly last
  release's use case. Ingress traffic is exempt (already behind HA's own
  login, via the same `X-Ingress-Path` trust boundary `_ingress_prefix()`
  already relies on elsewhere), so nothing changes for the primary,
  recommended Ingress-based way of using this add-on. Leaving the password
  blank still works (same "blank = feature off" convention as every other
  optional credential), but the home page now shows a loud warning banner
  in that specific combination (direct port reachable, no password set)
  instead of silently treating it as fine. See HANDOFF.md item 36 for the
  full design writeup, including the open-redirect guard on the
  post-login `?next=` redirect and why the session secret is intentionally
  not persisted across restarts.

## 0.9.6

- Add: direct port access (`config.yaml`'s `ports: {8099/tcp: 8099}`),
  alongside Ingress (not instead of it), plus iOS/Android "Add to Home
  Screen" support -- `apple-mobile-web-app-capable`/`-status-bar-style`/
  `-title` and `apple-touch-icon` added to both real HTML entry points
  (the index/ticker-entry form and the dashboard results page), with a
  new placeholder `dashboard/assets/icon.png`. Ingress URLs embed a
  per-session token that can change across HA restarts/logins, so a
  saved home-screen icon pointing at one can go stale -- the direct port
  gives a stable URL for that specific use case. Documented, real
  security tradeoff: a directly-exposed port has no HA login in front of
  it, unlike Ingress. See DOCS.md for setup steps and HANDOFF.md item 35
  for the full design writeup, including a new required-vs-optional
  split in `ensure_vendored_assets()` so a missing cosmetic icon can
  never break a dashboard write the way a missing required chart asset
  correctly still does.

## 0.9.5

- Fix: the "High" corner label on the price-range track charts rendered
  visibly to the left of its own dot instead of centered on it, flagged
  directly by the user. Root cause was two layered bugs, both fixed:
  1. `dashboard/assets/dashboard.js`'s shared label-collision callback
     (`makeRangeTrackLabelLayout`) always returned an absolute `{x: r.x,
     y}` -- `r.x` is a labelRect's LEFT edge, which only happens to be the
     correct anchor for left-aligned text. That was fine while Low/High
     used explicit align:"left"/"right", but broke the moment they were
     centered (below). Rewritten to return only a relative `dy`, leaving
     x untouched so whatever alignment a label actually uses renders
     correctly -- this callback only ever needs to move labels vertically
     to resolve a collision anyway.
  2. Low/High's label used an array-form `position: [0, -20]`, which
     ECharts measures from the symbol's TOP-LEFT corner, not its center --
     at symbolSize 18 that's a 9px horizontal error on its own, silently
     added to whatever alignment was set. Switched to the keyword form
     `position: "top"` (matching how the marker group already correctly
     uses `"bottom"`), which centers on the symbol properly. Confirmed by
     reading the actual rendered SVG label coordinates against the
     track's real pixel positions, not assumed from ECharts' docs.
  Also gave Low/High room to render fully centered without clipping past
  the SVG edge (grid margin 24 -> 55).

## 0.9.4

- Fix: "Price vs. moving averages" and "Analyst target price range" marker
  dots were painted UNDER the track, not on top of it -- 0.9.3's size fix
  addressed the wrong cause. Confirmed live by reading the actual rendered
  SVG's element order: ECharts does not paint cartesian series strictly in
  the order they're listed in `option.series` -- the scatter (marker) series
  painted before the line (track) series regardless of its later array
  position, so the opaque 10px track drew right over most of every dot.
  Fixed with explicit `z` on both series (z controls paint order; array
  position does not) -- track z:1, markers z:2, markers always on top.
- Fix, same charts: "Low"/"High" had no dot marker at all (`symbolSize: 0`),
  relying only on the track's own rounded end-caps to imply an endpoint.
  Given a real dot now, same size/border as every other marker, in a
  neutral color since Low/High aren't a categorical series the way
  MA20/Mean/etc. are.

## 0.9.3

- Fix: "Price vs. moving averages" and "Analyst target price range" marker
  dots (MA20/MA50/MA200, Mean/Median) were nearly invisible -- `symbolSize`
  was 12 against a 10px-thick track, leaving only 1px of colored dot
  poking out on each side, effectively a hidden sliver rather than a
  visible marker. Bumped to 18 and added a light border ring so each dot
  reads as a distinct circle sitting on the track regardless of how close
  its own color is to the track's neutral gray.

## 0.9.2

- Fix: the RSI gauge had no value indicator at all -- a static colored
  band and a big number below it, with nothing showing where on the band
  that number actually falls. Flagged directly by the user from a real
  screenshot ("where is it in the red, the green, or the gray?"). The
  pointer had been explicitly turned off (`show: False`) during the
  ECharts migration. Added it back as a dot sitting directly on the band
  rather than the default needle-from-center -- a needle this short would
  cross straight through the headline number occupying the same central
  area. `icon: "circle"` pointers turned out to center at *half* of
  `length` (confirmed by reading the actual rendered SVG transform, not
  assumed from docs); `length: "186%"` lands the dot at 93% of the
  gauge's radius, the middle of the band, and stays correct at any
  container width since it's a percentage, not a fixed pixel offset.
- Fix: "Price vs. moving averages" and "Analyst target price range" both
  render colored marker dots (MA20/MA50/MA200, or Mean/Median) with only
  a bare price label -- no name anywhere tying a color to what it means.
  Flagged directly by the user ("it's just a table"). `range_meter()` and
  `range_position_plot()` now both return a legend naming each marker's
  color, wired into their `viz_card()` calls the same way every other
  chart on the page already does it. Low/High/Current aren't in the
  legend -- Low/High are self-evident track endpoints and Current already
  carries its own explicit price label.

## 0.9.1

- Fix: "Price vs. moving averages" markers (MA20/MA50/MA200) could drift
  progressively further apart or crowd together unpredictably, found live
  from a real screenshot after 0.9.0 shipped. Root cause in
  `dashboard/assets/dashboard.js`'s label-collision stagger
  (`makeRangeTrackLabelLayout`): its "forget the previous render pass"
  reset only fired on `dataIndex === 0`, true for the corner (Low/High/
  Current) label group but never true for the marker group, whose points
  start at `dataIndex 2` in the same series -- so stale rects from earlier
  passes never got cleared, and each subsequent pass's labels collided
  against their own leftover ghosts, pushing them further down every
  pass. Fixed by keying the reset off each label's own
  `seriesIndex:dataIndex` identity (resets when a pair is seen again,
  regardless of which index a group happens to start at) instead of a
  fixed magic index.
- Fix, same chart, second bug: the "Current" price triangle marker had no
  `symbolSize`, so it rendered at ECharts' default 50x50 -- 4-5x its own
  path's native 12x10-unit size -- large enough to physically cover the
  neighboring "High" corner label whenever the current price sat close to
  the 52-week high. Fixed by setting `symbolSize: [12, 10]` explicitly.
- Both verified by reconstructing the exact reported scenario, reading
  real rendered SVG label coordinates out of the DOM (not just eyeballing
  a screenshot), confirming the fix converges to a single clean stagger
  pass, and re-screenshotting.

## 0.9.0

- **Replaced every hand-rolled inline-SVG chart with Apache ECharts**, vendored
  locally at `dashboard/assets/echarts.min.js` (no CDN, no build step — this
  add-on may run with no internet egress). A new `dashboard/assets/dashboard.js`
  runtime reads a `window.__CHARTS__` registry (emitted by `build_dashboard()`)
  and renders it client-side; `dashboard/assets.py`'s `ensure_vendored_assets()`
  copies both files next to every generated dashboard HTML (wired into
  `main.py`'s `dashboard` command and `webapp/app.py`'s `/run` handler).
  Motivated by an entire prior session (0.8.1-0.8.8) spent chasing one
  hand-rolled-SVG mobile/responsive bug after another (clipping, label
  collision, diverging-bar overflow on skewed data, inconsistent internal
  margins between neighboring charts) — every one of those bug classes is
  something ECharts solves natively (native gauge geometry, bidirectional
  self-centering stacking, built-in label-collision layout, real container-
  size-aware responsive layout) instead of needing more hand-tuned pixel math.
  The RSI gauge is a deliberate visual-form change (semicircular dial, not the
  old horizontal zone strip) as a result.
- Fixed three real "leaked `None`" bugs found auditing the migration (same bug
  class `test_dashboard_build.py`'s `assert_no_leaked_values` already guards
  against, but two of these three slipped past it — one because it wasn't a
  `None`/`nan` leak at all, one because the `None` didn't land contiguous with
  `><`): the EPS-surprise/quarterly-financials/buyback-spend cards passed a
  literal `"<svg></svg>"` string for empty data instead of `None`, which
  `viz_card()` treats as "there is a chart" — hid the "no data" table behind a
  toggle button instead of showing it immediately; the analyst
  recommendation-trend small-multiples loop and the AI recommendation's
  fair-value-range block both interpolated a chart function's `None` return
  (empty/invalid input) directly into an f-string with no guard, which would
  render the literal text "None" on the page.
- Everything else on the page (topbar, mobile nav, hero block, KPI tiles, data
  tables, badges, glossary popovers, dark-mode toggle) is unchanged —
  server-rendered exactly as before, was never the source of these bugs.

## 0.8.8

- Fix: "Price vs. moving averages" and the analyst target range chart
  used a much wider internal margin (pad=60, track spans 500 of 620
  units) than the RSI gauge directly below them on the same card
  (pad=20, spans 580 of 620) -- found from a photo comparing the two
  tracks side by side on a real phone. Matched both to gauge_meter's
  pad=20; a marker/Current label sitting right at an extreme value can no
  longer overflow the now-tighter margin because label positions are
  clamped independently of the pad (`_label_x_clamp`) instead of relying
  on extra whitespace to protect them.
- Fixed two more real bugs found while checking that change: charts using
  a centered-neutral-segment layout (`diverging_stacked_sentiment`,
  `diverging_stacked_ordinal` -- the social sentiment split and analyst
  recommendation trend) could push their larger side's bar and total
  label past the canvas edge entirely when the split was heavily
  imbalanced (found live: 18 bullish vs. 1 bearish; reproduced worse with
  synthetic 1000-vs-1 splits). Both now scale the whole diagram down
  together, preserving proportions, so neither side can exceed the
  available space regardless of how skewed the data is. Also found and
  fixed the quarterly revenue/income chart's y-axis labels clipping off
  the left edge (pad_l was too narrow for the mobile font size).
- Verification this round checked horizontal clipping for the first time,
  not just vertical -- the extreme-imbalance bug above only ever showed
  up on that axis, and every previous round's check had missed it.

## 0.8.7

- Fix: on mobile, the page-level gutter (`.wrap`'s padding) and each
  card's own padding stacked on top of each other -- the card padding was
  never reduced for mobile at all -- eating about 19% of a 375px phone
  screen's width in pure margin before any card content (a chart, a
  table) even started. Found from a screenshot marking the visible gap
  on both sides. Tightened both together (14px+22px -> 10px+14px per
  side), which also gives every chart real extra rendered width, not
  just less dead space.

## 0.8.6

- Fix: "Price vs. moving averages" (and the analyst target range chart)
  could look like they weren't using the card's full width -- found from
  a screenshot where AAPL's current price, close to its 52-week high,
  suppressed the "$340.08" high-end label (0.8.4/0.8.5's collision fix),
  leaving a big unexplained empty patch of track on the right with
  nothing there to explain it. Flipped which label gives way: the Low/
  High (or analyst target Low/High) corner labels now always render --
  they're what visually anchors the reader's sense that the track spans
  its full width -- and "Current" drops only its text label near an edge
  (never its triangle marker), since the current price is already shown
  prominently in the page's own hero number up top.

## 0.8.5

- Fix two more real mobile bugs from a follow-up screenshot: the RSI
  gauge's headline number ("45.1") had its top clipped off, and the
  "Price vs. moving averages" chart still read as too small despite
  0.8.4's fix.
  - **Clipping**: 0.8.4 boosted the gauge's headline text without giving
    it more room above the track, so its ascender got clipped against the
    SVG viewport's top edge. Gave `gauge_meter`, `range_meter`, and
    `range_position_plot` real headroom (all three measured empirically
    via `getBBox` in an actual browser, not estimated from font metrics)
    and moved the headline/track-label offsets to fit.
  - **Still small**: the previous mobile font-size override (25px) was
    calibrated only against the 3 "track" charts. It's one shared CSS
    rule across every chart on the page, and at that size it overlapped
    labels in several chart types never redesigned for it (grouped
    quarterly revenue/income columns, the relative-performance bars).
    Split into three tiers: `.viz-track-label`/`.viz-headline` (the 3
    track charts, now deliberately spaced for up to 30px/34px) and a
    plain tier for everything else, sized at the largest value (14px)
    that still doesn't collide anywhere -- including grouped_column_chart
    showing up to 8 quarters across a fixed-width plot, the tightest
    constraint in the file. Also fixed a real pre-existing bug this
    surfaced: two series' value labels in the same quarter (Revenue vs.
    Net income) could land at nearly the same height and overlap
    regardless of font size -- now staggered apart.
  - Verified this round by rendering every committed fixture with real
    mobile-viewport emulation and checking every single chart's every
    text element via `getBBox` for clipping against its own viewBox and
    pairwise overlap against every other label -- zero of either, versus
    doing spot checks by eye, which is what let both of these bugs
    through in 0.8.4. (Also corrected the calibration process itself:
    testing without mobile emulation gives different font metrics than a
    real phone and had produced an unsafe 15px figure before this.)

## 0.8.4

- Fix: 0.8.2's mobile chart fix (pin to native size + scroll) traded
  illegible text for a worse problem, found from a follow-up screenshot --
  charts were clipped to their card's visible width by default, hiding
  Current/MA20/the high-end label off-screen with no visual hint to
  swipe. Reverted that approach. The real fix: charts stay at
  width:100% (always fully visible, never clipped), and a mobile media
  query overrides each chart `<text>` element's font-size to a larger
  value instead -- CSS font-size on SVG text still scales with the
  viewBox transform even when it wins the cascade over the inline
  attribute, so this brings the rendered size up without pinning the
  chart wider than its card.
- That larger mobile text uncovered two real label-collision bugs that
  were invisible at the old smaller size (confirmed on a screenshot:
  "MA50"/"MA20" running together as "MA50MA20", and "Current" overlapping
  the 52-week-high price label): `range_position_plot`'s row-stagger
  threshold was tuned for the old font size, and there was no collision
  handling at all between the "Current" marker's label and the Low/High
  corner labels. Fixed both -- the stagger threshold is now sized for the
  actual mobile-rendered label width, and whichever corner label would
  collide with "Current" is dropped (Current's own label already conveys
  a near-identical value at that position). `range_meter` (analyst
  target range) had the identical latent bugs and got the identical fix.

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
