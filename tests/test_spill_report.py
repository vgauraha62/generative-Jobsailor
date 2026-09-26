"""Spill attribution: provider stamped per answer; switch + agreement reported."""
import sys
import unittest.mock as mock


def test_last_provider_gemini_and_spill(monkeypatch):
    import gemini_api as ga
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    fake_resp = mock.MagicMock()
    fake_resp.text = "hi"
    fake_models = mock.MagicMock()
    fake_models.generate_content.return_value = fake_resp
    with mock.patch.object(ga, "client", mock.MagicMock(models=fake_models)):
        assert ga._generate("q") == "hi"
        assert ga.last_provider == "gemini"
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("OPENROUTER_MODEL", "m")
    with mock.patch.object(ga, "openrouter_complete", return_value="spilled"):
        assert ga._spillover("q") == "spilled"
        assert ga.last_provider == "openrouter"


def test_forms_summary_spillover_block():
    from reporting import forms_items, build_visit_summary, spillover_block, JobResult
    r1 = JobResult(status="applied", job_type="python-jobs", url="https://u1", path_taken="chat_widget")
    r1.chat_transcript = [
        {"q_idx": 1, "type": "radio", "q": "Q1", "options": ["1. A"], "answer": "1", "provider": "gemini", "timestamp": "2026-09-26T10:00:00"},
        {"q_idx": 2, "type": "text", "q": "Q2", "options": None, "answer": "X", "provider": "openrouter", "timestamp": "2026-09-26T10:01:00"},
    ]
    r2 = JobResult(status="review", job_type="python-jobs", url="https://u2", path_taken="full_form")
    r2.form_plan = [{"label": "Name", "type": "text", "answer": "A", "required": True, "answered": True, "provider": "openrouter"}]
    items = forms_items([r1, r2], "run9")
    assert [i["provider"] for i in items] == ["gemini", "openrouter", "openrouter"]
    s = build_visit_summary([r1, r2])
    assert (s["answers_gemini"], s["answers_openrouter"]) == (1, 2)
    sb = spillover_block([r1, r2])
    assert sb == {"happened": True, "answers_via_openrouter": 2, "first_spill_at": "2026-09-26T10:01:00"}
    sb0 = spillover_block([])
    assert sb0 == {"happened": False, "answers_via_openrouter": 0, "first_spill_at": None}


def test_bard_threads_preset_caps():
    import gemini_api as ga
    seen = {}
    def fake_gen(q, max_tokens=None):
        seen["cap"] = max_tokens
        return "ok"
    with mock.patch.object(ga, "_generate", side_effect=fake_gen), \
         mock.patch("state.load_budget", return_value={"day": "x", "calls_used": 0}), \
         mock.patch("state.record_gemini_call"):
        assert ga.bard_flash_response("q") == "ok" and seen["cap"] == 50
        assert ga.bard_flash_response("q", preset="form") == "ok" and seen["cap"] == 500


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


def test_history_agreement_extras():
    aj = _load_aj()
    from reporting import JobResult
    r1 = JobResult(status="failed", job_type="python-jobs", url="https://x/job-listings-a-11111", path_taken="full_form", reason="no form fields found")
    r2 = JobResult(status="failed", job_type="python-jobs", url="https://x/job-listings-b-22222", path_taken="full_form", reason="no form fields found")
    with mock.patch.object(aj, "_fetch_history_applied", return_value={"11111", "99999"}):
        flips, pending, agreement = aj._apply_history_verdict([r1, r2])
    assert (flips, pending) == (1, 2)
    assert r1.status == "applied" and r1.verified == "history"
    assert agreement == {"claimed_applied": 1, "confirmed": 1, "extras_on_history": 1}


def test_llm_provider_defaults_gemini():
    aj = _load_aj()
    import gemini_api as ga
    ga.last_provider = None
    assert aj._llm_provider() == "gemini"
    ga.last_provider = "openrouter"
    assert aj._llm_provider() == "openrouter"
    ga.last_provider = "gemini"


def test_history_extracts_jobids_not_listings():
    aj = _load_aj()

    class _A:
        def __init__(self, href):
            self._href = href

        def get_attribute(self, k):
            return self._href

    anchors = [
        _A("https://www.naukri.com/ai-interview-questions/question-bank?jobId=080926000235&utmTerm=x"),
        _A("https://www.naukri.com/ai-interview-questions/question-bank?jobId=110926909069&utmTerm=x"),
        _A("https://www.naukri.com/"),
    ]

    def find(by, sel):
        if "jobId=" in sel:
            return anchors
        return []  # no pager -> single page

    aj.driver.get = mock.MagicMock()
    aj.driver.find_elements = find
    aj.driver.execute_script = mock.MagicMock()
    with mock.patch("time.sleep"):
        found = aj._fetch_history_applied(max_pages=5)
    assert found == {"080926000235", "110926909069"}, found
