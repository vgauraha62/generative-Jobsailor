"""Radio walk: Q1->Q2 same labels, slow renders, no re-answers. Provider-agnostic (above bard)."""
import sys
import time as _time
import unittest.mock as mock


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


class _Lbl:
    def __init__(self, t):
        self.text = t


class _Radio:
    def __init__(self, label):
        self._label = label

    def find_element(self, *a, **k):
        return _Lbl(self._label)


def test_sig_distinguishes_same_label_radios():
    aj, fd = _load_aj()

    def find(by, sel):
        if ".ssrc__radio-btn-container" in sel:
            return [_Radio("Yes"), _Radio("No")]
        if "botItem" in sel:
            return [mock.MagicMock(text=find.q)]
        return []
    find.q = "Q1: relocation?"
    fd.find_elements = find
    s1 = aj._current_question_signature()
    find.q = "Q2: night shift?"
    s2 = aj._current_question_signature()
    assert s1 != s2, (s1, s2)
    assert "Q1" in s1 and "Q2" in s2


def _run_loop(aj, sig_seq, input_seq):
    """Drive run_chat_widget_loop with scripted sig/input; stub answer fns like the real ones."""
    state = {"i": 0}
    qa_n = {"n": 0}

    def sig():
        return sig_seq[min(state["i"], len(sig_seq) - 1)]

    def has_input():
        return input_seq[min(state["i"], len(input_seq) - 1)]

    def fake_radio(answered=None):
        qa_n["n"] += 1
        aj._last_chat_qa = {"type": "radio", "q": f"Q{qa_n['n']}", "options": ["1. Yes", "2. No"], "answer": "1", "provider": "gemini"}
        return True

    mono = {"t": 0.0}

    def monotonic():
        mono["t"] += 0.5
        return mono["t"]

    with mock.patch.object(aj, "_current_question_signature", side_effect=sig), \
         mock.patch.object(aj, "_has_actionable_chat_input", side_effect=has_input), \
         mock.patch.object(aj, "application_status", return_value=None), \
         mock.patch.object(aj, "the_success_markers", return_value=False), \
         mock.patch.object(aj, "answer_radio_questions", side_effect=fake_radio), \
         mock.patch.object(aj, "answer_text_question", return_value=False), \
         mock.patch.object(_time, "sleep", side_effect=lambda s: state.__setitem__("i", state["i"] + 1)), \
         mock.patch.object(_time, "monotonic", side_effect=monotonic), \
         mock.patch.object(aj, "_capture_chat_q_screenshot", return_value=None):
        return aj.run_chat_widget_loop()


def test_walk_q1_q2_same_labels_then_success():
    aj, _ = _load_aj()
    sigs = ["radio:Q1|Yes|No"] * 3 + ["radio:Q2|Yes|No"] * 3 + ["thank:Thank you for your response"] * 60
    inputs = [True] * 6 + [False] * 60
    r = _run_loop(aj, sigs, inputs)
    assert r.status == "applied", (r.status, r.reason)
    qs = [e["q"] for e in r.chat_transcript]
    assert qs == ["Q1", "Q2"], qs


def test_slow_q2_answered_not_abandoned():
    aj, _ = _load_aj()
    answered_at = {"n": 0}

    def fake_radio(answered=None):
        answered_at["n"] += 1
        if answered_at["n"] < 3:
            return False
        aj._last_chat_qa = {"type": "radio", "q": "Qslow", "options": ["1. Yes"], "answer": "1", "provider": "gemini"}
        return True

    sigs = ["radio:Q1|Yes|No"] * 3 + ["radio:Qslow|Yes"] * 3 + ["thank:done"] * 60
    inputs = [True] * 6 + [False] * 60
    state = {"i": 0}
    mono = {"t": 0.0}

    def sig():
        return sigs[min(state["i"], len(sigs) - 1)]

    def has_input():
        return inputs[min(state["i"], len(inputs) - 1)]

    def monotonic():
        mono["t"] += 0.5
        return mono["t"]

    with mock.patch.object(aj, "_current_question_signature", side_effect=sig), \
         mock.patch.object(aj, "_has_actionable_chat_input", side_effect=has_input), \
         mock.patch.object(aj, "application_status", return_value=None), \
         mock.patch.object(aj, "the_success_markers", return_value=False), \
         mock.patch.object(aj, "answer_radio_questions", side_effect=fake_radio), \
         mock.patch.object(aj, "answer_text_question", return_value=False), \
         mock.patch.object(_time, "sleep", side_effect=lambda s: state.__setitem__("i", state["i"] + 1)), \
         mock.patch.object(_time, "monotonic", side_effect=monotonic), \
         mock.patch.object(aj, "_capture_chat_q_screenshot", return_value=None):
        # first round answers Q1 immediately via a one-shot stub
        orig = fake_radio
        calls = {"n": 0}

        def mixed(answered=None):
            calls["n"] += 1
            if calls["n"] == 1:
                aj._last_chat_qa = {"type": "radio", "q": "Q1", "options": ["1. Yes"], "answer": "1", "provider": "gemini"}
                return True
            return orig(answered)
        with mock.patch.object(aj, "answer_radio_questions", side_effect=mixed):
            r = aj.run_chat_widget_loop()
    qs = [e["q"] for e in (r.chat_transcript or [])]
    assert "Qslow" in qs, qs
