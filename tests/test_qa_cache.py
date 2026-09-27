"""Per-user answer cache: seed/lookup/hash gates, job-abort, NEEDS_REVIEW quarantine."""
import sys
import unittest.mock as mock


def test_remap_radio_order_safe():
    import qa_cache as qc
    hit = {"answer": "1", "options": ["1. Yes (Value: Yes)", "2. No (Value: No)"]}
    assert qc.remap_radio(hit, ["1. No (Value: No)", "2. Yes (Value: Yes)"]) == "2"
    assert qc.remap_radio(hit, ["1. Yes (Value: Yes)", "2. No (Value: No)"]) == "1"
    assert qc.remap_radio(hit, ["1. Maybe (Value: Maybe)"]) is None  # value gone
    assert qc.remap_radio({"answer": "x", "options": []}, ["1. A"]) is None


def test_empty_aborts_and_keeps_transcript():
    aj, fd = _load_aj()
    aj.driver = _radio_driver()
    aj._qa_cache = None
    import qa_cache as qc
    with mock.patch.object(aj, "bard_flash_response", return_value="  "):
        try:
            aj.answer_radio_questions(answered=set())
            assert False, "should raise"
        except qc.UnusableAnswer as e:
            assert e.reason == "empty response"
    aj._chat_transcript_buf = [{"q_idx": 1, "q": "Q0", "answer": "A0"}]
    with mock.patch.object(aj, "_process_job_inner", side_effect=qc.UnusableAnswer("Q?", "empty response")), \
         mock.patch.object(aj, "_record_error"):
        r = aj.process_job("https://u", "python-jobs")
    assert r.status == "failed" and r.error_type == "UnusableAnswer"
    assert r.chat_transcript == [{"q_idx": 1, "q": "Q0", "answer": "A0"}]


def _load_aj():
    fd = mock.MagicMock()
    fd.current_url = "https://www.naukri.com/job-listings-123"
    with mock.patch("selenium.webdriver.Firefox", return_value=fd), \
         mock.patch("selenium.webdriver.firefox.service.Service"), \
         mock.patch("selenium.webdriver.firefox.firefox_profile.FirefoxProfile"), \
         mock.patch("selenium.webdriver.firefox.options.Options"), \
         mock.patch("shutil.which", return_value="/usr/local/bin/geckodriver"):
        if "apply_jobs" in sys.modules:
            del sys.modules["apply_jobs"]
        import apply_jobs as aj
        aj.driver = fd
        return aj, fd


def test_norm_and_seed_filter(tmp_path):
    import qa_cache as qc
    assert qc.norm_q("  What IS  this? ") == "what is this?"
    forms = {"items": [
        {"q": "City?", "answer": "Pune", "type": "text", "profile_hash": "h1", "status": "applied"},
        {"q": "Bad", "answer": "NEEDS_REVIEW", "type": "text", "profile_hash": "h1", "status": "applied"},
        {"q": "Empty", "answer": "  ", "type": "text", "profile_hash": "h1", "status": "applied"},
        {"q": "", "answer": "X", "type": "text", "profile_hash": "h1", "status": "applied"},
        {"q": "Legacy", "answer": "Old", "type": "text", "status": "applied"},  # no hash -> skipped
        {"q": "Pick?", "answer": "1", "type": "radio", "options": ["1. A"], "profile_hash": "h1", "status": "applied"},
    ]}
    (tmp_path / "forms_r.json").write_text(__import__("json").dumps(forms))
    seed = qc.load_seed(str(tmp_path), "h1")
    assert set(seed) == {"city?", "pick?"}
    assert seed["city?"]["profile_hash"] == "h1"  # original hash kept, not restamped


def test_lookup_gates():
    import qa_cache as qc
    mem = {"city?": {"q": "City?", "norm": "city?", "type": "text", "options": None,
                     "answer": "Pune", "profile_hash": "h1"},
           "relocate?": {"q": "Relocate?", "norm": "relocate?", "type": "radio",
                         "options": ["1. Yes", "2. No"], "answer": "1", "profile_hash": "h1"}}
    assert qc.lookup(mem, "City?", "text", None, "h1")["answer"] == "Pune"  # exact
    assert qc.lookup(mem, "City??", "text", None, "h1")["answer"] == "Pune"  # similar
    assert qc.lookup(mem, "City?", "radio", None, "h1") is None  # type mismatch
    assert qc.lookup(mem, "City?", "text", None, "h2") is None  # stale hash
    assert qc.lookup(mem, "Relocate?", "radio", ["1. Yes", "2. No"], "h1")["answer"] == "1"
    assert qc.lookup(mem, "Relocate?", "radio", ["1. Yes"], "h1") is None  # options differ
    assert qc.lookup(mem, "Relocate?", "radio", ["1. Yes", "2. No", "3. Maybe"], "h1") is None
    assert qc.lookup(mem, "Zebra zebra zebra?", "text", None, "h1") is None  # below threshold


