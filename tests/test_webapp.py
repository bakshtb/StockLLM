"""
Tests for webapp/app.py's Flask routes. Never hits a real external API --
data.bundle.build_research_bundle and agents.pipeline.run_pipeline are
mocked at every call site (both are imported by name into webapp.app's
namespace via `from ... import ...`, so the patch target is
webapp.app.build_research_bundle / webapp.app.run_pipeline, not the
original module's copy -- patching the original wouldn't reach the name
webapp.app actually calls).

/run is async (see HANDOFF.md item 44): it starts a background thread and
redirects to /progress/<job_id> almost immediately, rather than blocking
for the whole pipeline duration. The `sync_background_jobs` autouse
fixture below makes that thread run synchronously within the request
itself, so most tests here can still assert on the *outcome* (dashboard
written, job status "done"/"error") without any real waiting or polling --
except TestAsyncBackgroundExecution, which deliberately restores real
threading to prove the async behavior itself (not just its result) works.

Two of these classes directly codify real bugs from this session (see
HANDOFF.md): the Ingress path-prefix bug (#28) and the ticker-validation
security boundary that was manually fuzzed by hand throughout the session.
"""

import re
import threading as real_threading
import time

import pytest

import webapp.app as wa

# Captured once, here, before any fixture/test can monkeypatch
# wa.threading.Thread (see sync_background_jobs below): `real_threading` is
# the exact same module object as `wa.threading` (import threading is a
# process-wide singleton, not a copy), so `real_threading.Thread` would
# otherwise be a *live* attribute lookup that reads back whatever the
# module's Thread currently is -- including an already-patched fake -- not
# a snapshot of the original class. Binding the class itself to a plain
# name here is what actually survives later mutation.
_REAL_THREAD_CLASS = real_threading.Thread


