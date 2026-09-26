"""Banner receipt: post-apply confirmation counts as applied, slow renders get a second look."""
import sys
import unittest.mock as mock


def _load_aj():
    fd = mock.MagicMock()
    fd.current_url = "https://www.naukri.com/job-listings-x-123456789012"
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


def _inner_common(aj, fd, surf_seq):
    return dict(
        already=mock.patch.object(aj, "already_applied_or_expired", return_value=False),
        jd=mock.patch("resume.jd.extract_jd", return_value="jd"),
        click=mock.patch.object(aj, "click_apply", return_value=True),
        surf=mock.patch("resume.jd.has_surface", side_effect=surf_seq),
        shot=mock.patch.object(aj, "_capture_visit_screenshot", return_value=None),
        sleep=mock.patch("time.sleep"),
    )


def test_banner_counts_as_applied():
    aj, fd = _load_aj()
    ctx = _inner_common(aj, fd, ["none", "none"])
    with ctx["already"], ctx["jd"], ctx["click"], ctx["surf"], ctx["shot"], ctx["sleep"], \
         mock.patch.object(aj, "the_success_markers", return_value=True):
        r = aj._process_job_inner("https://u", "python-jobs")
    assert r.status == "applied", (r.status, r.reason)
    assert r.reason == "confirmed via banner"
    assert getattr(r, "verified", None) == "banner"


def test_slow_render_gets_second_look():
    aj, fd = _load_aj()
    ctx = _inner_common(aj, fd, ["none", "chat_widget"])
    with ctx["already"], ctx["jd"], ctx["click"], ctx["surf"], ctx["shot"], ctx["sleep"], \
         mock.patch.object(aj, "the_success_markers", return_value=False), \
         mock.patch.object(aj, "load_curation_budget", return_value={"day": "x", "calls_used": 99}), \
         mock.patch.object(aj, "curation_budget_ok", return_value=False), \
         mock.patch.object(aj, "_extract_with_retry", return_value=[]):
        r = aj._process_job_inner("https://u", "python-jobs")
    assert r.reason != "no_form_or_chat", (r.status, r.reason)  # past the gate


def test_markers_include_banner():
    aj, fd = _load_aj()

    def find(by, sel):
        m = mock.MagicMock()
        if sel and 'Applied to "' in sel:
            return [m]
        return []
    fd.find_elements = find
    aj.driver = fd
    assert aj.the_success_markers() is True
    fd.find_elements = lambda by, sel: []
    assert aj.the_success_markers() is False