def test_save_quarantine_and_file(tmp_path):
    import qa_cache as qc
    c = qc.QACache(uid=None, prof_hash="h1")
    c.save("text", "Q?", None, "NEEDS_REVIEW")
    c.save("text", "Q?", None, "  ")
    assert c.mem == {}
    c.save("text", "Q?", None, "Pune")
    assert c.mem["q?"]["answer"] == "Pune"
    assert c.find("text", "Q?", None)["answer"] == "Pune"


def _radio_driver():
    fd = mock.MagicMock()

    class Lbl:
        def __init__(self, t):
            self.text = t

    class Btn:
        def __init__(self, label, value):
            self._l, self._v = label, value

        def find_element(self, *a, **k):
            m = mock.MagicMock()
            m.text = self._l
            m.get_attribute = lambda k: self._v
            return m

    def find(by, sel):
        if ".ssrc__radio-btn-container" in sel:
            return [Btn("Yes", "Yes"), Btn("No", "No")]
        if "botItem" in sel:
            m = mock.MagicMock()
            m.text = "Relocate?"
            return [m]
        return []
    fd.find_elements = find
    return fd


def test_radio_unusable_aborts():
    aj, fd = _load_aj()
    aj.driver = _radio_driver()
    aj._qa_cache = None
    import qa_cache as qc
    with mock.patch.object(aj, "bard_flash_response", return_value="NEEDS_REVIEW"):
        try:
            aj.answer_radio_questions(answered=set())
            assert False, "should raise"
        except qc.UnusableAnswer as e:
            assert e.question == "Relocate?" and e.reason == "NEEDS_REVIEW"
    with mock.patch.object(aj, "bard_flash_response", return_value="9"):
        try:
            aj.answer_radio_questions(answered=set())
            assert False, "should raise"
        except qc.UnusableAnswer as e:
            assert "invalid option" in e.reason


def test_text_unusable_aborts():
    aj, fd = _load_aj()
    m = mock.MagicMock()
    m.text = "Skills?"
    aj.driver.find_elements = lambda by, sel: [m]
    aj._qa_cache = None
    import qa_cache as qc
    with mock.patch.object(aj, "bard_flash_response", return_value="NEEDS_REVIEW"):
        try:
            aj.answer_text_question(answered=set())
            assert False, "should raise"
        except qc.UnusableAnswer:
            pass


def test_cache_hit_skips_llm():
    aj, fd = _load_aj()
    aj.driver = _radio_driver()
    import qa_cache as qc
    c = qc.QACache(uid=None, prof_hash="h")
    c.mem[qc.norm_q("Relocate?")] = {"q": "Relocate?", "norm": qc.norm_q("Relocate?"), "type": "radio",
                                     "options": ["1. Yes (Value: Yes)", "2. No (Value: No)"],
                                     "answer": "2", "profile_hash": "h"}
    aj._qa_cache = c
    with mock.patch.object(aj, "bard_flash_response", side_effect=AssertionError("LLM must not fire")), \
         mock.patch.object(aj, "WebDriverWait") as _w, \
         mock.patch("time.sleep"):
        assert aj.answer_radio_questions(answered=set()) is True
    assert aj._last_chat_qa["answer"] == "2" and aj._last_chat_qa["provider"] == "cache"


def test_abort_fails_job_not_run():
    aj, _ = _load_aj()
    import qa_cache as qc
    with mock.patch.object(aj, "_process_job_inner", side_effect=qc.UnusableAnswer("Q?", "NEEDS_REVIEW")), \
         mock.patch.object(aj, "_record_error"):
        r = aj.process_job("https://u", "python-jobs")
    assert r.status == "failed" and r.error_type == "UnusableAnswer" and "Q?" in r.reason


