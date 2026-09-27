import time
from unittest.mock import MagicMock, patch


class FakeEl:
    def __init__(self, text="", attrs=None, cls=""):
        self.text = text
        self._attrs = attrs or {}
        self._cls = cls

    def get_attribute(self, k):
        if k == "class":
            return self._cls
        return self._attrs.get(k, "")

    def find_element(self, *a, **kw):
        raise Exception("not found")

    def find_elements(self, *a, **kw):
        return []

    def is_displayed(self):
        return getattr(self, "_shown", True)

    def is_enabled(self):
        return getattr(self, "_enabled", True)

    def click(self):
        pass

    def send_keys(self, *a):
        self.sent = getattr(self, "sent", []) + list(a)


def _hidden_el():
    el = FakeEl()
    el._shown = False
    return el


def _disabled_el():
    el = FakeEl()
    el._enabled = False
    return el


def test_instruction_message_is_ignored():
    aj, fd = _load_apply_jobs_with_mock()
    aj._qa_cache = None
    bots = [FakeEl("Kindly answer all recruiter's questions carefully")]
    with patch.object(aj, "_chat_bot_messages", return_value=bots), \
         patch.object(aj, "bard_flash_response") as bard, \
         patch.object(aj, "_visible_enabled", return_value=[FakeEl()]):
        assert aj.answer_text_question() is False
        bard.assert_not_called()


def test_actual_text_question_answered_and_sent():
    aj, fd = _load_apply_jobs_with_mock()
    aj._qa_cache = None
    from selenium.webdriver.common.keys import Keys
    inp = FakeEl()
    bots = [FakeEl("What is your notice period?")]
    with patch.object(aj, "_chat_bot_messages", return_value=bots), \
         patch.object(aj, "_visible_enabled", return_value=[inp]), \
         patch.object(aj, "bard_flash_response", return_value="30 days"), \
         patch.object(aj, "load_candidate_profile", return_value={}), \
         patch.object(time, "sleep", return_value=None):
        assert aj.answer_text_question() is True
        assert inp.sent and inp.sent[0] == "30 days" and Keys.ENTER in inp.sent


def test_hidden_or_disabled_controls_not_actionable():
    aj, fd = _load_apply_jobs_with_mock()
    with patch.object(fd, "find_elements", return_value=[_hidden_el()]):
        assert aj._has_actionable_chat_input() is False
    with patch.object(fd, "find_elements", return_value=[_disabled_el()]):
        assert aj._has_actionable_chat_input() is False
    with patch.object(fd, "find_elements", return_value=[FakeEl()]):
        assert aj._has_actionable_chat_input() is True


def test_no_actionable_input_ends_as_review_with_screenshot():
    aj, fd = _load_apply_jobs_with_mock()
    with patch.object(aj, "answer_radio_questions", return_value=False), \
         patch.object(aj, "answer_text_question", return_value=False), \
         patch.object(aj, "answer_checkbox_questions", return_value=False), \
         patch.object(aj, "_current_question_signature", return_value=""), \
         patch.object(aj, "_has_actionable_chat_input", return_value=False), \
         patch.object(aj, "_has_checkbox_input", return_value=False), \
         patch.object(aj, "application_status", return_value=None), \
         patch.object(aj, "the_success_markers", return_value=False), \
         patch.object(aj, "attempt_final_submit", return_value=(False, "")), \
         patch.object(aj, "_capture_visit_screenshot", return_value="reports/x.png"), \
         patch.object(time, "sleep", return_value=None):
        res = aj.run_chat_widget_loop()
        assert res.status == "review", (res.status, res.reason)
        assert "confirm" in (res.reason or "").lower() or "actionable" in (res.reason or "").lower()
        assert res.screenshot == "reports/x.png"


class FakeDriver:
    def __init__(self):
        self._queues = {}
        self.current_url = "https://www.naukri.com/job-listings-123"
        self._sig_seq = []
        self._sig_idx = 0
        self._has_input_seq = []
        self._has_input_idx = 0

    def find_elements(self, by, val):
        if "thank" in val.lower() and "response" in val.lower():
            sig = self._current_sig()
            if sig and sig.startswith("thank:"):
                return [FakeEl(sig)]
            return []
        if ".ssrc__radio-btn-container" in val:
            sig = self._current_sig()
            if sig and sig.startswith("radio:"):
                return [FakeEl(), FakeEl()]
            return []
        if "contenteditable" in val or "textArea" in val:
            sig = self._current_sig()
            if sig and sig.startswith("text:"):
                return [FakeEl()]
            if self._has_input_seq:
                v = self._has_input_seq[min(self._has_input_idx, len(self._has_input_seq) - 1)]
                return [FakeEl()] if v else []
            return []
        if "apply-status-header" in val:
            return []
        if "apply-message" in val or "Application sent" in val:
            return []
        if "already-applied" in val:
            return []
        return []

    def find_element(self, by, val):
        raise Exception("not found")

    def _current_sig(self):
        if self._sig_seq:
            return self._sig_seq[min(self._sig_idx, len(self._sig_seq) - 1)]
        return ""


def _load_apply_jobs_with_mock():
    import sys
    import unittest.mock as mock
    fd = FakeDriver()
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


