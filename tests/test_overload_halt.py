"""Overload halt: persistent 503 raises through swallow-handlers; main breaks, writes reports, exits 3."""
import sys
import unittest.mock as mock


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


def test_process_job_reraises_overload():
    aj = _load_aj()
    from gemini_api import ModelOverloaded
    with mock.patch.object(aj, "_process_job_inner", side_effect=ModelOverloaded("boom")):
        try:
            aj.process_job("https://u", "python-jobs")
            assert False, "should raise"
        except ModelOverloaded:
            pass


def test_chat_loop_reraises_overload():
    aj = _load_aj()
    from gemini_api import ModelOverloaded
    with mock.patch.object(aj, "application_status", return_value=None), \
         mock.patch.object(aj, "the_success_markers", return_value=False), \
         mock.patch.object(aj, "_current_question_signature", return_value="text:Q"), \
         mock.patch.object(aj, "_has_actionable_chat_input", return_value=True), \
         mock.patch.object(aj, "answer_radio_questions", side_effect=ModelOverloaded("boom")), \
         mock.patch.object(aj, "answer_text_question", return_value=False), \
         mock.patch("time.sleep"):
        try:
            aj.run_chat_widget_loop()
            assert False, "should raise"
        except ModelOverloaded:
            pass


def test_main_halts_exit3(tmp_path):
    aj = _load_aj()
    from gemini_api import ModelOverloaded
    import argparse
    args = argparse.Namespace(live=False, types=["python"])
    with mock.patch.object(argparse.ArgumentParser, "parse_args", return_value=args), \
         mock.patch.object(aj, "load_candidate_profile", return_value={}), \
         mock.patch.object(aj, "find_sentinels", return_value=[]), \
         mock.patch("gemini_api.health_check", return_value={"ok": True, "model": "m"}), \
         mock.patch.object(aj, "load_visited", return_value={}), \
         mock.patch.object(aj, "load_budget", return_value={"day": "x", "calls_used": 0}), \
         mock.patch.object(aj, "budget_ok", return_value=True), \
         mock.patch.object(aj, "collect_job_urls_for", return_value=(["https://u"], {"total_links_captured": 1, "net_new_actionable_urls": 1})), \
         mock.patch.object(aj, "process_job", side_effect=ModelOverloaded("model overloaded after retries: 503")), \
         mock.patch.object(aj, "write_capture_report", return_value="cap"), \
         mock.patch("time.sleep"):
        aj.REPORTS_CFG["dir"] = str(tmp_path)
        try:
            aj.main()
            assert False, "should exit"
        except SystemExit as e:
            assert e.code == 3, e.code


def test_per_user_budget_shims_accept_tz(monkeypatch):
    import os
    monkeypatch.setenv("USER_ID", "1")
    aj = _load_aj()
    import state as _st
    assert _st.load_curation_budget("Asia/Kolkata")["day"]
    assert _st.load_budget("Asia/Kolkata")["day"]
    assert _st.load_curation_budget()["day"]
    monkeypatch.undo()
    if "apply_jobs" in sys.modules:
        del sys.modules["apply_jobs"]
