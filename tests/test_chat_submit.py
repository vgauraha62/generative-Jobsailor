"""Submit-once chat flow: answer all, submit once at end, incomplete banners never succeed."""
import sys
import time as _time
import unittest.mock as mock
from selenium.common.exceptions import NoSuchElementException


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
        return aj


class _El:
    def __init__(self, text="", click=None):
        self.text = text
        self._click = click

    def get_attribute(self, k):
        return ""

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True

    def click(self):
        pass

    def send_keys(self, *a):
        pass


class _RadioBox:
    def __init__(self, label, value, seq):
        self._label = label
        self._value = value
        self._seq = seq

    def find_element(self, by, sel):
        if "label" in sel:
            return _El(self._label)
        inp = _El()
        inp.get_attribute = lambda k: self._value
        return inp


class _CheckBox(_RadioBox):
    pass


class SeqDriver:
    """Scripted widget frames. Clicks advance frames like the site reacting."""

    def __init__(self, aj, frames):
        self.aj = aj
        self.frames = frames
        self.i = 0
        self.clicks = []
        self.current_url = "https://www.naukri.com/job-listings-123"

    def _f(self):
        return self.frames[min(self.i, len(self.frames) - 1)]

    def get(self, url):
        self.record("get", url)
        self.current_url = url

    def record(self, kind, detail=""):
        self.clicks.append((kind, detail))

    def execute_script(self, js, el):
        kind = "submit" if isinstance(el, _Btn) else "radio"
        self.record(kind, getattr(el, "text", ""))
        if kind == "radio" and self._f().get("stick_select"):
            return  # site did not advance on select alone
        self.i = min(self.i + 1, len(self.frames) - 1)

    def find_elements(self, by, sel):
        f = self._f()
        if ".ssrc__radio-btn-container" in sel:
            return [_RadioBox(l, v, self) for (l, v) in f.get("radios", [])] or []
        if "checkbox" in sel:
            return [_CheckBox(l, v, self) for (l, v) in f.get("checks", [])] or []
        if "botItem" in sel:
            return [_El(f["q"])] if f.get("q") else []
        if "contenteditable" in sel or "textArea" in sel or "textarea" in sel:
            return [_Input(self)] if f.get("q") and not f.get("radios") and not f.get("checks") else []
        if "button" in sel and any(k in sel.lower() for k in ("save", "send", "submit")):
            # ponytail: site xpath lowercases via translate() — match that, not capitalized labels
            subs = f.get("submits", [f.get("submit")] if f.get("submit") else [])
            return [_Btn(s, self) for s in subs if s]
        if "THANK" in sel:
            return [_El("Thank you for your response")] if f.get("thank") else []
        if "apply-status-header" in sel:
            m = mock.MagicMock()
            m.get_attribute = lambda k: "green" if f.get("applied") else ""
            return [m] if f.get("applied") or True else []
        if "Application sent" in sel or "applied successfully" in sel or 'Applied to "' in sel:
            return [_El("x")] if f.get("markers") else []
        if "already-applied" in sel:
            return []
        return []

    def find_element(self, by, sel):
        if sel == "body" or (str(by).lower() == "tag name" and sel == "body"):
            return _El(self._f().get("body", ""))
        if "contenteditable" in sel or "textarea" in sel or "textArea" in sel:
            f = self._f()
            if f.get("q") and not f.get("radios") and not f.get("checks"):
                return _Input(self)
            raise NoSuchElementException()
        if "chatList_" in sel:
            f = self._f()
            if f.get("q"):
                m = mock.MagicMock()
                li = mock.MagicMock()
                li.text = f["q"]
                m.find_elements = lambda by2, sel2: [li]
                return m
            raise NoSuchElementException()
        raise NoSuchElementException()


class _Btn(_El):
    def __init__(self, text, seq):
        super().__init__(text)
        self._seq = seq


class _Input(_El):
    def __init__(self, seq):
        super().__init__("")
        self._seq = seq

    def send_keys(self, *a):
        from selenium.webdriver.common.keys import Keys
        if a and a[0] == Keys.ENTER:
            self._seq.record("enter", "")
            self._seq.i = min(self._seq.i + 1, len(self._seq.frames) - 1)


def _ctx(aj, frames):
    drv = SeqDriver(aj, frames)
    aj.driver = drv
    mono = {"t": 0.0}

    def monotonic():
        mono["t"] += 0.5
        return mono["t"]

    def bard(prompt, timeout=None, preset="micro"):
        if "option number" in prompt:
            return "1"
        return "Pune"

    patches = [
        mock.patch.object(aj, "application_status",
                          side_effect=lambda: "applied" if drv._f().get("applied") else ("failed" if drv._f().get("failed") else None)),
        mock.patch.object(aj, "the_success_markers", side_effect=lambda: bool(drv._f().get("markers"))),
        mock.patch.object(aj, "already_applied_or_expired", return_value=False),
        mock.patch.object(aj, "click_apply", return_value=True),
        mock.patch("resume.jd.extract_jd", return_value="jd"),
        mock.patch("resume.jd.has_surface", return_value="both"),
        mock.patch.object(aj, "load_curation_budget", return_value={"day": "x", "calls_used": 99}),
        mock.patch.object(aj, "curation_budget_ok", return_value=False),
        mock.patch.object(aj, "bard_flash_response", side_effect=bard),
        mock.patch.object(aj, "_capture_visit_screenshot", return_value=None),
        mock.patch.object(aj, "_capture_chat_q_screenshot", return_value=None),
        mock.patch.object(_time, "sleep", return_value=None),
        mock.patch.object(_time, "monotonic", side_effect=monotonic),
        mock.patch.object(aj, "load_candidate_profile", return_value={}),
    ]
    return drv, patches


