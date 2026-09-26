import json
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

def test_status_includes_run_state_and_gemini_health(tmp_path):
    import state, config_loader, web.routes_status as rs
    fake_cfg = {
        "reports": {"dir": str(tmp_path)},
        "gemini": {"daily_call_limit": 19},
        "resume_curation": {"gemini_daily_limit": 50, "match_threshold": 0.5, "active_resume": "resumes/active.json"},
        "apply": {"dry_run": True},
    }
    lock = tmp_path / "run.lock"
    lock.write_text(json.dumps({"run_id": "20260829_123456", "types": ["python-jobs"], "live": True, "status": "running"}))
    with patch.object(state, "load_visited", return_value={}), \
         patch.object(state, "load_budget", return_value={"day": "2026-08-29", "calls_used": 0}), \
         patch.object(state, "load_curation_budget", return_value={"day": "2026-08-29", "calls_used": 0}), \
         patch("candidate_profile.load_candidate_profile", return_value={}), \
         patch("candidate_profile.find_sentinels", return_value=[]), \
         patch.object(config_loader, "load_config", return_value=fake_cfg):
        out = asyncio.run(rs.get_status())
        assert "run_state" in out and out["run_state"]["running"] is True and out["run_state"]["live"] is True
        assert "gemini_health" in out

def test_run_start_live_string_coercion(tmp_path):
    import web.routes_run as rr
    from unittest.mock import patch
    # ensure clean lock
    if rr.RUN_LOCK.exists():
        rr.RUN_LOCK.unlink(missing_ok=True)
    if rr.RUN_STATE.exists():
        rr.RUN_STATE.unlink(missing_ok=True)
    orig_popen = patch("subprocess.Popen")
    with patch.object(rr, "_load_cfg", return_value={"search": {"max_run_types": 3}, "reports": {"dir": "reports"}}), \
         patch("candidate_profile.load_candidate_profile", return_value={}), \
         patch("candidate_profile.find_sentinels", return_value=[]), \
         patch("subprocess.Popen") as mock_pop, \
         patch("gemini_api.health_check", return_value={"ok": True, "model": "x"}):
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.returncode = None
        mock_proc.wait = MagicMock()
        mock_proc.poll = MagicMock(return_value=None)
        mock_pop.return_value = mock_proc
        out = asyncio.run(rr.start_run({"types": ["python"], "live": "true"}))
        assert out["live"] is True
        # cleanup
        if rr.RUN_LOCK.exists():
            rr.RUN_LOCK.unlink(missing_ok=True)
        if rr.RUN_STATE.exists():
            try: rr.RUN_STATE.unlink(missing_ok=True)
            except: pass

def test_early_curation_budget_skips(tmp_path):
    import sys
    from unittest.mock import patch, MagicMock
    # need to mock driver creation
    fake_driver = MagicMock()
    with patch("selenium.webdriver.Firefox", return_value=fake_driver), \
         patch("selenium.webdriver.firefox.service.Service"), \
         patch("selenium.webdriver.firefox.firefox_profile.FirefoxProfile"), \
         patch("selenium.webdriver.firefox.options.Options"), \
         patch("shutil.which", return_value="/usr/local/bin/geckodriver"):
        if "apply_jobs" in sys.modules:
            del sys.modules["apply_jobs"]
        import apply_jobs as aj
        aj.driver = fake_driver
        # budget exhausted
        with patch("apply_jobs.load_curation_budget", return_value={"day": "2026-08-29", "calls_used": 50}), \
             patch("apply_jobs.curation_budget_ok", return_value=False):
            c, p, rp, us = aj._maybe_curate_and_upload("url", "jd text")
            assert p is False and c is None

def test_visit_screenshot_captured_on_failure():
    import sys
    from unittest.mock import patch, MagicMock
    fake_driver = MagicMock()
    fake_driver.save_screenshot = MagicMock(return_value=None)
    # make stat size large
    with patch("selenium.webdriver.Firefox", return_value=fake_driver), \
         patch("selenium.webdriver.firefox.service.Service"), \
         patch("selenium.webdriver.firefox.firefox_profile.FirefoxProfile"), \
         patch("selenium.webdriver.firefox.options.Options"), \
         patch("shutil.which", return_value="/usr/local/bin/geckodriver"):
        if "apply_jobs" in sys.modules:
            del sys.modules["apply_jobs"]
        import apply_jobs as aj
        aj.driver = fake_driver
        # mock Path stat
        with patch("pathlib.Path.mkdir"), \
             patch("pathlib.Path.stat", return_value=MagicMock(st_size=5000)):
            ss = aj._capture_visit_screenshot("test_tag", "20260829_000000")
            assert ss is not None and "visit_test_tag" in ss

def test_gemini_quota_spills_to_openrouter(monkeypatch):
    import gemini_api as ga
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_MODEL", "m")
    def fake_gen(q, max_tokens=None):
        raise Exception("429 RESOURCE_EXHAUSTED quota 20")
    with patch.object(ga, "_generate", side_effect=fake_gen), \
         patch.object(ga, "openrouter_complete", return_value="spilled text") as mock_or, \
         patch("state.load_budget", return_value={"day": "2026-08-29", "calls_used": 0}), \
         patch("state.record_gemini_call"), \
         patch("time.sleep"):
        out = ga.bard_flash_response("q", timeout=1)
        assert out == "spilled text"
        assert mock_or.call_count == 1

def test_gemini_quota_no_spill_target_skips(monkeypatch):
    import gemini_api as ga
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    def fake_gen(q, max_tokens=None):
        raise Exception("429 RESOURCE_EXHAUSTED quota 20")
    with patch.object(ga, "_generate", side_effect=fake_gen), \
         patch("state.load_budget", return_value={"day": "2026-08-29", "calls_used": 0}), \
         patch("state.record_gemini_call"), \
         patch("time.sleep"):
        assert ga.bard_flash_response("q", timeout=1) == ""

def test_gemini_overload_halts_run():
    import gemini_api as ga
    calls = {"n": 0}
    def fake_generate(q, max_tokens=None):
        calls["n"] += 1
        raise Exception("503 UNAVAILABLE high demand try again later")
    with patch.object(ga, "_generate", side_effect=fake_generate), \
         patch("state.load_budget", return_value={"day": "2026-08-29", "calls_used": 0}), \
         patch("state.record_gemini_call"), \
         patch("time.sleep"):
        try:
            ga.bard_flash_response("q", timeout=1)
            assert False, "should raise"
        except ga.ModelOverloaded:
            pass
        assert calls["n"] == 3  # initial + 2 retries

def test_gemini_classify():
    import gemini_api as ga
    assert ga._classify(Exception("429 quota billing exhausted")) == "quota"
    assert ga._classify(Exception("503 UNAVAILABLE high demand")) == "overload"
    assert ga._classify(Exception("401 unauthenticated")) == "other"

def test_gemini_health_check_ok():
    import gemini_api as ga
    with patch.object(ga, "_generate", return_value="pong"):
        hk = ga.health_check(timeout=1)
        assert hk["ok"] is True

def test_gemini_auth_no_retry():
    import gemini_api as ga
    def fake_gen(q, max_tokens=None):
        raise Exception("401 unauthenticated api key invalid")
    with patch.object(ga, "_generate", side_effect=fake_gen), \
         patch("state.load_budget", return_value={"day": "2026-08-29", "calls_used": 0}), \
         patch("state.record_gemini_call"), \
         patch("time.sleep") as mock_sleep:
        out = ga.bard_flash_response("q", timeout=1)
        assert out == ""
        mock_sleep.assert_not_called()
