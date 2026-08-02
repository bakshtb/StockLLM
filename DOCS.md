# StockLLM — Home Assistant Add-on

Installs StockLLM as a Home Assistant add-on with a web UI: pick a ticker,
choose dry-run (free) or a full run (calls Anthropic, Gemini, and Qwen,
gets you the 6-agent AI recommendation), and view the resulting dashboard.

This repo is private, so Supervisor needs a GitHub token embedded in the
repo URL to clone it -- a plain `git clone` won't authenticate on its own.

## 1. Add the repository to Home Assistant

1. Create a GitHub **fine-grained personal access token**: GitHub →
   Settings → Developer settings → Personal access tokens → Fine-grained
   tokens → Generate new token. Scope it to **only this repository**, with
   **Contents: Read-only** permission (that's the only permission a clone
   needs) -- avoid a broad, all-repos classic token.
2. In Home Assistant: **Settings → Add-ons → Add-on Store**.
3. Click the **⋮** (top right) → **Repositories**.
4. Paste the repo URL with the token embedded right before `github.com`:
   ```
   https://<YOUR_TOKEN>@github.com/bakshtb/StockLLM
   ```
5. Click **Add**. The add-on store will refresh and **StockLLM** should appear in the local store.

This token is stored locally by Supervisor (not published anywhere) and
reused automatically for update checks -- everything below works exactly
the same as a public repo from here on.

## 2. Install and configure

1. Click into the **StockLLM** add-on and click **Install**. The first install builds the Docker image locally on your HA host, which can take a few minutes (subsequent updates rebuild the same way).
2. Go to the add-on's **Configuration** tab and fill in:

   Required for a full (non-dry-run) check — dry-run needs none of these:
   - `anthropic_api_key` — from console.anthropic.com (Settings → API Keys). Powers the Skeptic and Judge agents.
   - `qwen_api_key` — from Alibaba Cloud Model Studio. Powers the independent second-opinion Skeptic and the Quant Checker.
   - `gemini_api_key` — from Google AI Studio. Powers the Bull, Bear, and both digest (news/filings summarization) agents.

   Always required (used even in dry-run):
   - `sec_edgar_user_agent` — your name + an email, e.g. `Jane Doe jane@example.com`. SEC EDGAR requires this to identify who's making requests (no signup, just an honest contact string).

   Optional — each adds more data, but the add-on works fine with these blank:
   - `finnhub_api_key` — supplements news coverage, and unlocks insider sentiment (MSPR) + analyst recommendation trend.
   - `fred_api_key` — free forever, no paid tier. Adds inflation/unemployment/fed-funds-rate/yield-curve to the macro backdrop.
   - `fmp_api_key` — free tier (250 calls/day). Adds an independent DCF fair-value estimate and PEG ratio.

   - `monthly_spend_limit_usd` — default 50. Full runs cost a few cents each; this is a hard stop once the month's total (tracked in the add-on's own local database) reaches this.
3. **Start** the add-on.
4. Open it from the Home Assistant sidebar (it appears there via Ingress — no separate port or login needed, it's already behind your HA login).

## 3. Using it

- Enter a ticker, leave **Dry run** checked for a free data-only check, or uncheck it for the full 6-agent AI recommendation (costs a few cents, needs the three API keys from step 2).
- Every run is saved and listed under **Recent runs** on the home page so you can revisit past dashboards without re-running them.

## Auto-update

Toggle **Auto update** on the add-on's own page once installed. Home
Assistant periodically checks the repository for a version bump in
`config.yaml` and updates automatically when it finds one — so an update
only ships once `version:` in `config.yaml` has actually been bumped and
pushed (see `HANDOFF.md` in the repo for the full reasoning behind this
add-on's structure).

## Troubleshooting

- **"Repository not found" / can't add the repo**: make sure the URL is exactly the repo itself, nothing appended — `https://<TOKEN>@github.com/bakshtb/StockLLM`, not `.../settings`, `.../tree/main`, or any other page from the browser address bar. Since this repo is private, also double check the token is valid, hasn't expired, and has at least Contents: Read-only access to this repo.
- **Add-on won't start / build fails**: check the add-on's **Log** tab — this is a plain Docker build from the `Dockerfile` in the repo, so build errors show up there directly.
- **"ANTHROPIC_API_KEY is not set" / "QWEN_API_KEY is not set" / "GEMINI_API_KEY is not set" when unchecking Dry run**: fill in the missing key under Configuration (step 2) and restart the add-on -- all three are required for a full run.
- **Blank/black page after submitting a ticker, nothing in the log**: this was a real bug (Ingress path-prefix handling) fixed in the add-on itself — make sure you're on the latest version (check for an update, or reinstall if needed).
- Everything else (what the tool actually fetches, known limitations, cost controls) is documented in the main `README.md`.
