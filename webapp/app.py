"""
Flask web UI for StockLLM -- lets a user pick a ticker, choose dry-run or a
full LLM-powered run, and view the resulting dashboard in a browser. This is
what the Home Assistant add-on runs (see run.sh / Dockerfile at the repo
root); it can also just be run directly with `python -m webapp.app` for
local testing outside of HA.

Reuses the exact same functions main.py's CLI calls (data.bundle.
build_research_bundle, agents.pipeline.run_pipeline, dashboard.
generate_dashboard.build_dashboard) -- no pipeline logic is duplicated here,
this is purely a second entrypoint into the same code.
"""

import json
import os


def _load_ha_options():
    """
    Home Assistant writes the add-on's user-filled Configuration tab to
    /data/options.json inside the container. Translate that into the same
    environment variables config.py already reads via os.getenv(), so the
    exact same config.py works unmodified whether invoked by the CLI (reads
    a real .env) or by the add-on (reads HA's options). Must run before
    `config` (or anything importing it) is imported anywhere in this
    process -- Python only executes a module's top-level code once, so
    once config.py has already read os.getenv() it's too late.
    """
    options_path = "/data/options.json"
    if not os.path.exists(options_path):
        return
    try:
        with open(options_path, "r", encoding="utf-8") as f:
            options = json.load(f)
    except Exception:
        return

    option_to_env = {
        "anthropic_api_key": "ANTHROPIC_API_KEY",
        "qwen_api_key": "QWEN_API_KEY",
        "gemini_api_key": "GEMINI_API_KEY",
        "sec_edgar_user_agent": "SEC_EDGAR_USER_AGENT",
        "finnhub_api_key": "FINNHUB_API_KEY",
        "monthly_spend_limit_usd": "MONTHLY_SPEND_LIMIT_USD",
    }
    for option_key, env_key in option_to_env.items():
        value = options.get(option_key)
        if value not in (None, ""):
            os.environ[env_key] = str(value)


_load_ha_options()

import re
import glob
import datetime as dt

from flask import Flask, request, redirect, send_from_directory

from config import ANTHROPIC_API_KEY, QWEN_API_KEY, GEMINI_API_KEY, MODEL_DIGEST, MONTHLY_SPEND_LIMIT_USD, OUTPUT_DIR
from data.bundle import build_research_bundle
from agents.pipeline import run_pipeline
from storage import db
from storage.db import get_monthly_spend
from dashboard.generate_dashboard import build_dashboard, CSS_STYLE

app = Flask(__name__)

# Deliberately restrictive: tickers are short alphanumeric strings (a few
# use '.' or '-', e.g. BRK.B). This also doubles as a security boundary --
# the ticker becomes part of an output filename below, so rejecting
# anything with a path separator or '..' up front avoids ever needing to
# reason about path-traversal in the filename construction.
TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")

PAGE_HEAD = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>StockLLM</title>
<script>
(function () {{
  try {{
    var saved = localStorage.getItem('stockllm-theme');
    if (saved) {{ document.documentElement.setAttribute('data-theme', saved); }}
  }} catch (e) {{}}
}})();
</script>
<style>{CSS_STYLE}
.form-card {{ max-width: 480px; margin: 60px auto 24px auto; }}
.form-row {{ margin-bottom: 14px; }}
.form-row label {{ display: block; font-size: 13px; color: var(--text-secondary); margin-bottom: 6px; }}
.form-row input[type=text] {{
  width: 100%; padding: 10px 12px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--page-plane); color: var(--text-primary); font-size: 14px; box-sizing: border-box;
}}
.form-row.checkbox {{ display: flex; align-items: center; gap: 8px; }}
.form-row.checkbox label {{ margin: 0; }}
.form-row.checkbox input {{ width: auto; }}
button.submit {{
  width: 100%; padding: 12px; border-radius: 8px; border: none;
  background: var(--series-1); color: #fff; font-size: 14px; font-weight: 600; cursor: pointer;
}}
button.submit:hover {{ opacity: 0.9; }}
button.submit:disabled {{ opacity: 0.6; cursor: wait; }}
.error-box {{
  background: rgba(208,59,59,0.12); border: 1px solid var(--status-critical);
  color: var(--status-critical); padding: 12px 14px; border-radius: 8px; margin-bottom: 16px; font-size: 13px;
}}
.recent-list {{ max-width: 480px; margin: 0 auto 40px auto; }}
.recent-list a {{ color: var(--series-1); text-decoration: none; }}
.recent-list a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
"""
PAGE_TAIL = "</body></html>"


def _ingress_prefix() -> str:
    """
    Home Assistant's Ingress proxy mounts this add-on at a dynamic sub-path
    (e.g. /api/hassio_ingress/<token>) rather than the domain root, and
    tells the backend what that prefix currently is via the X-Ingress-Path
    request header. Any URL this app generates -- form action, links,
    redirects -- has to be built with this prefix, or the browser resolves
    it against the domain root instead and the request goes to HA core
    (or nowhere) instead of back into this add-on. Empty string when not
    behind ingress (e.g. `python -m webapp.app` directly, or `docker run`
    without HA), so plain root-relative paths keep working unprefixed there.
    """
    return request.headers.get("X-Ingress-Path", "")


def _recent_runs(limit=15):
    if not os.path.isdir(OUTPUT_DIR):
        return []
    files = glob.glob(os.path.join(OUTPUT_DIR, "*_dashboard.html"))
    files.sort(key=os.path.getmtime, reverse=True)
    return [
        (os.path.basename(p), dt.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M"))
        for p in files[:limit]
    ]


def _render_form(error=None):
    prefix = _ingress_prefix()
    recent = _recent_runs()
    recent_html = "".join(
        f'<div class="news-item"><a href="{prefix}/output/{name}">{name}</a> <span class="meta">{mtime}</span></div>'
        for name, mtime in recent
    ) or '<div class="empty">No runs yet.</div>'
    error_html = f'<div class="error-box">{error}</div>' if error else ""
    return f"""{PAGE_HEAD}
