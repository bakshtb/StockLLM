"""
Flask web UI for ADELE -- lets a user pick a ticker, choose dry-run or a
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
import threading
import time

from flask import Flask, request, redirect, send_from_directory, session, jsonify

from config import ANTHROPIC_API_KEY, QWEN_API_KEY, GEMINI_API_KEY, MONTHLY_SPEND_LIMIT_USD, OUTPUT_DIR, WEB_PASSWORD
from data.bundle import build_research_bundle
from agents.pipeline import run_pipeline
from storage import db
from storage.db import get_monthly_spend
from dashboard.generate_dashboard import build_dashboard, load_built_assets, esc
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

# In-memory job registry backing the async /run flow (see run_check()/
# _run_job() below): a "run" (data fetch + optional multi-agent LLM pass)
# used to block the /run request for its entire duration -- often 10s of
# seconds with the AI recommendation on -- with nothing rendered but the
# browser's own spinner the whole time. /run now returns almost
# immediately and redirects to /progress/<job_id>, which polls
# /progress/<job_id>/status while the real work runs in a background
# thread.
#
# Deliberately in-memory, not persisted to storage/db.py: this is a
# single-process, single-worker personal add-on (see app.secret_key above
# for the same reasoning applied to sessions) -- a job lost on a mid-run
# restart is a rare, low-stakes inconvenience (re-submit the ticker), and
# not worth a persistence layer. Guarded by _jobs_lock since the
# background thread and request-handling threads both touch it.
_jobs = {}
_jobs_lock = threading.Lock()
_JOB_MAX_AGE_SECONDS = 3600  # prune finished jobs older than this, opportunistically (see _prune_old_jobs)


def _prune_old_jobs():
    """Called each time a new job is created -- keeps _jobs from growing
    without bound over a long add-on uptime, with no separate reaper thread
    needed for what's normally a handful of jobs at a time."""
    cutoff = time.time() - _JOB_MAX_AGE_SECONDS
    for jid in [j for j, v in _jobs.items() if v["status"] != "running" and v.get("finished_at", 0) < cutoff]:
        del _jobs[jid]


def _run_job(job_id: str, ticker: str, dry_run: bool) -> None:
    """Runs entirely on a background thread -- no Flask request/session
    context here (this function must not touch `request` or `session`),
    only what run_check() below already resolved and passed in. Mirrors
    the exact same sequence run_check() used to run synchronously; the
    only behavioral addition is the set_stage() calls at each real stage
    boundary, so the progress page can show honest, non-fabricated
    progress instead of a static spinner."""
    def set_stage(stage: str) -> None:
        with _jobs_lock:
            _jobs[job_id]["stage"] = stage

    try:
        set_stage("Fetching market data, filings, news & running backtests…")
        bundle, digest_calls = build_research_bundle(
            ticker, run_digests=not dry_run,
            on_stage=(lambda: set_stage("Summarizing filings & news…")) if not dry_run else None,
        )

        pipeline_result = None
        if not dry_run:
            # db.init_db() already ran synchronously in run_check() before
            # this job was even created -- see the pre-check block there.
            run_id = db.create_run(ticker)
            db.save_bundle(run_id, bundle)

            digest_cost = 0.0
            for dc in digest_calls:
                db.save_agent_output(
                    run_id, dc["name"], dc.get("model", "unknown"),
                    dc["input_tokens"], dc["output_tokens"], 0, dc["cost_usd"], {},
                )
                digest_cost += dc["cost_usd"]

            set_stage("Running AI recommendation (Bull/Bear/Skeptics/Judge)…")
            pipeline_result = run_pipeline(run_id, ticker, bundle, starting_cost_usd=digest_cost)
            db.create_outcome(run_id, bundle["price"]["current_price"])

        set_stage("Finalizing dashboard…")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        bundle_path = os.path.join(OUTPUT_DIR, f"{ticker}.json")
        with open(bundle_path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2)

        dashboard_name = f"{ticker}_dashboard.html"
        with open(os.path.join(OUTPUT_DIR, dashboard_name), "w", encoding="utf-8") as f:
            f.write(build_dashboard(bundle, pipeline_result))
        ensure_vendored_assets(OUTPUT_DIR)

        with _jobs_lock:
            _jobs[job_id].update(status="done", dashboard_name=dashboard_name, finished_at=time.time())
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id].update(status="error", error=str(e), finished_at=time.time())