def _timed_loop(aj, fd, wait_outcome, markers=(), actionable=(True, True)):
    """One answered round followed by an unanswerable round; returns (save_mock, result)."""
    import time as _t
    qa = {"type": "radio", "q": "City?", "options": ["1. Yes (Value: Yes)", "2. No (Value: No)"],
          "answer": "1", "provider": "gemini"}
    calls = {"n": 0}

    def answer_radio(answered=None):
        if calls["n"] == 0:
            aj._last_chat_qa = dict(qa)
            return True
        return False

    fd.find_elements = lambda *a, **k: []
    fd.find_element = mock.MagicMock(side_effect=Exception("no body"))
    aj._qa_cache = mock.MagicMock()
    aj._last_chat_qa = {}
    patches = [
        mock.patch.object(aj, "answer_radio_questions", side_effect=answer_radio),
        mock.patch.object(aj, "answer_text_question", return_value=False),
        mock.patch.object(aj, "answer_checkbox_questions", return_value=False),
        mock.patch.object(aj, "_current_question_signature", return_value="radio:City?|Yes|No"),
        mock.patch.object(aj, "_wait_for_next_state", return_value=wait_outcome),
        mock.patch.object(aj, "_has_actionable_chat_input", side_effect=list(actionable) + [False] * 30),
        mock.patch.object(aj, "_has_checkbox_input", return_value=False),
        mock.patch.object(aj, "application_status", return_value=None),
        mock.patch.object(aj, "the_success_markers", side_effect=list(markers) + [False] * 30),
        mock.patch.object(aj, "attempt_final_submit", return_value=(False, "")),
        mock.patch.object(aj, "_capture_chat_q_screenshot", return_value=None),
        mock.patch.object(aj, "_capture_visit_screenshot", return_value=None),
        mock.patch.object(_t, "sleep", return_value=None),
    ]
    for p in patches:
        p.start()
    try:
        calls["n"] = 0
        orig_wait = aj._wait_for_next_state

        def wait_once(*a, **k):
            calls["n"] += 1
            return wait_outcome
        aj._wait_for_next_state.side_effect = wait_once
        res = aj.run_chat_widget_loop()
    finally:
        for p in patches:
            p.stop()
    return aj._qa_cache.save, res


def test_no_cache_save_when_widget_does_not_advance():
    aj, fd = _load_aj()
    save, res = _timed_loop(aj, fd, "timeout")
    save.assert_not_called()  # ponytail: same question still present — answer unconfirmed


def test_cache_save_after_next_question():
    aj, fd = _load_aj()
    save, res = _timed_loop(aj, fd, "new_question")
    save.assert_called_once()
    kw = save.call_args
    assert kw.args[1] == "City?" and kw.args[3] == "1"  # qtype, q, options, answer positionally
    assert kw.kwargs.get("provider") == "gemini" and "run_id" in kw.kwargs


def test_cache_save_after_completed_question_with_confirmation():
    aj, fd = _load_aj()
    save, res = _timed_loop(aj, fd, "success", markers=[False, True], actionable=(False,))
    save.assert_called_once()
    assert res.status == "applied"


def _write_forms(tmp_path, items):
    import json as _j
    (tmp_path / "forms_r.json").write_text(_j.dumps({"items": items}))


def _row(q="City?", answer="Pune", status="applied", accepted=True, h="h1", type="text"):
    r = {"q": q, "answer": answer, "type": type, "status": status, "profile_hash": h}
    if accepted is not True:
        r["accepted"] = accepted
    if type == "radio":
        r["options"] = ["1. A"]
    return r


def test_only_applied_rows_seed(tmp_path):
    import qa_cache as qc
    _write_forms(tmp_path, [_row("Q1?", "A1", "applied"), _row("Q2?", "A2", "failed"), _row("Q3?", "A3", "review")])
    seed = qc.load_seed(str(tmp_path), "h1")
    assert set(seed) == {"q1?"}


def test_unconfirmed_and_invalid_answers_dont_seed(tmp_path):
    import qa_cache as qc
    _write_forms(tmp_path, [_row("Q1?", "A1", "applied", accepted=False), _row("Q2?", "", "applied"),
                            _row("Q3?", "NEEDS_REVIEW", "applied")])
    assert qc.load_seed(str(tmp_path), "h1") == {}


def test_profile_hash_gates_use(tmp_path):
    import qa_cache as qc
    _write_forms(tmp_path, [_row("City?", "Pune", "applied")])
    seed = qc.load_seed(str(tmp_path), "h1")
    assert qc.lookup(seed, "City?", "text", None, "h1")["answer"] == "Pune"
    assert qc.lookup(seed, "City?", "text", None, "h2") is None


def test_forms_drops_needs_review():
    from reporting import forms_items, JobResult
    r = JobResult(status="failed", job_type="p", url="https://u", path_taken="chat_widget")
    r.chat_transcript = [{"q_idx": 1, "type": "text", "q": "Q?", "options": None,
                          "answer": "NEEDS_REVIEW", "provider": "gemini", "timestamp": "t"}]
    r.form_plan = [{"label": "L", "type": "text", "answer": "", "provider": "gemini"}]
    assert forms_items([r], "run9") == []
