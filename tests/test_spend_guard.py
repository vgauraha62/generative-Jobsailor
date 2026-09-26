"""Spend guard: meter, 50% halt, probe-failure tolerance, exit 4."""
import io
import json
import sys
import unittest.mock as mock


def _key_payload(usage, limit):
    return json.dumps({"data": {"usage": usage, "limit": limit}}).encode()


def test_spend_meter(monkeypatch):
    import gemini_api as ga
    import urllib.request as _url
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    def fake_open(req, timeout=15):
        assert "auth/key" in req.full_url
        return io.BytesIO(_key_payload(62.5, 100))
    monkeypatch.setattr(_url, "urlopen", fake_open)
    assert ga.openrouter_spend() == {"usage": 62.5, "limit": 100.0, "pct": 0.625}


def test_spend_no_key_or_zero_limit(monkeypatch):
    import gemini_api as ga
    import urllib.request as _url
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert ga.openrouter_spend() is None
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    def fake_open(req, timeout=15):
        return io.BytesIO(_key_payload(0, 0))
    monkeypatch.setattr(_url, "urlopen", fake_open)
    assert ga.openrouter_spend() is None  # ponytail: $0-limit guard, no div-by-zero


def test_spend_probe_failure_is_none(monkeypatch):
    import gemini_api as ga
    import urllib.request as _url
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")

    def boom(req, timeout=15):
        raise OSError("net down")
    monkeypatch.setattr(_url, "urlopen", boom)
    assert ga.openrouter_spend() is None


def _load_aj():
    fd = mock.MagicMock()
    fd.current_url = "https://www.naukri.com/mnjuser/profile"
    with mock.patch("selenium.webdriver.Firefox", return_value=fd), \
         mock.patch("selenium.webdriver.firefox.service.Service"), \
         mock.patch("selenium.webdriver.firefox.firefox_profile.FirefoxProfile"), \
         mock.patch("selenium.webdriver.firefox.options.Options"), \
         mock.patch("shutil.which", return_value="/usr/local/bin/geckodriver"):
        if "apply_jobs" in sys.modules:
            del sys.modules["apply_jobs"]
        import apply_jobs as aj
        aj.driver = fd
        return aj


def test_main_spend_halt_exit4(tmp_path):
    aj = _load_aj()
    import argparse
    from reporting import JobResult
    args = argparse.Namespace(live=False, types=["python"])
    res = JobResult(status="applied", job_type="python", url="https://u", path_taken="chat_widget")
    with mock.patch.object(argparse.ArgumentParser, "parse_args", return_value=args), \
         mock.patch.object(aj, "load_candidate_profile", return_value={}), \
         mock.patch.object(aj, "find_sentinels", return_value=[]), \
         mock.patch("gemini_api.health_check", return_value={"ok": True, "model": "m"}), \
         mock.patch.object(aj, "load_visited", return_value={}), \
         mock.patch.object(aj, "load_budget", return_value={"day": "x", "calls_used": 0}), \
         mock.patch.object(aj, "budget_ok", return_value=True), \
         mock.patch.object(aj, "collect_job_urls_for", return_value=(["https://u"] * 21, {"total_links_captured": 21, "net_new_actionable_urls": 21})), \
         mock.patch.object(aj, "process_job", return_value=res), \
         mock.patch.object(aj, "mark_visited"), \
         mock.patch.object(aj, "save_visited", side_effect=lambda v: v.update({"https://u": {"attempts": 1}})), \
         mock.patch.object(aj, "write_capture_report", return_value="cap"), \
         mock.patch.object(aj, "write_visit_report", return_value="vis"), \
         mock.patch.object(aj, "write_forms_report", return_value="frm"), \
         mock.patch.object(aj, "write_manual_report", return_value="man"), \
         mock.patch("gemini_api.openrouter_spend", return_value={"usage": 60.0, "limit": 100.0, "pct": 0.6}), \
         mock.patch("time.sleep"):
        aj.REPORTS_CFG["dir"] = str(tmp_path)
        aj.DRY_RUN = False
        aj.PER_TYPE_JOBS = 30
        try:
            aj.main()
            assert False, "should exit"
        except SystemExit as e:
            assert e.code == 4, e.code


def test_status_carries_spend_or_none(tmp_path):
    import asyncio
    import json as _js
    import state
    import config_loader
    import web.routes_status as rs
    fake_cfg = {
        "reports": {"dir": str(tmp_path)},
        "gemini": {"daily_call_limit": 19},
        "resume_curation": {"gemini_daily_limit": 50, "match_threshold": 0.5, "active_resume": "resumes/active.json"},
        "rag": {"daily_call_limit": 50},
        "apply": {"dry_run": True},
    }
    with mock.patch.object(state, "load_visited", return_value={}), \
         mock.patch.object(state, "load_budget", return_value={"day": "2026-08-29", "calls_used": 0}), \
         mock.patch.object(state, "load_curation_budget", return_value={"day": "2026-08-29", "calls_used": 0}), \
         mock.patch("candidate_profile.load_candidate_profile", return_value={}), \
         mock.patch("candidate_profile.find_sentinels", return_value=[]), \
         mock.patch.object(config_loader, "load_config", return_value=fake_cfg), \
         mock.patch("gemini_api.openrouter_spend", return_value={"usage": 1.5, "limit": 100.0, "pct": 0.015}):
        out = asyncio.run(rs.get_status())
        assert out["budgets"]["openrouter"] == {"usage": 1.5, "limit": 100.0, "pct": 0.015}
    with mock.patch.object(state, "load_visited", return_value={}), \
         mock.patch.object(state, "load_budget", return_value={"day": "2026-08-29", "calls_used": 0}), \
         mock.patch.object(state, "load_curation_budget", return_value={"day": "2026-08-29", "calls_used": 0}), \
         mock.patch("candidate_profile.load_candidate_profile", return_value={}), \
         mock.patch("candidate_profile.find_sentinels", return_value=[]), \
         mock.patch.object(config_loader, "load_config", return_value=fake_cfg), \
         mock.patch("gemini_api.openrouter_spend", return_value=None):
        out = asyncio.run(rs.get_status())
        assert out["budgets"]["openrouter"] is None
        assert "openrouter" in _js.dumps(out["budgets"])  # key present even when unconfigured