def _run_inner(aj, patches, url="https://u"):
    for p in patches:
        p.start()
    try:
        return aj._process_job_inner(url, "python-jobs")
    finally:
        for p in patches:
            p.stop()


def test_answer_all_then_submit_once():
    aj = _load_aj()
    frames = [
        {"q": "City?", "radios": [("Yes", "Yes"), ("No", "No")], "submit": "Save & Continue"},
        {"q": "Skills?", "submit": "Save & Continue"},
        {"submit": "Save & Continue"},
        {"applied": True},
    ]
    drv, patches = _ctx(aj, frames)
    r = _run_inner(aj, patches)
    assert r.status == "applied", (r.status, r.reason)
    submits = [c for c in drv.clicks if c[0] == "submit"]
    assert len(submits) == 1, drv.clicks  # clicked exactly once, never mid-questions
    kinds = [e.get("type") for e in (r.chat_transcript or [])]
    assert kinds[0] in ("radio", "text") and "submit" in kinds, kinds


def test_incomplete_banner_reviews_without_submit():
    aj = _load_aj()
    frames = [{"submit": "Save", "body": "Please complete your application. Some information is incomplete."}]
    drv, patches = _ctx(aj, frames)
    r = _run_inner(aj, patches)
    assert r.status == "review", (r.status, r.reason)
    assert not [c for c in drv.clicks if c[0] == "submit"], drv.clicks
    assert "incomplete" in (r.reason or "").lower()


def test_no_submit_button_reviews():
    aj = _load_aj()
    frames = [{"body": "Thank you for your interest."}]
    drv, patches = _ctx(aj, frames)
    r = _run_inner(aj, patches)
    assert r.status in ("failed", "review"), (r.status, r.reason)
    assert not [c for c in drv.clicks if c[0] == "submit"], drv.clicks


def test_submit_revealing_more_questions_continues():
    aj = _load_aj()
    frames = [
        {"q": "City?", "radios": [("Yes", "Yes"), ("No", "No")], "submit": "Save"},
        {"submit": "Save"},
        {"q": "Night shift?", "radios": [("Yes", "Yes"), ("No", "No")], "submit": "Save"},
        {"applied": True},
    ]
    drv, patches = _ctx(aj, frames)
    r = _run_inner(aj, patches)
    qs = [e.get("q") for e in (r.chat_transcript or []) if e.get("type") in ("radio", "text")]
    assert qs == ["City?", "Night shift?"], qs
    assert r.status == "applied", (r.status, r.reason)


def test_stuck_select_never_clicks_save():
    aj = _load_aj()
    frames = [
        {"q": "City?", "radios": [("Yes", "Yes"), ("No", "No")], "submit": "Save", "stick_select": True},
        {"q": "City?", "radios": [("Yes", "Yes"), ("No", "No")], "submit": "Save", "stick_select": True},
    ]
    drv, patches = _ctx(aj, frames)
    r = _run_inner(aj, patches)
    assert r.status == "review", (r.status, r.reason)  # ponytail: stuck-but-unrejected is unresolved, not failed
    assert not [c for c in drv.clicks if c[0] == "submit"], drv.clicks  # strict: no Save while controls remain


def test_checkbox_question_answered():
    aj = _load_aj()
    frames = [
        {"q": "Perks?", "checks": [("Health", "Health"), ("Dental", "Dental")], "submit": "Save"},
        {"applied": True},
    ]
    drv, patches = _ctx(aj, frames)
    r = _run_inner(aj, patches)
    assert r.status == "applied", (r.status, r.reason)
    rows = [(e.get("type"), e.get("q"), e.get("answer")) for e in (r.chat_transcript or []) if e.get("type") == "checkbox"]
    assert rows == [("checkbox", "Perks?", "1")], rows


def test_final_submit_prefers_submit_over_save():
    import unittest.mock as mock
    aj = _load_aj()

    class Btns:
        def __init__(self, labels):
            self.labels = labels

    save_b = mock.MagicMock()
    save_b.text = "Save"
    save_b.is_displayed = lambda: True
    save_b.is_enabled = lambda: True
    sub_b = mock.MagicMock()
    sub_b.text = "Submit Application"
    sub_b.is_displayed = lambda: True
    sub_b.is_enabled = lambda: True
    clicked = []
    drv = mock.MagicMock()
    drv.find_elements = lambda by, sel: [save_b, sub_b] if "button" in sel else []
    drv.find_element = lambda by, sel: mock.MagicMock(text="")
    drv.execute_script = lambda js, el: clicked.append(el.text)
    drv.current_url = "https://u"
    aj.driver = drv
    with mock.patch.object(aj, "_has_actionable_chat_input", return_value=False), \
         mock.patch("time.sleep"):
        clicked_flag, label = aj.attempt_final_submit()
    assert clicked_flag is True and label == "Submit Application", (clicked_flag, label)
    assert clicked == ["Submit Application"]