@pytest.fixture(autouse=True)
def webapp_output_dir(monkeypatch, tmp_path):
    """Every webapp test writes into a throwaway directory instead of the
    real repo output/ folder. autouse=True since every test in this file
    goes through routes that touch OUTPUT_DIR one way or another."""
    monkeypatch.setattr(wa, "OUTPUT_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def sync_background_jobs(monkeypatch):
    """Runs _run_job() synchronously, inline within the /run request that
    starts it, instead of on a real background thread -- keeps every test
    in this file deterministic (no polling/timing needed) while still
    exercising the exact same job-registry code path production uses.
    TestAsyncBackgroundExecution below explicitly restores real threading
    to verify the async behavior itself, not just its eventual result."""
    class ImmediateThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(wa.threading, "Thread", ImmediateThread)


@pytest.fixture(autouse=True)
def clear_jobs():
    """_jobs is a module-level dict shared across the whole test session --
    clear it before each test so one test's job_id/state can never leak
    into another's assertions."""
    wa._jobs.clear()
    yield
    wa._jobs.clear()


@pytest.fixture
def client():
    wa.app.config.update(TESTING=True)
    return wa.app.test_client()


def _fake_bundle(ticker="AAPL"):
    return {"ticker": ticker, "fetched_at": "2026-01-01T00:00:00Z", "price": {"current_price": 180.0}}, []


def _run_and_get_status(client, data, headers=None):
    """POSTs /run (job runs synchronously under the sync_background_jobs
    fixture), follows the redirect to /progress/<job_id>/status, and
    returns (run_response, status_json). Asserts the redirect actually
    points at /progress/, not the old direct-to-dashboard redirect."""
    resp = client.post("/run", data=data, headers=headers or {})
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert "/progress/" in location
    status_resp = client.get(f"{location}/status")
    assert status_resp.status_code == 200
    return resp, status_resp.get_json()


class TestIndexPage:
    def test_get_root_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"StockLLM" in resp.data

    def test_recent_runs_empty_state(self, client):
        resp = client.get("/")
        assert b"No runs yet" in resp.data

    def test_ios_home_screen_meta_tags_present(self, client):
        # PWA/"Add to Home Screen" support -- meaningful mainly via the
        # add-on's direct port (config.yaml's `ports`), since an Ingress
        # URL's token prefix isn't stable enough to bookmark.
        html = client.get("/").get_data(as_text=True)
        assert '<meta name="apple-mobile-web-app-capable" content="yes">' in html
        assert '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">' in html
        assert '<meta name="apple-mobile-web-app-title" content="StockLLM">' in html
        assert '<link rel="apple-touch-icon" href="/assets/icon.png">' in html


class TestStaticAssetsRoute:
    """The index page isn't inside an OUTPUT_DIR run folder, so it can't
    reuse dashboard/assets.ensure_vendored_assets() the way generated
    dashboards do -- it needs a real route serving dashboard/assets/
    directly instead, for its relative "assets/icon.png" reference to
    resolve to anything."""

    def test_icon_served_from_dashboard_assets_dir(self, client):
        resp = client.get("/assets/icon.png")
        assert resp.status_code == 200
        assert resp.content_type == "image/png"

    def test_unknown_asset_404s_not_500s(self, client):
        resp = client.get("/assets/does-not-exist.js")
        assert resp.status_code == 404


class TestTickerValidation:
    """The ticker becomes part of an output filename -- this is the actual
    security boundary against path traversal, not just input validation."""

    @pytest.mark.parametrize("malicious_ticker", [
        "../../etc/passwd",
        "../../../etc/passwd",
        "$(rm -rf /)",
        "AAPL/../../etc",
        "",
        "A" * 50,  # too long
    ])
    def test_malicious_or_invalid_ticker_rejected(self, client, malicious_ticker):
        resp = client.post("/run", data={"ticker": malicious_ticker, "dry_run": "on"})
        assert resp.status_code == 400
        assert b"valid ticker" in resp.data

    def test_valid_ticker_with_dot_accepted(self, monkeypatch, client):
        # e.g. BRK.B -- must not be rejected by the same regex that blocks
        # path traversal.
        monkeypatch.setattr(wa, "build_research_bundle", lambda ticker, run_digests, on_stage=None: _fake_bundle(ticker))
        resp = client.post("/run", data={"ticker": "BRK.B", "dry_run": "on"})
        assert resp.status_code == 302


class TestDryRun:
    def test_successful_dry_run_redirects_to_dashboard(self, monkeypatch, client):
        monkeypatch.setattr(wa, "build_research_bundle", lambda ticker, run_digests, on_stage=None: _fake_bundle(ticker))
        _, status = _run_and_get_status(client, {"ticker": "AAPL", "dry_run": "on"})
        assert status["status"] == "done"
        assert status["dashboard_name"] == "AAPL_dashboard.html"

    def test_dry_run_never_calls_run_pipeline(self, monkeypatch, client):
        monkeypatch.setattr(wa, "build_research_bundle", lambda ticker, run_digests, on_stage=None: _fake_bundle(ticker))

        def _fail_if_called(*a, **kw):
            raise AssertionError("run_pipeline should not be called on a dry run")
        monkeypatch.setattr(wa, "run_pipeline", _fail_if_called)

        _, status = _run_and_get_status(client, {"ticker": "AAPL", "dry_run": "on"})
        assert status["status"] == "done"  # would be "error" if run_pipeline had actually been called

    def test_dashboard_file_actually_written(self, monkeypatch, client, webapp_output_dir):
        monkeypatch.setattr(wa, "build_research_bundle", lambda ticker, run_digests, on_stage=None: _fake_bundle(ticker))
        client.post("/run", data={"ticker": "AAPL", "dry_run": "on"})
        assert (webapp_output_dir / "AAPL_dashboard.html").exists()
        assert (webapp_output_dir / "AAPL.json").exists()

    def test_invalid_ticker_symbol_from_fetch_layer(self, monkeypatch, client):
        # Unlike a malformed ticker (rejected synchronously by TICKER_RE
        # before a job even exists), "no such ticker" can only be
        # discovered by actually trying to fetch it -- that happens inside
        # the background job, so it surfaces as a job error, not a
        # synchronous 400.
        def _raise_value_error(ticker, run_digests, on_stage=None):
            raise ValueError(f"No price history found for ticker '{ticker}'.")
        monkeypatch.setattr(wa, "build_research_bundle", _raise_value_error)
        _, status = _run_and_get_status(client, {"ticker": "ZZZZZ", "dry_run": "on"})
        assert status["status"] == "error"
        assert "No price history" in status["error"]


class TestFullRun:
    def test_blocked_without_anthropic_api_key(self, monkeypatch, client):
        monkeypatch.setattr(wa, "build_research_bundle", lambda ticker, run_digests, on_stage=None: _fake_bundle(ticker))
        monkeypatch.setattr(wa, "ANTHROPIC_API_KEY", "")
        monkeypatch.setattr(wa, "QWEN_API_KEY", "sk-qwen-test-key")
        resp = client.post("/run", data={"ticker": "AAPL"})  # dry_run omitted = full run
        assert resp.status_code == 400
        assert b"ANTHROPIC_API_KEY" in resp.data

    def test_blocked_without_qwen_api_key(self, monkeypatch, client):
        monkeypatch.setattr(wa, "build_research_bundle", lambda ticker, run_digests, on_stage=None: _fake_bundle(ticker))
        monkeypatch.setattr(wa, "ANTHROPIC_API_KEY", "sk-ant-test-key")
        monkeypatch.setattr(wa, "QWEN_API_KEY", "")
        monkeypatch.setattr(wa, "GEMINI_API_KEY", "sk-gemini-test-key")
        resp = client.post("/run", data={"ticker": "AAPL"})
        assert resp.status_code == 400
        assert b"QWEN_API_KEY" in resp.data

    def test_blocked_without_gemini_api_key(self, monkeypatch, client):
        monkeypatch.setattr(wa, "build_research_bundle", lambda ticker, run_digests, on_stage=None: _fake_bundle(ticker))
        monkeypatch.setattr(wa, "ANTHROPIC_API_KEY", "sk-ant-test-key")
        monkeypatch.setattr(wa, "QWEN_API_KEY", "sk-qwen-test-key")
        monkeypatch.setattr(wa, "GEMINI_API_KEY", "")
        resp = client.post("/run", data={"ticker": "AAPL"})
        assert resp.status_code == 400
        assert b"GEMINI_API_KEY" in resp.data

    def test_succeeds_with_mocked_pipeline(self, monkeypatch, client, temp_db):
        monkeypatch.setattr(wa, "build_research_bundle", lambda ticker, run_digests, on_stage=None: _fake_bundle(ticker))
        monkeypatch.setattr(wa, "ANTHROPIC_API_KEY", "sk-ant-test-key")
        monkeypatch.setattr(wa, "QWEN_API_KEY", "sk-qwen-test-key")
        monkeypatch.setattr(wa, "GEMINI_API_KEY", "sk-gemini-test-key")
        monkeypatch.setattr(wa, "MONTHLY_SPEND_LIMIT_USD", 50.0)
        monkeypatch.setattr(wa, "get_monthly_spend", lambda: 0.0)

        fake_result = {
            "run_id": 1, "total_cost_usd": 0.05,
            "judge": {"recommendation": "hold", "confidence": 50, "reasoning_summary": "x", "key_risks": [], "data_quality_caveat": "x"},
            "bull": {"thesis": "x", "confidence": 50},
            "bear": {"thesis": "x", "confidence": 50},
            "skeptic": {"unsupported_claims": [], "data_gaps": [], "overall_data_quality": "high"},
            "skeptic_qwen": {"unsupported_claims": [], "data_gaps": [], "overall_data_quality": "high"},
            "quant_check": {"verified_claims": [], "flagged_claims": [], "note": None},
        }
        monkeypatch.setattr(wa, "run_pipeline", lambda run_id, ticker, bundle, starting_cost_usd: fake_result)

        _, status = _run_and_get_status(client, {"ticker": "AAPL"})
        assert status["status"] == "done", status.get("error")
        assert status["dashboard_name"] == "AAPL_dashboard.html"

    def test_blocked_when_over_spend_limit(self, monkeypatch, client, temp_db):
        monkeypatch.setattr(wa, "build_research_bundle", lambda ticker, run_digests, on_stage=None: _fake_bundle(ticker))
        monkeypatch.setattr(wa, "ANTHROPIC_API_KEY", "sk-ant-test-key")
        monkeypatch.setattr(wa, "QWEN_API_KEY", "sk-qwen-test-key")
        monkeypatch.setattr(wa, "GEMINI_API_KEY", "sk-gemini-test-key")
        monkeypatch.setattr(wa, "MONTHLY_SPEND_LIMIT_USD", 50.0)
        monkeypatch.setattr(wa, "get_monthly_spend", lambda: 75.0)

        resp = client.post("/run", data={"ticker": "AAPL"})
        assert resp.status_code == 400
        assert b"spend limit" in resp.data


class TestProgressPage:
    def test_progress_page_renders_with_skeleton_and_stage(self, monkeypatch, client):
        # A slow-ish fake so the page itself (not its polled status) can be
        # inspected mid-flight -- real threading here, not the sync fixture.
        monkeypatch.setattr(wa.threading, "Thread", _REAL_THREAD_CLASS)

        def _slow_bundle(ticker, run_digests, on_stage=None):
            time.sleep(0.2)
            return _fake_bundle(ticker)
        monkeypatch.setattr(wa, "build_research_bundle", _slow_bundle)

        resp = client.post("/run", data={"ticker": "AAPL", "dry_run": "on"})
        location = resp.headers["Location"]
        page = client.get(location)
        assert page.status_code == 200
        html = page.get_data(as_text=True)
        assert "skeleton-block" in html
        assert "AAPL" in html
        assert "/status" in html  # the polling script's fetch target

        # Wait for the real background thread to actually finish before
        # this test returns -- otherwise it's still running when the next
        # test's clear_jobs fixture wipes wa._jobs out from under it.
        deadline = time.time() + 5
        status = {"status": "running"}
        while time.time() < deadline and status["status"] == "running":
            status = client.get(f"{location}/status").get_json()
            time.sleep(0.02)
        assert status["status"] == "done"

    def test_unknown_job_id_404s(self, client):
        assert client.get("/progress/does-not-exist").status_code == 404
        assert client.get("/progress/does-not-exist/status").status_code == 404


class TestAsyncBackgroundExecution:
    """Every other class in this file runs _run_job() synchronously (see
    sync_background_jobs) so assertions don't need to poll -- this class
    deliberately restores real threading to prove /run itself returns
    before the work is done, not just that the eventual result is
    correct."""

    def test_run_returns_before_job_finishes_then_status_transitions_to_done(self, monkeypatch, client):
        monkeypatch.setattr(wa.threading, "Thread", _REAL_THREAD_CLASS)

        release = real_threading.Event()

        def _blocking_bundle(ticker, run_digests, on_stage=None):
            release.wait(timeout=5)
            return _fake_bundle(ticker)
        monkeypatch.setattr(wa, "build_research_bundle", _blocking_bundle)

        resp = client.post("/run", data={"ticker": "AAPL", "dry_run": "on"})
        location = resp.headers["Location"]

        # The job must still be running immediately after /run returns --
        # if this were "in progress" instead of a real assertion, a
        # regression back to synchronous /run would slip through
        # unnoticed, so this ordering is the actual point of the test.
        status = client.get(f"{location}/status").get_json()
        assert status["status"] == "running"

        release.set()
        deadline = time.time() + 5
        while time.time() < deadline:
            status = client.get(f"{location}/status").get_json()
            if status["status"] != "running":
                break
            time.sleep(0.05)
        assert status["status"] == "done"
        assert status["dashboard_name"] == "AAPL_dashboard.html"


class TestJobPruning:
    def test_prune_removes_only_old_finished_jobs(self):
        now = time.time()
        wa._jobs.update({
            "old-done": {"status": "done", "finished_at": now - wa._JOB_MAX_AGE_SECONDS - 10},
            "recent-done": {"status": "done", "finished_at": now},
            "still-running": {"status": "running", "finished_at": None},
        })
        wa._prune_old_jobs()
        assert set(wa._jobs.keys()) == {"recent-done", "still-running"}


class TestOutputFileServing:
    def test_serves_generated_file(self, monkeypatch, client, webapp_output_dir):
        (webapp_output_dir / "AAPL_dashboard.html").write_text("<html>test</html>")
        resp = client.get("/output/AAPL_dashboard.html")
        assert resp.status_code == 200
        assert b"test" in resp.data

    def test_path_traversal_on_output_route_blocked(self, client):
        resp = client.get("/output/../../../etc/passwd")
        assert resp.status_code == 404


class TestIngressPathHandling:
    """Real bug (HANDOFF.md #28): HA's Ingress proxy mounts the add-on at a
    dynamic sub-path, but the form action/redirect/links were hardcoded
    root-relative, so a submission went straight past the add-on to HA core."""

    INGRESS_PREFIX = "/api/hassio_ingress/abc123"

    def test_form_action_unprefixed_without_ingress_header(self, client):
        resp = client.get("/")
        assert b'action="/run"' in resp.data

    def test_form_action_prefixed_with_ingress_header(self, client):
        resp = client.get("/", headers={"X-Ingress-Path": self.INGRESS_PREFIX})
        assert f'action="{self.INGRESS_PREFIX}/run"'.encode() in resp.data

    def test_redirect_prefixed_with_ingress_header(self, monkeypatch, client):
        monkeypatch.setattr(wa, "build_research_bundle", lambda ticker, run_digests, on_stage=None: _fake_bundle(ticker))
        resp = client.post(
            "/run", data={"ticker": "AAPL", "dry_run": "on"},
            headers={"X-Ingress-Path": self.INGRESS_PREFIX},
        )
        assert resp.status_code == 302
        assert re.match(rf"^{re.escape(self.INGRESS_PREFIX)}/progress/[\w-]+$", resp.headers["Location"])

    def test_recent_runs_links_prefixed_with_ingress_header(self, client, webapp_output_dir):
        (webapp_output_dir / "AAPL_dashboard.html").write_text("<html></html>")
        resp = client.get("/", headers={"X-Ingress-Path": self.INGRESS_PREFIX})
        assert f'{self.INGRESS_PREFIX}/output/AAPL_dashboard.html'.encode() in resp.data


class TestDirectAccessLogin:
    """Gates config.yaml's directly-exposed port (ports: {8099/tcp: 8099})
    behind a password -- Ingress traffic (already behind HA's own login) is
    exempt, and so is every request when WEB_PASSWORD isn't configured at
    all, matching this repo's "blank = feature not configured" convention
    for every other optional credential (see config.py)."""

    def test_no_password_configured_means_no_gate(self, client):
        # WEB_PASSWORD defaults to "" -- every other test file in this repo
        # relies on this exact default, so this is the baseline every other
        # test implicitly already exercises; asserted explicitly here too.
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"StockLLM" in resp.data

    def test_unprotected_warning_shown_when_no_password_and_no_ingress(self, client):
        resp = client.get("/")
        assert b"no password set" in resp.data

    def test_unprotected_warning_absent_behind_ingress(self, client, monkeypatch):
        monkeypatch.setattr(wa, "WEB_PASSWORD", "hunter2")
        resp = client.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc123"})
        assert resp.status_code == 200
        assert b"no password set" not in resp.data

    def test_direct_access_redirected_to_login_when_password_set(self, client, monkeypatch):
        monkeypatch.setattr(wa, "WEB_PASSWORD", "hunter2")
        resp = client.get("/")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/login?next=/"

    def test_ingress_access_exempt_even_with_password_set(self, client, monkeypatch):
        # Already authenticated via HA's own login -- must not be asked
        # again just because a direct-port password also happens to be set.
        monkeypatch.setattr(wa, "WEB_PASSWORD", "hunter2")
        resp = client.get("/", headers={"X-Ingress-Path": "/api/hassio_ingress/abc123"})
        assert resp.status_code == 200
        assert b"StockLLM" in resp.data

    def test_wrong_password_rejected(self, client, monkeypatch):
        monkeypatch.setattr(wa, "WEB_PASSWORD", "hunter2")
        resp = client.post("/login", data={"password": "wrong", "next": "/"})
        assert resp.status_code == 401
        assert b"Incorrect password" in resp.data

    def test_correct_password_grants_access_and_redirects_to_next(self, client, monkeypatch):
        monkeypatch.setattr(wa, "WEB_PASSWORD", "hunter2")
        resp = client.post("/login", data={"password": "hunter2", "next": "/"})
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"
        # Session cookie now carries the login -- a follow-up request must
        # not be redirected back to /login.
        resp2 = client.get("/")
        assert resp2.status_code == 200
        assert b"StockLLM" in resp2.data

    def test_open_redirect_via_next_param_rejected(self, client, monkeypatch):
        # ?next=https://evil.example must never be honored -- would turn
        # this app's own login page into a phishing redirector.
        monkeypatch.setattr(wa, "WEB_PASSWORD", "hunter2")
        resp = client.post("/login", data={"password": "hunter2", "next": "https://evil.example/steal"})
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"

    def test_logout_clears_session_and_re_gates(self, client, monkeypatch):
        monkeypatch.setattr(wa, "WEB_PASSWORD", "hunter2")
        client.post("/login", data={"password": "hunter2", "next": "/"})
        assert client.get("/").status_code == 200  # confirms login took

        resp = client.post("/logout")
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/login"

        resp2 = client.get("/")
        assert resp2.status_code == 302  # logged out -- gated again

    def test_login_page_itself_and_assets_never_gated(self, client, monkeypatch):
        # Otherwise the login page couldn't load at all: gating /login
        # would redirect it to /login forever, and gating /assets/ would
        # break its own icon reference before anyone could log in to see it.
        monkeypatch.setattr(wa, "WEB_PASSWORD", "hunter2")
        assert client.get("/login").status_code == 200
        assert client.get("/assets/icon.png").status_code == 200

    def test_progress_route_gated_like_run(self, client, monkeypatch):
        # /progress/ isn't in _LOGIN_EXEMPT_PATH_PREFIXES -- must stay
        # behind the same gate /run already sits behind, not accidentally
        # left open when this route was added.
        monkeypatch.setattr(wa, "WEB_PASSWORD", "hunter2")
        resp = client.get("/progress/some-job-id")
        assert resp.status_code == 302
        assert resp.headers["Location"].startswith("/login")
