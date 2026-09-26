from unittest.mock import patch, MagicMock
import sys

def _load_aj():
    fake_driver = MagicMock()
    fake_driver.current_url = "https://www.naukri.com/job-listings-test"
    fake_driver.page_source = ""
    with patch("selenium.webdriver.Firefox", return_value=fake_driver), \
         patch("selenium.webdriver.firefox.service.Service"), \
         patch("selenium.webdriver.firefox.firefox_profile.FirefoxProfile"), \
         patch("selenium.webdriver.firefox.options.Options"), \
         patch("shutil.which", return_value="/usr/local/bin/geckodriver"):
        if "apply_jobs" in sys.modules:
            del sys.modules["apply_jobs"]
        import apply_jobs as aj
        aj.driver = fake_driver
        return aj, fake_driver

def test_chat_no_input_stays_chat_widget_not_full_form():
    aj, fd = _load_aj()
    fake_chat = MagicMock()
    fake_chat.status = "failed"
    fake_chat.reason = "no actionable chat input"
    fake_chat.error_type = None
    fake_chat.traceback = None
    fake_chat.path_taken = "chat_widget"
    with patch("apply_jobs.already_applied_or_expired", return_value=False), \
         patch("apply_jobs.click_apply", return_value=True), \
         patch("resume.jd.has_surface", return_value="chat_widget"), \
         patch("apply_jobs._maybe_curate_and_upload", return_value=(0.0, False, None, "skipped_high_score")), \
         patch("apply_jobs.run_chat_widget_loop", return_value=fake_chat), \
         patch("apply_jobs._verify_late_success", return_value=False), \
         patch("apply_jobs.extract_form_fields", return_value=[]), \
         patch("apply_jobs._capture_visit_screenshot", return_value=None), \
         patch("apply_jobs.load_curation_budget", return_value={"day":"2026-08-29","calls_used":0}), \
         patch("apply_jobs.curation_budget_ok", return_value=True), \
         patch("time.sleep"):
        res = aj._process_job_inner("https://www.naukri.com/job-listings-test", "python")
        assert res.path_taken == "chat_widget", res.path_taken
        assert res.reason == "no actionable chat input"
        assert res.status == "failed"

def test_upload_failed_blocks_apply():
    aj, fd = _load_aj()
    with patch("apply_jobs.already_applied_or_expired", return_value=False), \
         patch("apply_jobs.click_apply", return_value=True), \
         patch("resume.jd.has_surface", return_value="chat_widget"), \
         patch("apply_jobs._maybe_curate_and_upload", return_value=(0.0, True, "resumes/pdf/abc.pdf", "upload_failed:wait_success:TimeoutException")), \
         patch("apply_jobs._capture_visit_screenshot", return_value="reports/visit_upload_failed_123.png"), \
         patch("apply_jobs.load_curation_budget", return_value={"day":"2026-08-29","calls_used":0}), \
         patch("apply_jobs.curation_budget_ok", return_value=True), \
         patch("time.sleep"):
        res = aj._process_job_inner("https://www.naukri.com/job-listings-test", "python")
        assert res.status == "failed"
        assert res.reason == "resume_upload_failed"
        assert res.upload_status.startswith("upload_failed")
        assert res.screenshot is not None

def test_upload_error_blocks_apply():
    aj, fd = _load_aj()
    with patch("apply_jobs.already_applied_or_expired", return_value=False), \
         patch("apply_jobs.click_apply", return_value=True), \
         patch("resume.jd.has_surface", return_value="chat_widget"), \
         patch("apply_jobs._maybe_curate_and_upload", return_value=(None, False, None, "error:WebDriverException")), \
         patch("apply_jobs._capture_visit_screenshot", return_value="reports/visit_upload_failed_123.png"), \
         patch("apply_jobs.load_curation_budget", return_value={"day":"2026-08-29","calls_used":0}), \
         patch("apply_jobs.curation_budget_ok", return_value=True), \
         patch("time.sleep"):
        res = aj._process_job_inner("https://www.naukri.com/job-listings-test", "python")
        assert res.status == "failed"
        assert res.reason == "resume_upload_failed"

def test_full_form_still_full_form_when_surf_full():
    aj, fd = _load_aj()
    fake_chat = MagicMock()
    fake_chat.status = "failed"
    fake_chat.reason = "no actionable chat input"
    fake_chat.error_type = None
    fake_chat.traceback = None
    with patch("apply_jobs.already_applied_or_expired", return_value=False), \
         patch("apply_jobs.click_apply", return_value=True), \
         patch("resume.jd.has_surface", return_value="full_form"), \
         patch("apply_jobs._maybe_curate_and_upload", return_value=(0.0, False, None, "skipped_high_score")), \
         patch("apply_jobs.run_chat_widget_loop", return_value=fake_chat), \
         patch("apply_jobs._verify_late_success", return_value=False), \
         patch("apply_jobs.extract_form_fields", return_value=[]), \
         patch("apply_jobs._capture_visit_screenshot", return_value=None), \
         patch("apply_jobs.load_curation_budget", return_value={"day":"2026-08-29","calls_used":0}), \
         patch("apply_jobs.curation_budget_ok", return_value=True), \
         patch("time.sleep"):
        res = aj._process_job_inner("https://www.naukri.com/job-listings-test", "python")
        assert res.path_taken == "full_form"
        assert res.reason == "no form fields found"
