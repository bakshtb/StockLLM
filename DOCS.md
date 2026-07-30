# StockLLM — Home Assistant Add-on

Installs StockLLM as a private Home Assistant add-on with a web UI: pick a
ticker, choose dry-run (free) or a full run (calls the Anthropic API, gets
you the 4-agent AI recommendation), and view the resulting dashboard.

This add-on lives in a **private** GitHub repository, so Home Assistant
needs a way to authenticate when it clones it — Supervisor's normal
"Add-on Store → Repositories" flow only works with a plain `git clone`,
which can't reach a private repo on its own. The fix is a GitHub
**fine-grained Personal Access Token embedded directly in the repository
URL** you give Home Assistant.

## 1. Generate a fine-grained Personal Access Token

1. Go to **github.com/settings/tokens** → **Fine-grained tokens** → **Generate new token**.
2. **Repository access**: "Only select repositories" → choose this repo (`StockLLM`).
3. **Permissions** → **Repository permissions** → **Contents**: **Read-only**. Nothing else is needed.
4. Generate it and copy the token (starts with `github_pat_...`) — GitHub only shows it once.
5. Treat it like a password: don't paste it into a screenshot, a public issue, or a chat that isn't yours. If it ever leaks, revoke it immediately from the same tokens page and generate a new one.

## 2. Add the repository to Home Assistant

1. In Home Assistant: **Settings → Add-ons → Add-on Store**.
2. Click the **⋮** (top right) → **Repositories**.
3. Paste, with your token embedded:
   ```
   https://<YOUR_TOKEN>@github.com/bakshtb/StockLLM
   ```
4. Click **Add**. The add-on store will refresh and **StockLLM** should appear in the local store.

## 3. Install and configure

1. Click into the **StockLLM** add-on and click **Install**. The first install builds the Docker image locally on your HA host, which can take a few minutes (subsequent updates rebuild the same way).
2. Go to the add-on's **Configuration** tab and fill in:
   - `anthropic_api_key` — from console.anthropic.com (Settings → API Keys). Only needed for full (non-dry-run) checks; dry-run works without it.
   - `sec_edgar_user_agent` — your name + an email, e.g. `Jane Doe jane@example.com`. SEC EDGAR requires this to identify who's making requests (no signup, just an honest contact string).
   - `finnhub_api_key` — optional, supplements news coverage. Leave blank if you don't have one.
   - `monthly_spend_limit_usd` — default 50. Full runs cost a few cents each; this is a hard stop once the month's total (tracked in the add-on's own local database) reaches this.
3. **Start** the add-on.
4. Open it from the Home Assistant sidebar (it appears there via Ingress — no separate port or login needed, it's already behind your HA login).

## 4. Using it

- Enter a ticker, leave **Dry run** checked for a free data-only check, or uncheck it for the full 4-agent AI recommendation (costs a few cents, needs the API key from step 3).
- Every run is saved and listed under **Recent runs** on the home page so you can revisit past dashboards without re-running them.

## Auto-update

Toggle **Auto update** on the add-on's own page once installed. Home
Assistant periodically checks the repository for a version bump in
`config.yaml` and updates automatically when it finds one — so an update
only ships once `version:` in `config.yaml` has actually been bumped and
pushed (see `HANDOFF.md` in the repo for the full reasoning behind this
add-on's structure).

## Troubleshooting

- **"Repository not found" / can't add the repo**: double check the token is still valid (fine-grained tokens have an expiry date) and that it's scoped to this exact repository with Contents: Read-only.
- **Add-on won't start / build fails**: check the add-on's **Log** tab — this is a plain Docker build from the `Dockerfile` in the repo, so build errors show up there directly.
- **"ANTHROPIC_API_KEY is not set" when unchecking Dry run**: fill it in under Configuration (step 3) and restart the add-on.
- Everything else (what the tool actually fetches, known limitations, cost controls) is documented in the main `README.md`.