# Read once at process start (same lifetime as PAGE_HEAD itself, which this
# feeds into) -- see dashboard.generate_dashboard.load_built_assets() for
# why a missing/unbuilt webui/ raises loudly here rather than rendering a
# page with no styling.
_built = load_built_assets()

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
<meta name="apple-mobile-web-app-title" content="ADELE">
<link rel="icon" type="image/png" href="/assets/icon.png" media="(prefers-color-scheme: light)">
<link rel="icon" type="image/png" href="/assets/icon-dark.png" media="(prefers-color-scheme: dark)">
<link rel="apple-touch-icon" href="/assets/icon.png">
<title>ADELE</title>
<script>
(function () {{
  try {{
    var saved = localStorage.getItem('stockllm-theme');
    if (saved) {{ document.documentElement.setAttribute('data-theme', saved); }}
  }} catch (e) {{}}
}})();
</script>
<!-- Absolute, not relative: PAGE_HEAD is shared by routes at different
     path depths ("/", "/login", "/progress/<job_id>") -- a relative
     "assets/..." resolves against each page's own URL, so it'd only
     happen to reach the real /assets/ route from a single-segment path.
     An absolute /assets/... path is safe under Ingress too: Ingress
     strips its own dynamic prefix before forwarding, so Flask always sees
     the plain /assets/... path either way (see static_assets() below). -->
<link rel="stylesheet" href="/assets/dist/{_built['css']}">
<style>
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
    <h2>ADELE</h2>
    <div class="card-sub">Enter the password to continue.</div>
    {error_html}
    <form method="post" action="/login">
      <input type="hidden" name="next" value="{esc(_safe_next_path(next_path))}">
      <div class="form-row">
        <label for="password">Password</label>
        <input type="password" id="password" name="password" required>
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
    <h2>ADELE</h2>
    <div class="card-sub">Pick a ticker to research. Not financial advice.</div>
    {error_html}
    <form method="post" action="{prefix}/run" onsubmit="this.querySelector('button').disabled=true; this.querySelector('button').textContent='Running…';">
      <div class="form-row">
        <label for="ticker">Ticker symbol</label>
        <input type="text" id="ticker" name="ticker" placeholder="e.g. AAPL" maxlength="10" required>
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

    # Everything here is a fast, synchronous pre-check -- deliberately kept
    # in front of the async job below (not folded into _run_job) so a
    # missing API key or an already-exhausted spend limit is reported
    # immediately as a form error, not after the user has waited through a
    # whole data-fetch cycle only to learn the run couldn't have completed
    # anyway. Ticket-doesn't-exist and pipeline failures, by contrast,
    # genuinely can't be known until the real work has started -- those
    # surface as a job error on the progress page instead.
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

        db.init_db()
        spent = get_monthly_spend()
        if spent >= MONTHLY_SPEND_LIMIT_USD:
            return _render_form(
                error=f"Monthly spend limit reached (${spent:.2f} / ${MONTHLY_SPEND_LIMIT_USD:.2f}). "
                      "Raise it in this add-on's Configuration tab, or use Dry run."
            ), 400

    with _jobs_lock:
        _prune_old_jobs()
        job_id = secrets.token_urlsafe(12)
        _jobs[job_id] = {
            "status": "running", "stage": "Starting…", "ticker": ticker,
            "dry_run": dry_run, "dashboard_name": None, "error": None, "finished_at": None,
        }

    threading.Thread(target=_run_job, args=(job_id, ticker, dry_run), daemon=True).start()
    return redirect(f"{_ingress_prefix()}/progress/{job_id}")