<div class="wrap">
  <div class="card form-card">
    <h2>StockLLM</h2>
    <div class="card-sub">Pick a ticker to research. Not financial advice.</div>
    {error_html}
    <form method="post" action="{prefix}/run" onsubmit="this.querySelector('button').disabled=true; this.querySelector('button').textContent='Running...';">
      <div class="form-row">
        <label for="ticker">Ticker symbol</label>
        <input type="text" id="ticker" name="ticker" placeholder="e.g. AAPL" maxlength="10" required autofocus>
      </div>
      <div class="form-row checkbox">
        <input type="checkbox" id="dry_run" name="dry_run" checked>
        <label for="dry_run">Dry run (free, no API key needed, data only -- uncheck for the full AI recommendation)</label>
      </div>
      <button type="submit" class="submit">Run</button>
    </form>
  </div>
  <div class="card recent-list">
    <h2>Recent runs</h2>
    {recent_html}
  </div>
</div>
{PAGE_TAIL}"""


@app.route("/", methods=["GET"])
def index():
    return _render_form()


@app.route("/run", methods=["POST"])
def run_check():
    ticker = (request.form.get("ticker") or "").strip().upper()
    dry_run = request.form.get("dry_run") == "on"

    if not TICKER_RE.match(ticker):
        return _render_form(error="Enter a valid ticker symbol (letters/numbers, up to 10 characters)."), 400

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    try:
        bundle, digest_calls = build_research_bundle(ticker, run_digests=not dry_run)
    except ValueError as e:
        return _render_form(error=str(e)), 400

    pipeline_result = None
    if not dry_run:
        if not ANTHROPIC_API_KEY:
            return _render_form(
                error="ANTHROPIC_API_KEY is not set. Fill it in under this add-on's Configuration "
                      "tab (or use Dry run, which needs no API key)."
            ), 400

        if not QWEN_API_KEY:
            return _render_form(
                error="QWEN_API_KEY is not set. The independent second-opinion Skeptic and Quant "
                      "Checker agents need it -- fill it in under this add-on's Configuration tab "
                      "(or use Dry run, which needs no API key)."
            ), 400

        if not GEMINI_API_KEY:
            return _render_form(
                error="GEMINI_API_KEY is not set. Bull, Bear, and both digest steps need it -- fill "
                      "it in under this add-on's Configuration tab (or use Dry run, which needs no "
                      "API key)."
            ), 400

        try:
            db.init_db()
            spent = get_monthly_spend()
            if spent >= MONTHLY_SPEND_LIMIT_USD:
                return _render_form(
                    error=f"Monthly spend limit reached (${spent:.2f} / ${MONTHLY_SPEND_LIMIT_USD:.2f}). "
                          "Raise it in this add-on's Configuration tab, or use Dry run."
                ), 400

            run_id = db.create_run(ticker)
            db.save_bundle(run_id, bundle)

            digest_cost = 0.0
            for dc in digest_calls:
                db.save_agent_output(
                    run_id, dc["name"], dc.get("model", MODEL_DIGEST),
                    dc["input_tokens"], dc["output_tokens"], 0, dc["cost_usd"], {},
                )
                digest_cost += dc["cost_usd"]

            pipeline_result = run_pipeline(run_id, ticker, bundle, starting_cost_usd=digest_cost)
        except RuntimeError as e:
            return _render_form(error=str(e)), 500

    bundle_path = os.path.join(OUTPUT_DIR, f"{ticker}.json")
    with open(bundle_path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)

    dashboard_name = f"{ticker}_dashboard.html"
    with open(os.path.join(OUTPUT_DIR, dashboard_name), "w", encoding="utf-8") as f:
        f.write(build_dashboard(bundle, pipeline_result))

    return redirect(f"{_ingress_prefix()}/output/{dashboard_name}")


@app.route("/output/<path:filename>")
def output_file(filename):
    return send_from_directory(OUTPUT_DIR, filename)


if __name__ == "__main__":
    # debug=False deliberately -- Flask's debug mode ships an interactive
    # in-browser debugger that can execute arbitrary code, not appropriate
    # even behind HA's ingress proxy.
    app.run(host="0.0.0.0", port=8099, debug=False)
