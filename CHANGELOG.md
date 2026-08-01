# Changelog

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
