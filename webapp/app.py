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
        "fred_api_key": "FRED_API_KEY",
        "fmp_api_key": "FMP_API_KEY",
        "monthly_spend_limit_usd": "MONTHLY_SPEND_LIMIT_USD",
        "web_password": "WEB_PASSWORD",
    }
    for option_key, env_key in option_to_env.items():
        value = options.get(option_key)
        if value not in (None, ""):
            os.environ[env_key] = str(value)


_load_ha_options()

import re
import glob
import secrets
import datetime as dt

from flask import Flask, request, redirect, send_from_directory, session

from config import ANTHROPIC_API_KEY, QWEN_API_KEY, GEMINI_API_KEY, MONTHLY_SPEND_LIMIT_USD, OUTPUT_DIR, WEB_PASSWORD
from data.bundle import build_research_bundle
from agents.pipeline import run_pipeline
from storage import db
from storage.db import get_monthly_spend
from dashboard.generate_dashboard import build_dashboard, CSS_STYLE, esc
from dashboard.assets import ensure_vendored_assets

app = Flask(__name__)

# Random per process start, not persisted -- signs the login session cookie.
# The one real consequence: every add-on restart/update invalidates existing
# sessions, so a user who was logged in has to enter the password again next
# time they open the app. Acceptable for a personal tool (a one-time
# password entry, not a lockout) and far simpler than persisting a stable
# secret across restarts for a single-user app that isn't handling anyone
# else's sessions.
app.secret_key = secrets.token_bytes(32)
app.config["PERMANENT_SESSION_LIFETIME"] = dt.timedelta(days=30)

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
<!-- iOS "Add to Home Screen" support -- only meaningful reached via the
     add-on's direct port (config.yaml's `ports`), since an Ingress URL's
     token prefix isn't stable enough to bookmark as a home-screen icon. -->
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="StockLLM">
<link rel="apple-touch-icon" href="assets/icon.png">
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


# Paths reachable with no login: the login page/submit itself (obviously),
# and the vendored assets (icon/CSS-adjacent JS) the login page's own head
# needs to render -- gating those too would mean the login page can't even
# load its own icon before you've logged in to see it.
_LOGIN_EXEMPT_PATH_PREFIXES = ("/login", "/assets/")


def _login_required() -> bool:
    """
    Whether the current request must be sent to the login gate before
    proceeding. False (no gate) when: WEB_PASSWORD isn't configured
    (matches this repo's "blank = feature not configured" convention for
    every other optional credential -- see config.py); the request already
    came through Home Assistant's own login via Ingress (a non-empty
    X-Ingress-Path header is set only by HA's own proxy, never forgeable by
    a request hitting this port directly -- same trust boundary
    _ingress_prefix() already relies on); or this session already logged in
    successfully.
    """
    if not WEB_PASSWORD:
        return False
    if _ingress_prefix():
        return False
    return not session.get("authed")


def _safe_next_path(raw: str) -> str:
    """Only accept an internal, relative path for post-login redirect --
    guards against an open-redirect (?next=https://evil.example) being used
    to phish from what looks like this app's own login page."""
    if raw and raw.startswith("/") and not raw.startswith("//") and "://" not in raw:
        return raw
    return "/"


@app.before_request
def _gate_direct_access():
    if request.path.startswith(_LOGIN_EXEMPT_PATH_PREFIXES) or not _login_required():
        return None
    # _login_required() already confirmed we're not behind Ingress in this
    # branch, so the plain unprefixed path below is always correct here --
    # unlike every other redirect in this file, no _ingress_prefix() call
    # is needed (there's nothing to prefix with).
    return redirect(f"/login?next={_safe_next_path(request.path)}")


def _render_login(error=None, next_path="/"):
    error_html = f'<div class="error-box">{error}</div>' if error else ""
    return f"""{PAGE_HEAD}
<div class="wrap">
  <div class="card form-card">
    <h2>StockLLM</h2>
    <div class="card-sub">Enter the password to continue.</div>
    {error_html}
    <form method="post" action="/login">
      <input type="hidden" name="next" value="{esc(_safe_next_path(next_path))}">
      <div class="form-row">
        <label for="password">Password</label>
        <input type="password" id="password" name="password" required autofocus>
      </div>
      <button type="submit" class="submit">Log in</button>
    </form>
  </div>
</div>
{PAGE_TAIL}"""


@app.route("/login", methods=["GET"])
def login_form():
    return _render_login(next_path=request.args.get("next", "/"))