def _render_progress(job_id: str, ticker: str):
    prefix = _ingress_prefix()
    return f"""{PAGE_HEAD}
<div class="sticky-top">
  <div class="topbar">
    <div>
      <h1>{esc(ticker)} — Researching…</h1>
      <div class="meta" id="progress-stage">Starting…</div>
    </div>
  </div>
</div>
<div class="wrap">
  <div class="hero">
    <div class="skeleton-block" style="height:44px;width:220px;border-radius:8px;"></div>
    <div class="skeleton-block" style="height:20px;width:140px;border-radius:6px;margin-top:12px;"></div>
  </div>
  <div class="kpi-row cols-4">
    <div class="stat-tile"><div class="skeleton-block" style="height:12px;width:60%;border-radius:4px;"></div><div class="skeleton-block" style="height:24px;width:75%;border-radius:4px;margin-top:8px;"></div></div>
    <div class="stat-tile"><div class="skeleton-block" style="height:12px;width:60%;border-radius:4px;"></div><div class="skeleton-block" style="height:24px;width:75%;border-radius:4px;margin-top:8px;"></div></div>
    <div class="stat-tile"><div class="skeleton-block" style="height:12px;width:60%;border-radius:4px;"></div><div class="skeleton-block" style="height:24px;width:75%;border-radius:4px;margin-top:8px;"></div></div>
    <div class="stat-tile"><div class="skeleton-block" style="height:12px;width:60%;border-radius:4px;"></div><div class="skeleton-block" style="height:24px;width:75%;border-radius:4px;margin-top:8px;"></div></div>
  </div>
  <div class="grid">
    <div class="card"><div class="skeleton-block" style="height:16px;width:35%;border-radius:4px;margin-bottom:14px;"></div><div class="skeleton-block" style="height:160px;width:100%;border-radius:8px;"></div></div>
    <div class="card"><div class="skeleton-block" style="height:16px;width:45%;border-radius:4px;margin-bottom:14px;"></div><div class="skeleton-block" style="height:160px;width:100%;border-radius:8px;"></div></div>
    <div class="card full"><div class="skeleton-block" style="height:16px;width:25%;border-radius:4px;margin-bottom:14px;"></div><div class="skeleton-block" style="height:120px;width:100%;border-radius:8px;"></div></div>
  </div>
  <div id="progress-error" class="error-box" style="display:none;"></div>
</div>
<script>
(function () {{
  var statusUrl = "{prefix}/progress/{job_id}/status";
  var stageEl = document.getElementById('progress-stage');
  var errEl = document.getElementById('progress-error');
  function poll() {{
    fetch(statusUrl).then(function (r) {{ return r.json(); }}).then(function (data) {{
      if (data.status === 'done') {{
        window.location = "{prefix}/output/" + data.dashboard_name;
        return;
      }}
      if (data.status === 'error') {{
        stageEl.textContent = 'Something went wrong.';
        errEl.textContent = data.error;
        errEl.style.display = 'block';
        return;
      }}
      stageEl.textContent = data.stage;
      setTimeout(poll, 900);
    }}).catch(function () {{ setTimeout(poll, 1500); }});
  }}
  poll();
}})();
</script>
{PAGE_TAIL}"""


@app.route("/progress/<job_id>")
def progress_page(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return _render_form(error="That run wasn't found (it may have finished a while ago, or the add-on restarted)."), 404
    return _render_progress(job_id, job["ticker"])


@app.route("/progress/<job_id>/status")
def progress_status(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"status": "error", "error": "Run not found."}), 404
    return jsonify({
        "status": job["status"], "stage": job["stage"],
        "dashboard_name": job["dashboard_name"], "error": job["error"],
    })


@app.route("/output/<path:filename>")
def output_file(filename):
    return send_from_directory(OUTPUT_DIR, filename)


# Serves dashboard/assets/ (dist/, icon.png, ...) directly for pages that
# aren't inside an OUTPUT_DIR run folder -- namely
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