def test_checkbox_question_answered_like_radio():
    aj = _load_aj()
    frames = [
        {"q": "Perks?", "checks": [("Health", "Health"), ("Dental", "Dental")], "submit": "Save"},
        {"applied": True},
    ]
    drv, patches = _ctx(aj, frames)
    r = _run_inner(aj, patches)
    assert r.status == "applied", (r.status, r.reason)
    rows = [(e.get("type"), e.get("q"), e.get("answer")) for e in (r.chat_transcript or []) if e.get("type") == "checkbox"]
    assert rows == [("checkbox", "Perks?", "1")], rows


def test_thank_without_markers_submits_first():
    aj = _load_aj()
    frames = [
        {"q": "City?", "radios": [("Yes", "Yes"), ("No", "No")], "submit": "Save"},
        {"thank": True, "submit": "Save & Continue"},
        {"applied": True},
    ]
    drv, patches = _ctx(aj, frames)
    r = _run_inner(aj, patches)
    assert r.status == "applied", (r.status, r.reason)
    submits = [c for c in drv.clicks if c[0] == "submit"]
    assert len(submits) == 1 and submits[0][1] == "Save & Continue", drv.clicks


def _btn(labels_text, seq=None, shown=True, enabled=True):
    b = _Btn(labels_text, seq)
    b.is_displayed = lambda: shown
    b.is_enabled = lambda: enabled
    return b


def _submit_drv(aj, buttons, body=""):
    clicks = []
    drv = mock.MagicMock()
    drv.find_elements = lambda by, sel: list(buttons) if "button" in sel else []
    drv.find_element = lambda by, sel: _El(body)
    drv.execute_script = lambda js, el: clicks.append(el.text)
    drv.current_url = "https://u"
    aj.driver = drv
    return clicks


def test_never_submit_while_question_control_remains():
    aj = _load_aj()
    clicks = _submit_drv(aj, [_btn("Submit Application")])
    with mock.patch.object(aj, "_has_actionable_chat_input", return_value=True), \
         mock.patch("time.sleep"):
        assert aj.attempt_final_submit() == (False, "")
    assert clicks == []


def test_message_send_button_is_not_final_submit():
    # ponytail: site xpath only matches submit/save; a lone Send yields no candidates
    aj = _load_aj()
    send = _btn("Send")
    drv = mock.MagicMock()
    drv.find_elements = lambda by, sel: [] if "button" in sel else ([send] if "send" in sel.lower() else [])
    drv.find_element = lambda by, sel: _El("")
    drv.execute_script = lambda js, el: (_ for _ in ()).throw(AssertionError("must not click"))
    drv.current_url = "https://u"
    aj.driver = drv
    with mock.patch.object(aj, "_has_actionable_chat_input", return_value=False), \
         mock.patch("time.sleep"):
        assert aj.attempt_final_submit() == (False, "")


def test_single_clear_final_button_clicked_once():
    aj = _load_aj()
    clicks = _submit_drv(aj, [_btn("Submit Application")])
    with mock.patch.object(aj, "_has_actionable_chat_input", return_value=False), \
         mock.patch("time.sleep"):
        clicked, label = aj.attempt_final_submit()
    assert (clicked, label) == (True, "Submit Application")
    assert clicks == ["Submit Application"]


def test_ambiguous_final_buttons_never_click():
    aj = _load_aj()
    for labels in (["Submit", "Submit"], ["Save", "Save"]):
        clicks = _submit_drv(aj, [_btn(t) for t in labels])
        with mock.patch.object(aj, "_has_actionable_chat_input", return_value=False), \
             mock.patch("time.sleep"):
            assert aj.attempt_final_submit() == (False, ""), labels
        assert clicks == [], labels


def test_incomplete_banner_blocks_submission():
    aj = _load_aj()
    clicks = _submit_drv(aj, [_btn("Submit Application")],
                         body="Some information is incomplete, please complete your application.")
    with mock.patch.object(aj, "_has_actionable_chat_input", return_value=False), \
         mock.patch("time.sleep"):
        assert aj.attempt_final_submit() == (False, "incomplete")
    assert clicks == []


def test_failed_header_with_questions_continues():
    aj = _load_aj()
    frames = [
        {"submit": "Save"},
        {"q": "Late?", "radios": [("Yes", "Yes"), ("No", "No")], "submit": "Save", "failed": True},
        {"applied": True},
    ]
    drv, patches = _ctx(aj, frames)
    r = _run_inner(aj, patches)
    assert r.status == "applied", (r.status, r.reason)
    qs = [e.get("q") for e in (r.chat_transcript or []) if e.get("type") in ("radio", "text", "checkbox")]
    assert qs == ["Late?"], qs