@app.route("/login", methods=["POST"])
def login_submit():
    next_path = _safe_next_path(request.form.get("next", "/"))
    password = request.form.get("password", "")
    # secrets.compare_digest: a plain `==` short-circuits on the first
    # mismatched byte, which leaks how many leading characters were
    # correct via response timing -- irrelevant against a truly random
    # guesser, but a real difference against someone actually probing it.
    if not WEB_PASSWORD or not secrets.compare_digest(password, WEB_PASSWORD):
        return _render_login(error="Incorrect password.", next_path=next_path), 401
    session.permanent = True
    session["authed"] = True
    return redirect(next_path)


@app.route("/logout", methods=["POST"])
def logout():
    session.pop("authed", None)
    return redirect("/login")


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
    # Only meaningful (and only shown) when this session actually went
    # through the password gate -- an Ingress session was never asked for
    # one, so a "Log out" link there would have nothing to do.
    logout_html = (
        '<form method="post" action="/logout" style="text-align:right;margin-bottom:8px;">'
        '<button type="submit" style="background:none;border:none;color:var(--text-secondary);'
        'font-size:12px;cursor:pointer;text-decoration:underline;padding:0;">Log out</button></form>'
    ) if session.get("authed") else ""
    # Loud, not silent: reachable on the direct port with no password set at
    # all means _login_required() lets everything through unauthenticated
    # (matching this repo's "blank = feature off" convention -- see
    # config.py) -- but unlike a blank optional API key, that specific
    # combination is a real open door, not just a missing nice-to-have.
    unprotected_html = (
        '<div class="error-box" style="background:rgba(250,178,25,0.14);'
        'border-color:var(--status-warning);color:var(--status-warning);">'
        "This add-on's direct port has no password set -- anyone who can reach this host on "
        "this port can use it, unauthenticated. Set <b>web_password</b> in this add-on's "
        "Configuration tab to protect it."
        "</div>"
    ) if not prefix and not WEB_PASSWORD else ""
    return f"""{PAGE_HEAD}
<div class="wrap">
  {logout_html}
  {unprotected_html}
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
                    run_id, dc["name"], dc.get("model", "unknown"),
                    dc["input_tokens"], dc["output_tokens"], 0, dc["cost_usd"], {},
                )
                digest_cost += dc["cost_usd"]

            pipeline_result = run_pipeline(run_id, ticker, bundle, starting_cost_usd=digest_cost)
            db.create_outcome(run_id, bundle["price"]["current_price"])
        except RuntimeError as e:
            return _render_form(error=str(e)), 500

    bundle_path = os.path.join(OUTPUT_DIR, f"{ticker}.json")
    with open(bundle_path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, indent=2)

    dashboard_name = f"{ticker}_dashboard.html"
    with open(os.path.join(OUTPUT_DIR, dashboard_name), "w", encoding="utf-8") as f:
        f.write(build_dashboard(bundle, pipeline_result))
    ensure_vendored_assets(OUTPUT_DIR)

    return redirect(f"{_ingress_prefix()}/output/{dashboard_name}")


@app.route("/output/<path:filename>")
def output_file(filename):
    return send_from_directory(OUTPUT_DIR, filename)


# Serves dashboard/assets/ (echarts.min.js, dashboard.js, icon.png, ...)
# directly for pages that aren't inside an OUTPUT_DIR run folder -- namely
# the index/form page below, which references them via a plain relative
# path ("assets/icon.png") exactly like every generated dashboard already
# does. That works unprefixed under both direct port access and Ingress:
# Ingress strips its dynamic token prefix before forwarding to this
# container, so Flask always sees the plain "/assets/..." path either way
# -- same reasoning as _ingress_prefix() below, just for a route that
# happens to need no prefix-awareness at all since it's never prefixed at
# the server side, only ever relative in the HTML.
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard", "assets")


@app.route("/assets/<path:filename>")
def static_assets(filename):
    return send_from_directory(_ASSETS_DIR, filename)


if __name__ == "__main__":
    # Flask's own app.run() is a development server, and neither it nor
    # waitress (the production WSGI server used below) installs a SIGTERM
    # handler on its own -- HA Supervisor's "stop" during every add-on
    # update/restart killed the process via Python's default signal
    # disposition (exit code 143), logging a warning every single time.
    # Trap it explicitly: sys.exit(0) raises SystemExit, which interrupts
    # waitress's blocking accept loop and propagates out cleanly (it's a
    # BaseException, so it isn't accidentally swallowed by an `except
    # Exception` somewhere in the request-handling loop).
    import signal
    import sys

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    from waitress import serve
    serve(app, host="0.0.0.0", port=8099)