def test_wait_prioritizes_new_question_over_transient_thank():
    aj, fd = _load_apply_jobs_with_mock()
    fd._sig_seq = ["radio:Yes|No", "thank:Thank you for your response", "text:What is your notice period?"]
    aj.NEXT_QUESTION_TIMEOUT = 5
    aj.NEXT_QUESTION_POLL = 0.05
    call = {"idx": 0}

    orig_sig = aj._current_question_signature

    def sig_mock():
        v = fd._sig_seq[min(call["idx"], len(fd._sig_seq) - 1)]
        return v

    def has_input_mock():
        s = sig_mock()
        return s.startswith("radio:") or s.startswith("text:")

    with patch.object(aj, "_current_question_signature", side_effect=sig_mock), \
         patch.object(aj, "_has_actionable_chat_input", side_effect=has_input_mock), \
         patch.object(aj, "application_status", return_value=None), \
         patch.object(aj, "the_success_markers", return_value=False):
        def advance(*a, **kw):
            call["idx"] = min(call["idx"] + 1, len(fd._sig_seq) - 1)
        with patch.object(time, "sleep", side_effect=advance):
            monotonic_vals = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 1.0, 2.0, 6.0]
            m_idx = {"i": 0}

            def mono():
                v = monotonic_vals[min(m_idx["i"], len(monotonic_vals) - 1)]
                m_idx["i"] += 1
                return v

            with patch.object(time, "monotonic", side_effect=mono):
                out = aj._wait_for_next_state("radio:Yes|No", fd.current_url, timeout=5)
                assert out == "new_question"


def test_wait_returns_success_only_after_thank_persists_no_input():
    aj, fd = _load_apply_jobs_with_mock()
    fd._sig_seq = ["thank:Thank you for your response"]
    aj.NEXT_QUESTION_TIMEOUT = 6
    aj.NEXT_QUESTION_POLL = 0.05

    def sig_mock():
        return "thank:Thank you for your response"

    with patch.object(aj, "_current_question_signature", side_effect=sig_mock), \
         patch.object(aj, "_has_actionable_chat_input", return_value=False), \
         patch.object(aj, "application_status", return_value=None), \
         patch.object(aj, "the_success_markers", return_value=False):
        with patch.object(time, "sleep", return_value=None):
            vals = [0, 0.5, 1.0, 2.0, 3.5, 5.0, 7.0]
            idx = {"i": 0}

            def mono():
                v = vals[min(idx["i"], len(vals) - 1)]
                idx["i"] += 1
                return v

            with patch.object(time, "monotonic", side_effect=mono):
                out = aj._wait_for_next_state("text:Q1", fd.current_url, timeout=6)
                assert out == "success"


def test_answer_text_skips_already_answered():
    aj, fd = _load_apply_jobs_with_mock()
    answered = {"What is your notice period?"}
    el1 = FakeEl("What is your notice period?")
    el2 = FakeEl("What is your expected CTC?")
    with patch.object(fd, "find_elements", return_value=[el1, el2]):
        aj.driver = fd
        with patch.object(aj, "bard_flash_response", return_value="NEEDS_REVIEW"):
            pass
        q = None
        bots = fd.find_elements(None, None)
        for e in reversed(bots):
            if e.text.strip() and e.text.strip() not in answered:
                q = e.text.strip()
                break
        assert q == "What is your expected CTC?"
    with patch.object(fd, "find_elements", return_value=[el1]):
        bots = fd.find_elements(None, None)
        q2 = None
        for e in reversed(bots):
            if e.text.strip() and e.text.strip() not in answered:
                q2 = e.text.strip()
                break
        assert q2 is None


def test_run_chat_widget_loop_answers_all_before_applied():
    aj, fd = _load_apply_jobs_with_mock()
    aj.MAX_QUESTIONS_PER_JOB = 5
    seq = [
        ("radio:Yes|No", True, "new_question"),
        ("text:Notice period?", True, "new_question"),
        ("radio:A|B|C", True, "success"),
    ]
    call = {"i": 0}

    def radio_mock(answered=None):
        idx = call["i"]
        if idx < len(seq) and seq[idx][0].startswith("radio:"):
            return True
        return False

    def text_mock(answered=None):
        idx = call["i"]
        if idx < len(seq) and seq[idx][0].startswith("text:"):
            if answered is not None:
                answered.add(seq[idx][0][5:])
            return True
        return False

    def wait_mock(prev_sig, prev_url, timeout=None):
        idx = call["i"]
        out = seq[idx][2] if idx < len(seq) else "timeout"
        call["i"] += 1
        return out

    def sig_mock():
        idx = min(call["i"], len(seq) - 1)
        return seq[idx][0]

    with patch.object(aj, "answer_radio_questions", side_effect=radio_mock), \
         patch.object(aj, "answer_text_question", side_effect=text_mock), \
         patch.object(aj, "_wait_for_next_state", side_effect=wait_mock), \
         patch.object(aj, "_current_question_signature", side_effect=sig_mock), \
         patch.object(aj, "_has_actionable_chat_input", side_effect=lambda: call["i"] < len(seq) - 1), \
         patch.object(aj, "application_status", return_value=None), \
         patch.object(aj, "the_success_markers", side_effect=lambda: call["i"] >= len(seq) - 1), \
         patch.object(time, "sleep", return_value=None):
        fd.current_url = "https://www.naukri.com/job-listings-xyz"
        res = aj.run_chat_widget_loop()
        assert res.status == "applied"
        assert call["i"] == 2  # site proof at i>=2 ends the loop; no answering after confirmation
