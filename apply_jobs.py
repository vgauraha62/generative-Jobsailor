"""Automated job application bot for Naukri.com using Selenium + Firefox.

Fetches live job listings, applies to each, and uses the Gemini API
(gemini_api.bard_flash_response) to answer any questions Naukri asks during
the apply flow.
"""

from selenium.webdriver.firefox.service import Service
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import (
    InvalidSessionIdException,
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
    StaleElementReferenceException,
)
from gemini_api import bard_flash_response, reset_job_counter, job_count as gemini_job_count, reset_curation_counter, curation_count
from candidate_profile import load_candidate_profile, find_sentinels
from config_loader import load_config
import os as _os
_USER_ID = _os.environ.get("USER_ID")
if _USER_ID:
    try:
        from pathlib import Path as _P
        _uid = int(_USER_ID)
        _shard = _P("data/users") / str(_uid)
        _shard.mkdir(parents=True, exist_ok=True)
        # override per-user config/budgets if exists
        import config_loader as _cl
        _per_cfg = _shard / "config.json"
        if _per_cfg.exists():
            try:
                import json as _js
                _pc = json.loads(_per_cfg.read_text())
                # merge not needed, will be read via helper
                pass
            except: pass
        # per-user gemini key
        _gem = _shard / ".env.gemini"
        if _gem.exists():
            for line in _gem.read_text().splitlines():
                if line.startswith("GEMINI_API_KEY="):
                    _os.environ["GEMINI_API_KEY"] = line.split("=",1)[1].strip()
                if line.startswith("GEMINI_MODEL=") and line.split("=",1)[1].strip():
                    _os.environ["GEMINI_MODEL"] = line.split("=",1)[1].strip()
        # monkey-patch state to per-user files
        import state as _st
        orig_load_visited = _st.load_visited
        orig_save_visited = _st.save_visited
        orig_load_budget = _st.load_budget
        orig_save_budget = _st.save_budget
        orig_load_curation = _st.load_curation_budget
        orig_save_curation = _st.save_curation_budget
        def _per_load_visited():
            p = _shard / "visited.json"
            if p.exists():
                with open(p) as f: return json.load(f)
            return {}
        def _per_save_visited(d):
            p = _shard / "visited.json"
            tmp = str(p) + ".tmp"
            import json as _js
            with open(tmp, "w") as f: _js.dump(d, f, indent=2)
            _os.replace(tmp, p)
        def _per_load_budget(tz_name=None):  # ponytail: same signature as state.load_budget
            p = _shard / "gemini_budget.json"
            from datetime import datetime as _dt
            today = _dt.now().date().isoformat()
            if p.exists():
                with open(p) as f:
                    b = json.load(f)
                    if b.get("day") == today: return b
            return {"day": today, "calls_used": 0}
        def _per_save_budget(b):
            p = _shard / "gemini_budget.json"
            tmp = str(p) + ".tmp"
            import json as _js
            with open(tmp, "w") as f: _js.dump(b, f)
            _os.replace(tmp, p)
        def _per_load_curation(tz_name=None):  # ponytail: same signature as state.load_curation_budget
            p = _shard / "curation_budget.json"
            from datetime import datetime as _dt
            today = _dt.now().date().isoformat()
            if p.exists():
                with open(p) as f:
                    b = json.load(f)
                    if b.get("day") == today: return b
            return {"day": today, "calls_used": 0}
        def _per_save_curation(b):
            p = _shard / "curation_budget.json"
            tmp = str(p) + ".tmp"
            import json as _js
            with open(tmp, "w") as f: _js.dump(b, f)
            _os.replace(tmp, p)
        _st.load_visited = _per_load_visited
        _st.save_visited = _per_save_visited
        _st.load_budget = _per_load_budget
        _st.save_budget = _per_save_budget
        _st.load_curation_budget = _per_load_curation
        _st.save_curation_budget = _per_save_curation
        # also patch candidate_profile - blank NEEDS_REVIEW for new user, never global Vaibhav
        import candidate_profile as _cp
        orig_cp_load = _cp.load_candidate_profile
        def _per_cp_load():
            p = _shard / "candidate_profile.json"
            if p.exists():
                try:
                    with open(p) as f: return json.load(f)
                except: pass
            return {"resume_facts": {"name": "NEEDS_REVIEW", "email": "NEEDS_REVIEW", "phone": "NEEDS_REVIEW", "highest_qualification": "NEEDS_REVIEW", "institution": "NEEDS_REVIEW", "total_experience_years": "NEEDS_REVIEW", "relevant_experience_years": "NEEDS_REVIEW", "current_location": "NEEDS_REVIEW", "skills": "NEEDS_REVIEW"}, "user_preferences": {"current_ctc_lpa": "NEEDS_REVIEW", "expected_ctc_lpa": "NEEDS_REVIEW", "notice_period_days": "NEEDS_REVIEW", "willing_to_relocate": "NEEDS_REVIEW", "work_authorization": "NEEDS_REVIEW", "passport_valid": "NEEDS_REVIEW"}}
        _cp.load_candidate_profile = _per_cp_load
        _cp._cache = _cp._UNSET
        # per-user gemini key (dir overrides deferred until CONFIG exists below)
        try:
            import gemini_api as _ga
            if _os.environ.get("GEMINI_API_KEY"):
                _ga.API_KEY = _os.environ["GEMINI_API_KEY"]
                _ga.MODEL_NAME = _os.environ.get("GEMINI_MODEL") or _ga.GEMINI_CFG.get("model")
                try:
                    from google import genai as _gen
                    _ga.client = _gen.Client(api_key=_ga.API_KEY)
                except: pass
        except: pass
    except Exception as _e:
        print(f"[per-user] setup warn: {_e}")
from state import load_visited, save_visited, should_skip, mark_visited, load_budget, budget_ok, bucket_against_ledger, load_curation_budget, curation_budget_ok
from reporting import write_capture_report, write_visit_report, write_manual_report, build_visit_summary, run_id, JobResult, visit_items, write_forms_report, forms_items, spillover_block
from gemini_api import ModelOverloaded  # ponytail: halt signal re-raised through swallow-handlers
import time
import csv
import shutil
import signal
import traceback
import argparse
import json
from datetime import datetime
from pathlib import Path

_stop_requested = False
_RUN_ID = ""


def _handle_stop(signum, frame):
    global _stop_requested
    _stop_requested = True
    print(f"[stop] signal {signum} received — will stop after current job")


signal.signal(signal.SIGINT, _handle_stop)
signal.signal(signal.SIGTERM, _handle_stop)

CONFIG = load_config()
SEARCH_CFG = CONFIG["search"]
BROWSER_CFG = CONFIG["browser"]
TIMING_CFG = CONFIG["timing"]
APPLY_CFG = CONFIG["apply"]
VISITED_CFG = CONFIG["visited"]
CSV_CFG = CONFIG["csv"]
REPORTS_CFG = CONFIG["reports"]
CURATION_CFG = CONFIG["resume_curation"]
# ponytail: deferred per-user dirs; CONFIG must exist first, never brick run
try:
    if _USER_ID and "_shard" in globals() and "_uid" in globals():
        Path(str(_shard / "naukri_profile")).mkdir(parents=True, exist_ok=True)  # ponytail: fresh users have no profile yet; create so import never bricks
        REPORTS_CFG["dir"] = str(_P("reports") / str(_uid))
        # ponytail: shard profile only when uploaded (cookies.sqlite); else keep global login
        if Path(str(_shard / "naukri_profile" / "cookies.sqlite")).exists():
            BROWSER_CFG["profile_path"] = str(_shard / "naukri_profile")
        else:
            print(f"[browser] shard profile empty, using global login profile: {BROWSER_CFG['profile_path']}")
        CURATION_CFG["dir"] = str(_shard / "resumes")
        CURATION_CFG["active_resume"] = str(_shard / "resumes" / "active.json")
except Exception:
    pass

PROFILE_PATH = BROWSER_CFG["profile_path"]
JOBS_CSV = CSV_CFG["path"]
SEARCH_SLUGS = list(SEARCH_CFG["slugs"])
PER_TYPE_JOBS = SEARCH_CFG["per_type_jobs"]
MAX_JOBS = SEARCH_CFG["max_jobs_global"]
MAX_QUESTIONS_PER_JOB = APPLY_CFG["max_questions_per_job"]
APPLY_TIMEOUT = TIMING_CFG["apply_timeout"]
QUESTION_TIMEOUT = TIMING_CFG["question_timeout"]
NEXT_QUESTION_TIMEOUT = TIMING_CFG.get("next_question_timeout", 8)
NEXT_QUESTION_POLL = 0.3
DRY_RUN = APPLY_CFG["dry_run"]
MAX_RETRIES = VISITED_CFG["max_retries"]
GEMINI_CFG = CONFIG["gemini"]
DAILY_CALL_LIMIT = GEMINI_CFG["daily_call_limit"]
MAX_PAGES_PER_TYPE = SEARCH_CFG["max_pages_per_type"]
_last_chat_qa = {}
_chat_transcript_buf = []

driver_path = shutil.which("geckodriver")
binary = BROWSER_CFG["binary"] or shutil.which("firefox") or "/opt/firefox/firefox"
if not driver_path:
    raise RuntimeError("geckodriver not found on PATH.")

service = Service(driver_path)
options = Options()
options.binary_location = binary
options.profile = FirefoxProfile(PROFILE_PATH)
options.add_argument("--no-default-browser-check")

driver = webdriver.Firefox(service=service, options=options)
wait = WebDriverWait(driver, APPLY_TIMEOUT)

applied = 0
failed = 0
success_messages = (
    "//span[contains(@class, 'apply-message') and "
    "(contains(text(), 'successfully applied') or contains(text(), 'You have successfully applied'))]"
)


def _harvest_page(page_url: str, already: dict) -> tuple:
    """Scrape one search page; return (new_links, dup_count)."""
    driver.get(page_url)
    time.sleep(TIMING_CFG["page_load_wait"])
    new_links = 0
    dup = 0
    for a in driver.find_elements(By.XPATH, "//a[contains(@href, '/job-listings')]"):
        href = a.get_attribute("href")
        if not href or "job-listings" not in href:
            continue
        if href in already:
            dup += 1
            continue
        already[href] = True
        new_links += 1
    return new_links, dup


def collect_job_urls_for(slug: str, visited: dict) -> tuple:
    """Live job-link harvest across pages; fall back to type-filtered csv.

    Returns (actionable_urls, per_type_meta) where actionable_urls pass the
    visited-ledger filter and per_type_meta records how the capture went
    (pages, dedup, ledger breakdown, net-new) for the report.
    """
    live = True  # ponytail: sampling dry-run behaves live everywhere; stop is by counts, not by gates
    urls: dict = {}
    links_per_page = {}
    stopped_reason = None
    duplicates = 0
    attempts = 0
    try:
        for page in range(1, MAX_PAGES_PER_TYPE + 1):
            page_url = (f"https://www.naukri.com/{slug}"
                        if page == 1 else f"https://www.naukri.com/{slug}-{page}")
            attempts += 1
            before = len(urls)
            print(f"[search] {slug} page {page}: {page_url}")
            new_count, dup_count = _harvest_page(page_url, urls)
            links_per_page[str(page)] = new_count
            duplicates += dup_count
            if new_count == 0 or len(urls) == before:
                stopped_reason = "zero_new_links"
                break
            if page == MAX_PAGES_PER_TYPE:
                stopped_reason = "max_pages_reached"
        if attempts == 0:
            stopped_reason = "zero_new_links"
    except (InvalidSessionIdException, WebDriverException) as e:
        print(f"[search] failed, falling back to csv: {e}")
        stopped_reason = "request_failed"

    if urls:
        print(f"[search] {slug}: captured {len(urls)} live links "
              f"(pages_scraped={attempts}, stop={stopped_reason})")
        seen = [u for u in urls
                if not should_skip(u, visited, live=live, max_retries=MAX_RETRIES)]
        print(f"[search] {slug}: {len(seen)}/{len(urls)} actionable after visited-ledger filter")
        meta = _build_capture_meta(slug, urls, visited, live, links_per_page,
                                   attempts, stopped_reason, duplicates, csv_used=False)
        return seen, meta

    if not CSV_CFG["fallback_enabled"]:
        print(f"[search] {slug}: no live links; csv fallback disabled")
        return [], _build_capture_meta(slug, {}, visited, live, links_per_page,
                                       attempts, stopped_reason, duplicates, csv_used=False)

    csv_urls = []
    try:
        with open(JOBS_CSV, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if not row or not row.get("url"):
                    continue
                row_type = (row.get("job_type") or "").strip().lower()
                if row_type and row_type != slug.replace("-jobs", ""):
                    continue
                csv_urls.append("https://www.naukri.com" + row["url"])
    except FileNotFoundError:
        print(f"[search] {JOBS_CSV} not found")
    csv_urls = [u for u in csv_urls
                if not should_skip(u, visited, live=live, max_retries=MAX_RETRIES)]
    print(f"[search] {slug}: no live links; using {len(csv_urls)} csv fallback rows")
    meta = _build_capture_meta(slug, csv_urls, visited, live, {}, 0,
                               "csv_fallback", duplicates, csv_used=True)
    return csv_urls, meta


def _build_capture_meta(slug, urls, visited, live, links_scraped, pages_scraped,
                        stopped, duplicates, csv_used) -> dict:
    ledger = {"new": 0, "applied": 0, "skipped": 0, "review": 0,
              "failed_retryable": 0, "failed_exhausted": 0}
    for u in urls:
        b = bucket_against_ledger(u, visited, live=live, max_retries=MAX_RETRIES)
        ledger[b] = ledger.get(b, 0) + 1
    actionable = sum(1 for u in urls
                     if not should_skip(u, visited, live=live, max_retries=MAX_RETRIES))
    return {
        "pages_scraped": pages_scraped,
        "pages_stopped_reason": stopped,
        "links_per_page": links_scraped,
        "total_links_captured": len(urls),
        "duplicate_links_within_type": duplicates,
        "already_in_ledger": ledger,
        "net_new_actionable_urls": actionable,
        "csv_fallback_used": csv_used,
        "urls": list(urls),
    }


def already_applied_or_expired() -> bool:
    """Return True if this job is already applied, expired, or sent to company site."""
    already = driver.find_elements(By.ID, "already-applied")
    alerts = driver.find_elements(By.XPATH, "//*[contains(@class, 'styles_alert-message-text')]")
    company = driver.find_elements(By.ID, "company-site-button")
    expired = driver.find_elements(By.XPATH, "//*[contains(@class, 'styles_alert-message-text__')]")
    banner = driver.find_elements(By.XPATH, "//*[contains(text(), 'Applied to \"')]")
    if already or alerts or company or expired or banner:
        print("[job] skipped (already applied / expired / company-site)")
        return True
    return False


def click_apply() -> bool:
    """Click the primary Apply button; returns True if a click happened."""
    try:
        btn = WebDriverWait(driver, APPLY_TIMEOUT).until(
            EC.element_to_be_clickable(
                (By.XPATH,
                 "//button[contains(normalize-space(.), 'Apply') and "
                 "not(contains(., 'Apply on the go')) and not(contains(., 'Auto-Apply'))]")
            )
        )
        driver.execute_script("arguments[0].click();", btn)
        print("[apply] Apply button clicked")
        return True
    except (TimeoutException, NoSuchElementException) as e:
        print(f"[apply] Apply button not found: {e}")
        return False


def application_status():
    """Return 'applied', 'failed', or None based on Naukri's status header."""
    try:
        headers = driver.find_elements(By.XPATH, "//div[contains(@class, 'apply-status-header')]")
    except (InvalidSessionIdException, WebDriverException):
        return None
    for h in headers:
        cls = (h.get_attribute("class") or "").lower()
        if "green" in cls:
            print("[status] apply-status-header: applied (green)")
            return "applied"
        if "red" in cls:
            print("[status] apply-status-header: rejected (red)")
            return "failed"
    return None


def the_success_markers():
    """Return True if any 'successfully applied' marker is present."""
    try:
        if driver.find_elements(By.XPATH, success_messages):
            return True
        if driver.find_elements(
                By.XPATH,
                "//*[contains(text(), 'Application sent') or contains(text(), 'applied successfully') or contains(text(), 'Applied to \"')]"):
            return True
    except (InvalidSessionIdException, WebDriverException):
        pass
    return False


def _fail_result(status="failed", reason=None, error_type=None, tb=None, path=None):
    return JobResult(status=status, reason=reason, error_type=error_type,
                     traceback=tb, path_taken=path)


def _current_question_signature() -> str:
    """Cheap fingerprint of what's on screen right now, so we can tell a
    genuinely new question apart from re-reading the same DOM state too
    early - e.g. right after clicking Save, before the spinner resolves."""
    try:
        thank = driver.find_elements(By.XPATH, "//*[contains(translate(normalize-space(.),'THANK','thank'),'thank') and contains(translate(normalize-space(.),'RESPONSE','response'),'response')]")
        if thank:
            return "thank:" + thank[0].text.strip()[:60]
    except Exception:
        pass
    try:
        radios = driver.find_elements(By.CSS_SELECTOR, ".ssrc__radio-btn-container")
        if radios:
            labels = tuple(r.find_element(By.CSS_SELECTOR, "label").text.strip() for r in radios if r.find_element(By.CSS_SELECTOR, "label").text.strip())
            if labels:
                # ponytail: question text in sig; same-label Qs (Yes/No x N) must differ
                try:
                    _q = driver.find_elements(By.XPATH, "//li[contains(@class,'botItem')]//span")
                    _qt = _q[-1].text.strip() if _q else ""
                except Exception:
                    _qt = ""
                return "radio:" + _qt + "|" + "|".join(labels)
    except (StaleElementReferenceException, NoSuchElementException):
        pass
    try:
        bots = driver.find_elements(By.XPATH, "//li[contains(@class,'botItem')]//span")
        if bots:
            txt = bots[-1].text.strip()
            if txt:
                return "text:" + txt
    except Exception:
        pass
    try:
        chat = driver.find_element(By.XPATH, "//ul[contains(@id, 'chatList_')]")
        lis = [li.text.strip() for li in chat.find_elements(By.TAG_NAME, "li") if li.text.strip()]
        if lis:
            return "text:" + lis[-1]
    except NoSuchElementException:
        pass
    return ""


def _has_actionable_chat_input() -> bool:
    try:
        if driver.find_elements(By.CSS_SELECTOR, ".ssrc__radio-btn-container"):
            return True
    except Exception:
        pass
    try:
        if driver.find_elements(By.CSS_SELECTOR, "[contenteditable='true'], div.textArea, textarea"):
            return True
    except Exception:
        pass
    return False


def _capture_visit_screenshot(tag: str, run_id_str: str = None) -> str | None:
    try:
        from pathlib import Path as _P
        from datetime import datetime as _dt
        rid = run_id_str or _dt.now().strftime("%Y%m%d_%H%M%S")
        ts = _dt.now().strftime("%H%M%S")
        path = f"reports/visit_{tag}_{rid}_{ts}.png"
        _P("reports").mkdir(parents=True, exist_ok=True)
        driver.save_screenshot(path)
        if _P(path).stat().st_size < 1024:
            try:
                _P(path).unlink(missing_ok=True)
            except Exception:
                pass
            return None
        return path
    except Exception:
        return None


def _capture_chat_q_screenshot(q_idx: int, phase: str, run_id_str: str = None) -> str | None:
    try:
        from pathlib import Path as _P
        from datetime import datetime as _dt
        import time as _t
        rid = run_id_str or _dt.now().strftime("%Y%m%d_%H%M%S")
        ts = _dt.now().strftime("%H%M%S")
        seq = int(_t.monotonic() * 1000) % 100000
        path = f"reports/visit_chat_q{q_idx:02d}_{phase}_{rid}_{ts}_{seq}.png"
        _P("reports").mkdir(parents=True, exist_ok=True)
        driver.save_screenshot(path)
        if _P(path).stat().st_size < 1024:
            try:
                _P(path).unlink(missing_ok=True)
            except Exception:
                pass
            return None
        return path
    except Exception:
        return None


def _wait_for_next_state(prev_signature: str, prev_url: str, timeout: float = None):
    """Wait for the DOM to move past the current question.

    Returns 'navigated' | 'success' | 'failed_status' | 'new_question' | 'timeout'.

    Success (thank/response or applied marker) is only returned when no
    actionable chat input remains and the thank banner has persisted through a
    grace window - this prevents the transient per-question 'Thank you for
    your response' from ending the multi-question loop after Q1.
    """
    timeout = timeout or NEXT_QUESTION_TIMEOUT
    deadline = time.monotonic() + timeout
    empty_streak = 0
    thank_seen_since = None
    while time.monotonic() < deadline:
        if application_status() == "failed":
            return "failed_status"
        cur_url = ""
        try:
            cur_url = driver.current_url
        except Exception:
            cur_url = prev_url
        if cur_url != prev_url:
            if "multiApplyResp" in cur_url and ("406" in cur_url or "%22406" in cur_url):
                return "failed_status"
            if "multiApplyResp" in cur_url and ("200" in cur_url or "%22200" in cur_url):
                return "success"
            return "navigated"
        sig = _current_question_signature()
        if not sig:
            empty_streak += 1
            if empty_streak >= 2:
                time.sleep(NEXT_QUESTION_POLL)
                continue
        else:
            empty_streak = 0
        if sig and sig != prev_signature and not sig.startswith("thank:"):
            return "new_question"
        if sig and sig.startswith("thank:"):
            if thank_seen_since is None:
                thank_seen_since = time.monotonic()
        else:
            if sig and sig.startswith("thank:") is False and thank_seen_since is not None and sig:
                thank_seen_since = None
        if not _has_actionable_chat_input():
            if application_status() == "applied" or the_success_markers():
                if sig and sig.startswith("thank:"):
                    if thank_seen_since is not None and time.monotonic() - thank_seen_since >= 3.0:
                        return "success"
                else:
                    return "success"
            if sig and sig.startswith("thank:") and thank_seen_since is not None and time.monotonic() - thank_seen_since >= 3.0:
                return "success"
        time.sleep(NEXT_QUESTION_POLL)
    sig = _current_question_signature()
    if sig and sig != prev_signature and not sig.startswith("thank:"):
        return "new_question"
    if sig and sig.startswith("thank:") and not _has_actionable_chat_input():
        return "success"
    if not _has_actionable_chat_input() and (application_status() == "applied" or the_success_markers()):
        return "success"
    return "timeout"


def run_chat_widget_loop() -> JobResult:
    """Answer the inline chat widget questions.

    Returns a JobResult with status 'applied'|'failed' and path_taken set to
    'chat_widget'. On failure, captures the error_type + traceback string (not
    print-and-discard) so the visit report can attribute it.
    """
    global _last_chat_qa, _chat_transcript_buf
    _chat_transcript_buf = []
    def _attach_transcript(res):
        try:
            res.chat_transcript = list(_chat_transcript_buf)
            res.screenshots = [s for e in _chat_transcript_buf for s in [e.get("screenshot_after_save"), e.get("screenshot_new_q"), e.get("screenshot_success")] if s]
            res.screenshot = res.screenshots[0] if res.screenshots else getattr(res, "screenshot", None)
        except Exception:
            pass
        return res
    last_err = None  # (error_type, reason, traceback_str)
    answered_count = 0
    answered_texts: set = set()
    for _q_round in range(MAX_QUESTIONS_PER_JOB):
        status = application_status()
        if status == "applied" or the_success_markers():
            if not _has_actionable_chat_input():
                return _attach_transcript(_fail_result("applied", path="chat_widget"))
        if status == "failed":
            return _attach_transcript(_fail_result("failed", reason="apply rejected by status header", path="chat_widget"))

        url_before = driver.current_url
        sig_before = _current_question_signature()
        cur_question_text = None
        if sig_before.startswith("text:"):
            cur_question_text = sig_before[5:]

        answered = False
        try:
            if answer_radio_questions(answered=answered_texts):
                answered = True
        except Exception as e:
            if isinstance(e, ModelOverloaded):
                raise
            last_err = (type(e).__name__, "radio step error", traceback.format_exc())

        if not answered:
            try:
                if answer_text_question(answered=answered_texts):
                    answered = True
            except Exception as e:
                if isinstance(e, ModelOverloaded):
                    raise
                last_err = (type(e).__name__, "text step error", traceback.format_exc())

        if not answered:
            if _current_question_signature() and _current_question_signature() != sig_before:
                answered = True
            else:
                # ponytail: one patience loop for slow renders; per-Q Save still advances
                _waited = 0.0
                while not answered and _waited < 10.0:
                    time.sleep(1.0)
                    _waited += 1.0
                    if not _has_actionable_chat_input():
                        continue  # ponytail: no inputs yet — wait, don't burn LLM calls
                    try:
                        if answer_radio_questions(answered=answered_texts):
                            answered = True
                            break
                    except Exception as e:
                        if isinstance(e, ModelOverloaded):
                            raise
                        last_err = (type(e).__name__, "radio retry error", traceback.format_exc())
                    try:
                        if answer_text_question(answered=answered_texts):
                            answered = True
                            break
                    except Exception as e:
                        if isinstance(e, ModelOverloaded):
                            raise
                        last_err = (type(e).__name__, "text retry error", traceback.format_exc())
                    if _current_question_signature() and _current_question_signature() != sig_before:
                        answered = True
                        break
                if not answered:
                    if not _has_actionable_chat_input() and driver.find_elements(By.XPATH, "//*[contains(translate(normalize-space(.),'THANK','thank'),'thank') and contains(translate(normalize-space(.),'RESPONSE','response'),'response')]"):
                        return _attach_transcript(_fail_result("applied", path="chat_widget"))
                    break

        if answered:
            answered_count += 1
            if cur_question_text:
                answered_texts.add(cur_question_text)
            else:
                try:
                    bots = driver.find_elements(By.XPATH, "//li[contains(@class,'botItem')]//span")
                    if bots:
                        for el in reversed(bots):
                            t = el.text.strip()
                            if t and t not in answered_texts:
                                answered_texts.add(t)  # ponytail: radio answers recorded like text ones
                                break
                except Exception:
                    pass
            try:
                rid = run_id()
                ss_after = _capture_chat_q_screenshot(answered_count, "after_save", rid)
                gem_before = getattr(__import__('gemini_api'), 'job_count', lambda: 0)() if 'gemini_api' in __import__('sys').modules else 0
                qa = dict(_last_chat_qa) if _last_chat_qa else {"type": "unknown", "q": cur_question_text or sig_before, "answer": "unknown"}
                entry = {"q_idx": answered_count, "type": qa.get("type"), "q": qa.get("q"), "options": qa.get("options"), "answer": qa.get("answer"), "provider": qa.get("provider", "gemini"), "gemini_calls_before": gem_before, "sig_before": sig_before, "screenshot_after_save": ss_after, "timestamp": datetime.now().isoformat()}
                _chat_transcript_buf.append(entry)
                _last_chat_qa = {}
            except Exception:
                pass

        outcome = _wait_for_next_state(sig_before, url_before)
        if outcome == "new_question":
            try:
                last = _chat_transcript_buf[-1] if _chat_transcript_buf else None
                if last is not None:
                    ss_new = _capture_chat_q_screenshot(last["q_idx"], "new_question", run_id())
                    last["screenshot_new_q"] = ss_new
                    last["sig_after"] = _current_question_signature()
            except Exception:
                pass
            continue
        if outcome == "success":
            if _has_actionable_chat_input():
                continue
            try:
                if _chat_transcript_buf:
                    ss_final = _capture_chat_q_screenshot(len(_chat_transcript_buf), "success", run_id())
                    _chat_transcript_buf[-1]["screenshot_success"] = ss_final
            except Exception:
                pass
            res = _fail_result("applied", path="chat_widget")
            res.chat_transcript = list(_chat_transcript_buf)
            res.screenshots = [s for e in _chat_transcript_buf for s in [e.get("screenshot_after_save"), e.get("screenshot_new_q")] if s]
            res.screenshot = res.screenshots[0] if res.screenshots else None
            return res
        if outcome == "navigated":
            if application_status() == "applied" or the_success_markers():
                res = _fail_result("applied", path="chat_widget")
                res.chat_transcript = list(_chat_transcript_buf)
                res.screenshots = [s for e in _chat_transcript_buf for s in [e.get("screenshot_after_save"), e.get("screenshot_new_q")] if s]
                res.screenshot = res.screenshots[0] if res.screenshots else None
                return res
            print(f"[chat] URL changed after answer ({driver.current_url}); no explicit success marker.")
            return _attach_transcript(_fail_result("skipped", reason="navigated away without success marker", path="chat_widget"))
        if outcome == "failed_status":
            return _attach_transcript(_fail_result("skipped", reason="apply rejected by status header or 406", path="chat_widget"))
        if outcome == "timeout":
            time.sleep(1.0)
            sig_now = _current_question_signature()
            if sig_now and sig_now != sig_before and not sig_now.startswith("thank:"):
                continue
            if not _has_actionable_chat_input() and driver.find_elements(By.XPATH, "//*[contains(translate(normalize-space(.),'THANK','thank'),'thank') and contains(translate(normalize-space(.),'RESPONSE','response'),'response')]"):
                return _attach_transcript(_fail_result("applied", path="chat_widget"))
            if _has_actionable_chat_input():
                continue
        last_err = last_err or (None, "next question did not render in time", None)
        break

    if last_err:
        etype, reason, tb = last_err
        return _attach_transcript(_fail_result("failed", reason=reason, error_type=etype, tb=tb, path="chat_widget"))
    return _attach_transcript(_fail_result("failed", reason="no actionable chat input", path="chat_widget"))


def _verify_late_success(url: str) -> bool:
    """Re-visit a job fresh and check Naukri's own already-applied marker.

    Used when the chat loop gave up ambiguously (not an explicit rejection)
    - if Naukri now says already-applied, the application went through even
    though our loop missed the confirmation moment."""
    try:
        driver.get(url)
        time.sleep(TIMING_CFG["nav_wait"])
        return bool(driver.find_elements(By.ID, "already-applied"))
    except (InvalidSessionIdException, WebDriverException):
        return False


def _job_key(url: str) -> str:
    """Normalize a job URL to its trailing id for history matching."""
    import re as _re
    m = _re.search(r"(\d{5,})\s*$", str(url or "").rstrip("/"))
    return m.group(1) if m else str(url or "").lower()


def _fetch_history_applied(max_pages: int = 5) -> set:
    """One sweep of myapply/historypage; returns normalized job keys. Best-effort, never raises."""
    # ponytail: ids ride jobId= params (no /job-listings hrefs on history cards); scroll + pager fallback
    import re as _re
    found = set()
    try:
        driver.get("https://www.naukri.com/myapply/historypage")
        time.sleep(TIMING_CFG["nav_wait"])
        for _ in range(max(1, max_pages)):
            try:
                for a in driver.find_elements(By.XPATH, "//a[contains(@href,'jobId=')]"):
                    try:
                        href = a.get_attribute("href") or ""
                    except Exception:
                        continue
                    m = _re.search(r"jobId=(\d+)", href)
                    if m:
                        found.add(m.group(1))
            except Exception:
                pass
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            except Exception:
                pass
            try:
                nxt = driver.find_elements(By.XPATH, "//*[self::a or self::button][contains(normalize-space(.),'Next') or contains(normalize-space(.),'Load More') or contains(normalize-space(.),'Show More')]")
                nxt = [b for b in nxt if b.is_displayed() and b.is_enabled()]
                if not nxt:
                    break
                driver.execute_script("arguments[0].click();", nxt[0])
                time.sleep(TIMING_CFG["nav_wait"])
            except Exception:
                break
    except Exception as e:
        print(f"[verify] history sweep warn: {e}")
    return found


def _apply_history_verdict(visit_results: list, max_pages: int = 5) -> tuple:
    """Flip failed/review matches to applied via one history sweep. Applied-wins; never downgrades."""
    pending = [r for r in visit_results if r.status in ("failed", "review")]
    our_keys = {_job_key(r.url) for r in visit_results if r.url}
    claimed = {_job_key(r.url) for r in visit_results if r.url and r.status == "applied"}
    if not pending:
        return 0, 0, {"claimed_applied": len(claimed), "confirmed": len(claimed), "extras_on_history": 0}
    applied_keys = _fetch_history_applied(max_pages)
    flips = 0
    for r in pending:
        if r.url and _job_key(r.url) in applied_keys:
            r.status = "applied"
            r.reason = "confirmed via history"
            r.verified = "history"
            flips += 1
    claimed = {_job_key(r.url) for r in visit_results if r.url and r.status == "applied"}
    agreement = {"claimed_applied": len(claimed), "confirmed": len(claimed & applied_keys),
                 "extras_on_history": len(applied_keys - our_keys)}
    print(f"[verify] history sweep: {flips}/{len(pending)} flipped ({len(applied_keys)} applied on record) agreement={agreement}")
    return flips, len(pending), agreement


def _maybe_curate_and_upload(url: str, jd_text: str) -> tuple:
    import os
    curation_score = None
    curation_performed = False
    resume_path = None
    upload_status = None
    if not CURATION_CFG.get("enabled"):
        return curation_score, curation_performed, resume_path, upload_status
    cb_early = load_curation_budget()
    if not curation_budget_ok(cb_early, CURATION_CFG.get("gemini_daily_limit", 50)):
        print("[curation] budget exhausted (early), skipping curation")
        return curation_score, curation_performed, resume_path, upload_status
    base_md_path = os.path.join(CURATION_CFG.get("dir", "resumes"), "base.md")
    active_json = CURATION_CFG.get("active_resume", "resumes/active.json")
    if not os.path.exists(base_md_path):
        print("[curation] base.md missing; run: python -m resume.ingest <resume.pdf>")
        return curation_score, curation_performed, resume_path, upload_status
    with open(base_md_path, encoding="utf-8") as f:
        base_md = f.read()
    active_md = base_md
    if os.path.exists(active_json):
        try:
            with open(active_json, encoding="utf-8") as f:
                aj = json.load(f)
            ap = aj.get("active_pdf")
            am = aj.get("active_md")
            if am and os.path.exists(am):
                with open(am, encoding="utf-8") as mf:
                    active_md = mf.read()
        except Exception:
            pass
    try:
        from resume.scorer import score_jd_vs_resume
        from resume.curator import curate_md, save_curated
        from resume.builder import md_to_pdf
        from resume.uploader import upload_to_naukri
        curation_budget = load_curation_budget()
        if not curation_budget_ok(curation_budget, CURATION_CFG.get("gemini_daily_limit", 50)):
            print("[curation] budget exhausted, skipping curation")
            return curation_score, curation_performed, resume_path, upload_status
        scored = score_jd_vs_resume(jd_text, active_md, timeout=CURATION_CFG.get("gemini_timeout", 40))
        curation_score = scored.get("score", 0.0)
        try:
            from web.db import record_jd as _rjd
            _rjd(os.environ.get("USER_ID"), url, "", "", jd_text)
        except Exception:
            pass
        print(f"[curation] score={curation_score} threshold={CURATION_CFG.get('match_threshold')} matched={len(scored.get('matched',[]))}/{len(scored.get('keywords',[]))}")
        if curation_score is not None and curation_score >= float(CURATION_CFG.get("match_threshold", 0.5)):
            print("[curation] score above threshold, skipping curate")
            return curation_score, False, resume_path, "skipped_high_score"
        curated_md = curate_md(base_md, jd_text, timeout=CURATION_CFG.get("gemini_timeout", 40))
        md_path, h = save_curated(curated_md, jd_text, out_dir=os.path.join(CURATION_CFG.get("dir", "resumes"), "curated"))
        pdf_path = os.path.join(CURATION_CFG.get("dir", "resumes"), "pdf", f"{h}.pdf")
        md_to_pdf(md_path, pdf_path)
        resume_path = pdf_path
        curation_performed = True
        upload_result = upload_to_naukri(driver, os.path.abspath(pdf_path), timeout=CURATION_CFG.get("upload_timeout", 25))
        if isinstance(upload_result, tuple):
            ok, upload_info = upload_result
        else:
            ok, upload_info = bool(upload_result), {}
        upload_info = upload_info or {}
        if not ok:
            upload_status = f"upload_failed:{upload_info.get('step','wait')}:{str(upload_info.get('error',''))[:80]}"
            print(f"[curation] upload {upload_status}: {pdf_path} alerts={upload_info.get('alerts')} screenshot={upload_info.get('screenshot')}")
            dump_path = f"reports/upload_debug_{h}.json"
            try:
                Path("reports").mkdir(parents=True, exist_ok=True)
                with open(dump_path, "w") as df:
                    json.dump({"jd_hash": h, "pdf": pdf_path, "upload_info": upload_info, "score": curation_score, "traceback": upload_info.get("traceback","")[:3000]}, df, indent=2)
                print(f"[curation] upload debug dumped {dump_path}")
            except Exception:
                pass
            return curation_score, True, resume_path, upload_status
        upload_status = "uploaded"
        print(f"[curation] upload {upload_status}: {pdf_path} alerts={upload_info.get('alerts')} screenshot={upload_info.get('screenshot')}")
        try:
            dump_path = f"reports/upload_debug_{h}.json"
            Path("reports").mkdir(parents=True, exist_ok=True)
            with open(dump_path, "w") as df:
                json.dump({"jd_hash": h, "pdf": pdf_path, "upload_info": upload_info, "score": curation_score, "status": "uploaded"}, df, indent=2)
        except Exception:
            pass
        try:
            os.makedirs(os.path.dirname(active_json), exist_ok=True)
            with open(active_json, "w", encoding="utf-8") as af:
                json.dump({"active_md": md_path, "active_pdf": pdf_path, "sha": h}, af, indent=2)
        except Exception as e:
            print(f"[curation] active.json write failed: {e}")
        return curation_score, curation_performed, resume_path, upload_status
    except Exception as e:
        print(f"[curation] error: {e} {traceback.format_exc()}")
        return curation_score, curation_performed, resume_path, f"error:{type(e).__name__}"


def _process_job_inner(url: str, slug: str) -> JobResult:
    """Core process_job body; duration/counter/type attribution handled by process_job."""
    mark = "[job] " + url
    print(mark)
    try:
        driver.get(url)
        time.sleep(TIMING_CFG["nav_wait"])
    except (InvalidSessionIdException, WebDriverException) as e:
        print(f"{mark} navigation failed: {e!r}")
        return _fail_result("failed", reason="navigation failed", error_type=type(e).__name__,
                            tb=traceback.format_exc(), path="chat_widget")

    if driver.current_url.rstrip("/").endswith("homepage"):
        print(f"{mark} redirected to homepage (invalid/expired link)")
        return _fail_result("failed", reason="redirected to homepage (invalid/expired link)", path="chat_widget")

    if already_applied_or_expired():
        return JobResult(status="skipped", path_taken="none")

    jd_cache = ""
    try:
        from resume.jd import extract_jd
        jd_cache = extract_jd(driver)
    except Exception:
        jd_cache = ""

    if not click_apply():
        return _fail_result("failed", reason="apply button not found", error_type="NoSuchElementException", path="chat_widget")

    time.sleep(TIMING_CFG["apply_wait"])

    surf_state = "unknown"
    try:
        from resume.jd import has_surface
        surf = has_surface(driver)
        surf_state = surf
        if surf == "none":
            # ponytail: slow renders get one more look before failing
            time.sleep(TIMING_CFG["nav_wait"])
            try:
                surf = has_surface(driver)
                surf_state = surf
            except Exception:
                pass
        if surf == "none" and the_success_markers():
            # ponytail: Naukri's own receipt ("Applied to ...") — nothing left to fill
            print("[gate] post-apply confirmation banner; marking applied")
            r = _fail_result("applied", reason="confirmed via banner", path="chat_widget")
            r.verified = "banner"
            ss = _capture_visit_screenshot("no_surface", run_id())
            if ss:
                r.screenshot = ss
            return r
        if surf == "none":
            print("[gate] no form or chat detected, skipping curation/upload")
            ss = _capture_visit_screenshot("no_surface", run_id())
            r = _fail_result("failed", reason="no_form_or_chat", path="chat_widget")
            if ss:
                r.screenshot = ss
            return r
    except Exception as e:
        print(f"[gate] probe error: {e}")

    cb = load_curation_budget()
    if not curation_budget_ok(cb, CURATION_CFG.get("gemini_daily_limit", 50)):
        print("[curation] budget exhausted (caller early), skipping curate")
        curation_score, curation_performed, resume_path, upload_status = None, False, None, None
    else:
        curation_score, curation_performed, resume_path, upload_status = _maybe_curate_and_upload(url, jd_cache)
    if upload_status and (upload_status.startswith("upload_failed") or upload_status.startswith("error:")):
        ss = _capture_visit_screenshot("upload_failed", run_id())
        r = _fail_result("failed", reason="resume_upload_failed", path="chat_widget")
        r.curation_score = curation_score
        r.curation_performed = curation_performed
        r.resume_path = resume_path
        r.upload_status = upload_status
        r.screenshot = ss
        r.gemini_error = upload_status
        return r
    if upload_status == "uploaded":
        try:
            driver.get(url)
            time.sleep(TIMING_CFG["nav_wait"])
            if not click_apply():
                r = _fail_result("failed", reason="apply button not found after resume upload", path="chat_widget")
                r.curation_score = curation_score
                r.curation_performed = curation_performed
                r.resume_path = resume_path
                r.upload_status = upload_status
                return r
            time.sleep(TIMING_CFG["apply_wait"])
        except Exception as e:
            r = _fail_result("failed", reason="re-navigate after upload failed", error_type=type(e).__name__, tb=traceback.format_exc(), path="chat_widget")
            r.curation_score = curation_score
            r.curation_performed = curation_performed
            r.resume_path = resume_path
            r.upload_status = upload_status
            return r

    def _attach_curation(res: JobResult) -> JobResult:
        res.curation_score = curation_score
        res.curation_performed = curation_performed
        res.resume_path = resume_path
        res.upload_status = upload_status
        return res

    chat = run_chat_widget_loop()
    if chat.status in ("applied", "skipped"):
        return _attach_curation(chat)
    if chat.status == "failed" and chat.reason and ("navigated" in chat.reason or "406" in chat.reason or "rejected" in chat.reason):
        return _attach_curation(chat)

    # ponytail: any chat failure gets one revisit; form failures ride the history sweep (O(1))
    if chat.status == "failed" and _verify_late_success(url):
        print("[verify] late success confirmed via already-applied marker; overriding to applied")
        res = JobResult(status="applied", path_taken="chat_widget", reason="confirmed via revisit")
        res.verified = "revisit"
        return _attach_curation(res)

    # Chat flow failed or produced no questions; fall back to the full form only when appropriate.
    if chat.reason and "navigated" in chat.reason:
        return _attach_curation(chat)
    if surf_state in ("chat_widget", "both") and chat.reason in ("no actionable chat input", "next question did not render in time", "no_form_or_chat"):
        ss = _capture_visit_screenshot("chat_no_input", run_id())
        r = _fail_result("failed", reason=chat.reason or "no actionable chat input", path="chat_widget")
        if ss:
            r.screenshot = ss
        r.error_type = chat.error_type
        r.traceback = chat.traceback
        return _attach_curation(r)
    try:
        fields = _extract_with_retry(timeout_secs=4)
    except Exception as e:
        ss = _capture_visit_screenshot("form_extract_error")
        fb_path = "chat_widget" if surf_state in ("chat_widget", "both") else "full_form"
        r = _fail_result("failed", reason="form field extraction error", error_type=type(e).__name__, tb=traceback.format_exc(), path=fb_path)
        r.screenshot = ss
        return _attach_curation(r)
    if not fields:
        ss = _capture_visit_screenshot("no_form_fields")
        fb_path = "chat_widget" if surf_state in ("chat_widget", "both") else "full_form"
        r = _fail_result("failed", reason="no form fields found", path=fb_path)
        r.screenshot = ss
        return _attach_curation(r)

    try:
        answers = get_structured_answers(fields)
    except Exception as e:
        if isinstance(e, ModelOverloaded):
            raise
        ss = _capture_visit_screenshot("structured_answers_error")
        r = _fail_result("failed", reason="structured answers error", error_type=type(e).__name__, tb=traceback.format_exc(), path="full_form")
        r.screenshot = ss
        return _attach_curation(r)

    try:
        plan = fill_form_dry_run(fields, answers)
    except Exception as e:
        ss = _capture_visit_screenshot("form_fill_error")
        r = _fail_result("failed", reason="form fill error", error_type=type(e).__name__, tb=traceback.format_exc(), path="full_form")
        r.screenshot = ss
        return _attach_curation(r)

    _prov = _llm_provider()
    for _p in plan:
        _p["provider"] = _prov  # ponytail: whole-form = one Gemini call; rows share its provider

    unanswered_required = [p["label"] for p in plan if p["required"] and not p["answered"]]
    if unanswered_required:
        print(f"[form] NOT submitting: {len(unanswered_required)} required fields unanswered: {unanswered_required}")
        ss = _capture_visit_screenshot("required_incomplete")
        r = _fail_result("failed", reason=f"required fields incomplete: {unanswered_required}", path="full_form")
        r.screenshot = ss
        r.form_plan = plan  # ponytail: answers ride the result into forms.json
        return _attach_curation(r)

    print("[form] submitting form...")
    try:
        submit_btn = driver.find_element(
            By.XPATH, "//button[contains(normalize-space(.), 'Submit') or contains(normalize-space(.), 'Save & Continue') or contains(normalize-space(.), 'Submit Application')]")
        driver.execute_script("arguments[0].click();", submit_btn)
    except NoSuchElementException as e:
        print("[form] submit button not found; marking failed")
        ss = _capture_visit_screenshot("submit_not_found")
        r = _fail_result("failed", reason="submit button not found", error_type=type(e).__name__, tb=traceback.format_exc(), path="full_form")
        r.screenshot = ss
        r.form_plan = plan  # ponytail: answers ride the result into forms.json
        return _attach_curation(r)
    time.sleep(TIMING_CFG["submit_wait"])
    st = application_status()
    if st == "failed":
        print("[form] submit finished with rejected/review status")
        ss = _capture_visit_screenshot("submit_rejected")
        r = _fail_result("failed", reason="submit finished with rejected/review status", path="full_form")
        r.screenshot = ss
        r.form_plan = plan  # ponytail: answers ride the result into forms.json
        return _attach_curation(r)
    if st == "applied":
        r = _fail_result("applied", path="full_form")
        r.form_plan = plan  # ponytail: answers ride the result into forms.json
        return _attach_curation(r)
    r = _fail_result("review", reason="submit returned review status", path="full_form")
    r.form_plan = plan  # ponytail: answers ride the result into forms.json
    return _attach_curation(r)


def process_job(url: str, slug: str = "") -> JobResult:
    """Attempt to apply to a single job URL. Returns a JobResult."""
    start = time.monotonic()
    reset_job_counter()
    reset_curation_counter()
    try:
        res = _process_job_inner(url, slug)
    except InvalidSessionIdException:
        raise
    except ModelOverloaded:
        raise
    except Exception as e:
        res = _fail_result("failed", reason="unhandled exception", error_type=type(e).__name__,
                           tb=traceback.format_exc(), path="chat_widget")
    res.job_type = slug.replace("-jobs", "")
    res.url = url
    res.duration_seconds = round(time.monotonic() - start, 1)
    res.gemini_calls_this_job = gemini_job_count()
    try:
        res.curation_calls_this_job = curation_count()
    except Exception:
        pass
    if res.status == "failed":
        _record_error(url, res)
    return res


def _record_error(url: str, res) -> None:
    # ponytail: one failure line per failed job; dashboard reads last 20
    if (res.status or "") != "failed":
        return
    try:
        ef = _os.path.join(REPORTS_CFG.get("dir", "reports"), "errors.jsonl")
        _os.makedirs(_os.path.dirname(ef) or ".", exist_ok=True)
        with open(ef, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": datetime.now().isoformat(), "run_id": _RUN_ID, "url": url, "job_type": res.job_type, "error_type": res.error_type, "reason": (res.reason or "")[:300], "traceback": (res.traceback or "")[:2000], "path": res.path_taken}) + "\n")
    except Exception:
        pass


def _llm_provider() -> str:
    # ponytail: single read of gemini_api.last_provider; mixed forms collapse to last writer
    try:
        import gemini_api as _ga2
        return _ga2.last_provider or "gemini"
    except Exception:
        return "gemini"


def answer_radio_questions(answered: set = None) -> bool:
    radio_buttons = driver.find_elements(By.CSS_SELECTOR, ".ssrc__radio-btn-container")
    if not radio_buttons:
        return False

    q_els = driver.find_elements(By.XPATH, "//li[contains(@class, 'botItem')]//span")
    question = q_els[-1].text if q_els else ""
    if answered is not None and question and question in answered:
        return False
    print(f"[radio] Q: {question}")

    options = []
    for idx, button in enumerate(radio_buttons, start=1):
        label = button.find_element(By.CSS_SELECTOR, "label").text
        value = button.find_element(By.CSS_SELECTOR, "input").get_attribute("value")
        options.append(f"{idx}. {label} (Value: {value})")
    options_str = "\n".join(options)
    print("[radio] options:\n" + options_str)

    answer = bard_flash_response(
        f"Candidate context (JSON):\n{json.dumps(load_candidate_profile(), indent=2)}\n\n"
        f"Question: {question}\nOptions:\n{options_str}\n\n"
        "Reply with ONLY the option number that best matches the candidate.",
        APPLY_CFG["gemini_timeout"])
    if not answer or not answer.strip():
        print("[radio] Gemini empty/timeout/429 — skipping (prefer skipped over NEEDS_REVIEW)")
        return False
    answer = answer.strip()
    if not answer.isdigit() or int(answer) not in range(1, len(radio_buttons) + 1):
        print(f"[radio] Gemini returned invalid option {answer!r} — skipping")
        return False
    global _last_chat_qa
    _last_chat_qa = {"type": "radio", "q": question, "options": options, "answer": answer, "provider": _llm_provider()}

    # Re-query fresh handles after the API gap and retry on staleness once.
    for attempt in range(2):
        try:
            fresh = driver.find_elements(By.CSS_SELECTOR, ".ssrc__radio-btn-container")
            target = fresh[int(answer) - 1].find_element(By.CSS_SELECTOR, "input")
            driver.execute_script("arguments[0].click();", target)
            break
        except (StaleElementReferenceException, NoSuchElementException):
            if attempt == 1:
                raise
            time.sleep(TIMING_CFG["click_delay"])
    time.sleep(TIMING_CFG["click_delay"])

    save_btn = WebDriverWait(driver, APPLY_TIMEOUT).until(
        EC.element_to_be_clickable(
            (By.XPATH, "//button[contains(normalize-space(.), 'Save') or "
                       "contains(normalize-space(.), 'Save & Continue')]"))
    )
    driver.execute_script("arguments[0].click();", save_btn)
    time.sleep(TIMING_CFG["save_delay"])
    if answered is not None and question:
        answered.add(question)
    return True


def answer_text_question(answered: set = None) -> bool:
    question = None
    bots = driver.find_elements(By.XPATH, "//li[contains(@class,'botItem')]//span")
    if bots:
        for el in reversed(bots):
            txt = el.text.strip()
            if txt:
                if answered is not None and txt in answered:
                    continue
                question = txt
                break
        if question is None and answered is not None:
            return False
    if not question:
        try:
            chat = driver.find_element(By.XPATH, "//ul[contains(@id, 'chatList_')]")
        except NoSuchElementException:
            return False
        lis = chat.find_elements(By.TAG_NAME, "li")
        for li in reversed(lis):
            txt = li.text.strip()
            if txt and "thank" not in txt.lower():
                if answered is not None and txt in answered:
                    continue
                question = txt
                break
    if not question:
        return False
    if answered is not None and question in answered:
        return False
    print(f"[text] Q: {question}")

    response = bard_flash_response(
        f"Candidate context (JSON):\n{json.dumps(load_candidate_profile(), indent=2)}\n\n"
        f"Question: {question}\n\n"
        "Answer using ONLY the candidate profile. If the question is not covered "
        "by the profile, reply literally NEEDS_REVIEW.",
        APPLY_CFG["gemini_timeout"])
    if not response or not response.strip():
        print("[text] Gemini empty/timeout/429 — skipping (prefer skipped)")
        return False
    if response.strip() == "NEEDS_REVIEW":
        print("[text] NEEDS_REVIEW — skipping (prefer skipped)")
        return False
    global _last_chat_qa
    _last_chat_qa = {"type": "text", "q": question, "answer": response.strip(), "options": None, "provider": _llm_provider()}
    input_field = driver.find_element(
        By.CSS_SELECTOR, "[contenteditable='true'], div.textArea, textarea")
    input_field.click()
    input_field.send_keys(response)
    time.sleep(TIMING_CFG["click_delay"])

    # Chat widgets generally send on Enter; click Save fallback if it exists.
    input_field.send_keys(Keys.ENTER)
    time.sleep(TIMING_CFG["click_delay"])
    try:
        save_click = driver.find_element(
            By.XPATH, "//button[contains(normalize-space(.), 'Save') or contains(normalize-space(.), 'Send')]")
        driver.execute_script("arguments[0].click();", save_click)
    except NoSuchElementException:
        pass
    time.sleep(TIMING_CFG["save_delay"])
    if answered is not None:
        answered.add(question)
    return True


def _norm(s: str) -> str:
    """Normalize a label for tolerant key matching."""
    return "".join(str(s or "").lower().split())


def extract_form_fields() -> list:
    """Scrape the open application form into a structured field list.

    Each item: {label, field_type, options, required, container}.
    Container handles go stale; use immediately, don't cache across waits.
    """
    fields = []
    containers = driver.find_elements(
        By.CSS_SELECTOR, "[class*='form-field'], [class*='formField'], [class*='styles_form-box']")

    for c in containers:
        try:
            label_el = c.find_element(By.CSS_SELECTOR, "label, [class*='label']")
            label = label_el.text.strip()
            if not label:
                continue
        except NoSuchElementException:
            continue

        required = bool(c.find_elements(
            By.CSS_SELECTOR, "[class*='required'], .mandatory")) or "*" in label

        if c.find_elements(By.TAG_NAME, "select"):
            sel = c.find_element(By.TAG_NAME, "select")
            options = [o.text.strip() for o in sel.find_elements(By.TAG_NAME, "option") if o.text.strip()]
            fields.append({"label": label, "field_type": "select", "options": options,
                           "required": required, "container": c})
        elif c.find_elements(By.CSS_SELECTOR, "input[type='radio']"):
            options = []
            for r in c.find_elements(By.CSS_SELECTOR, "input[type='radio']"):
                try:
                    opt = r.find_element(By.XPATH, "./following-sibling::*[1]").text.strip()
                except NoSuchElementException:
                    opt = r.get_attribute("value")
                options.append(opt)
            fields.append({"label": label, "field_type": "radio", "options": options,
                           "required": required, "container": c})
        elif c.find_elements(By.CSS_SELECTOR, "input[type='number']"):
            fields.append({"label": label, "field_type": "number", "options": None,
                           "required": required, "container": c})
        elif c.find_elements(By.CSS_SELECTOR, "input[type='text'], input:not([type])"):
            fields.append({"label": label, "field_type": "text", "options": None,
                           "required": required, "container": c})
        elif c.find_elements(By.CSS_SELECTOR, "textarea, [contenteditable='true']"):
            fields.append({"label": label, "field_type": "textarea", "options": None,
                           "required": required, "container": c})
        else:
            print(f"[form] unrecognized field type for label {label!r}")

    print(f"[form] extracted {len(fields)} fields")
    return fields


def _probe_form_containers():
    try:
        js = """
        function deepQuery(sel){
          const out=[];
          function walk(root){
            try { root.querySelectorAll(sel).forEach(e=>out.push(e)); } catch(e) {}
            try { root.querySelectorAll('*').forEach(el=>{
              if(el.shadowRoot) walk(el.shadowRoot);
              if(el.tagName==='IFRAME'){ try{ if(el.contentDocument) walk(el.contentDocument);}catch(e){} }
            });} catch(e) {}
          }
          walk(document);
          return out;
        }
        return deepQuery("[class*='form-field'], [class*='formField'], [class*='styles_form-box']").length;
        """
        cnt = driver.execute_script(js)
        return int(cnt) if cnt is not None else 0
    except Exception:
        return None


def _extract_with_retry(timeout_secs=4):
    deadline = time.monotonic() + timeout_secs
    last = []
    while time.monotonic() < deadline:
        try:
            fields = extract_form_fields()
            if fields:
                return fields
            probe = _probe_form_containers()
            if probe is not None and probe == 0:
                time.sleep(0.5)
                continue
            elif probe is not None and probe > 0:
                time.sleep(0.5)
                fields = extract_form_fields()
                if fields:
                    return fields
            else:
                time.sleep(0.5)
        except Exception:
            time.sleep(0.5)
        last = []
    return last


def get_structured_answers(fields) -> dict:
    """One Gemini call returning {label: answer} for the whole form."""
    field_desc = "\n".join(
        f"- {f['label']} (type={f['field_type']}"
        + (f", options={f['options']}" if f["options"] else "")
        + (", REQUIRED" if f["required"] else "")
        + ")"
        for f in fields
    )
    prompt = (
        "You are filling a job application form. Candidate profile:\n"
        f"{json.dumps(load_candidate_profile(), indent=2)}\n\n"
        "Form fields:\n"
        f"{field_desc}\n\n"
        "Return ONLY a JSON object mapping each field's label to its answer string. "
        "For select/radio fields the answer must exactly match one of the given options. "
        "If the profile value for a field is NEEDS_REVIEW, return the literal string "
        "NEEDS_REVIEW for it. "
        "Do not invent values. Return only raw JSON, no fences, no prose."
    )
    raw = bard_flash_response(prompt, APPLY_CFG["form_gemini_timeout"], preset="form")
    try:
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(cleaned)
        # match against extracted labels tolerantly
        norm_map = {_norm(f["label"]): f["label"] for f in fields}
        answers = {}
        for key, val in parsed.items():
            target = norm_map.get(_norm(key), key)
            answers[target] = val
        return answers
    except (json.JSONDecodeError, AttributeError) as e:
        print(f"[form] failed to parse Gemini JSON: {e!r}\nraw: {raw!r}")
        return {}


def fill_form_dry_run(fields, answers) -> list:
    """Fill each field with its answer. Returns a review plan. NEVER submits."""
    from selenium.webdriver.support.ui import Select
    plan = []
    norm_answers = {_norm(k): v for k, v in answers.items()}
    for f in fields:
        label = f["label"]
        answer = norm_answers.get(_norm(label))
        if answer == "NEEDS_REVIEW":
            answer = None
        plan.append({"label": label, "type": f["field_type"], "answer": answer,
                     "required": f["required"], "answered": answer is not None})

        if answer is None:
            continue

        try:
            c = f["container"]
            if f["field_type"] in ("text", "number"):
                inp = c.find_element(By.CSS_SELECTOR, "input")
                inp.clear()
                inp.send_keys(str(answer))
            elif f["field_type"] == "textarea":
                inp = c.find_element(By.CSS_SELECTOR, "textarea, [contenteditable='true']")
                inp.send_keys(str(answer))
            elif f["field_type"] == "select":
                Select(c.find_element(By.TAG_NAME, "select")).select_by_visible_text(str(answer))
            elif f["field_type"] == "radio":
                radios = c.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                labels = f["options"]
                if answer in labels:
                    idx = labels.index(answer)
                    driver.execute_script("arguments[0].click();", radios[idx])
        except (NoSuchElementException, ValueError) as e:
            print(f"[form] fill failed for {label!r}: {e!r}")

    print("\n[form] DRY RUN PLAN:")
    for p in plan:
        flag = "FILLED" if p["answered"] else ("MISSING" if p["required"] else "skip")
        print(f"  [{flag}] {p['label']!r} ({p['type']}) -> {p['answer']!r}")
    return plan


def main():
    global DRY_RUN, SEARCH_SLUGS, _RUN_ID
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true",
                        help="Actually submit full forms instead of dry-run")
    parser.add_argument("--types", nargs="*", default=None,
                        help="Override job-type slugs (e.g. --types python backend). "
                             "Appends '-jobs' if missing.")
    args = parser.parse_args()
    if args.live:
        DRY_RUN = False
        print("LIVE mode: forms will be submitted.")
    if args.types:
        SEARCH_SLUGS = [t if t.endswith("-jobs") else t + "-jobs" for t in args.types]
        print(f"Types overridden via CLI: {SEARCH_SLUGS}")

    # Warm the profile cache (and validate the file) before any job processing,
    # on EVERY run (dry-run and live). Fails loud at startup if the file is
    # missing or malformed, never mid-job.
    profile = load_candidate_profile()
    unresolved = find_sentinels(profile)
    if unresolved:
        for p in unresolved:
            print(f"[gate] NEEDS_REVIEW: {p}")
        raise SystemExit("refused: unresolved profile sentinels; "
                         "edit candidate_profile.json first.")

    try:
        from gemini_api import health_check
        hk = health_check(timeout=5)
        print(f"[health] gemini {hk.get('model')}: {'ok' if hk.get('ok') else 'FAIL'} {hk.get('error') or ''}")
        if not hk.get("ok"):
            err = (hk.get("error") or "").lower()
            if "unauth" in err or "api key" in err or "permission" in err or "401" in err or "403" in err:
                raise SystemExit(f"Gemini API key invalid: {hk.get('error')}")
            if "quota" in err or "429" in err or "resource_exhausted" in err:
                print("[health] quota exhausted before run — continuing but expect failures")
    except SystemExit:
        raise
    except Exception as e:
        print(f"[health] check warn: {e}")

    try:
        from gemini_api import openrouter_spend
        _sp0 = openrouter_spend()
        if _sp0 is not None:
            print(f"[spend] key at ${_sp0['usage']:.2f}/${_sp0['limit']:.2f} ({_sp0['pct']:.0%}) — log-only at gate, halt at 50% mid-run")
    except Exception as e:
        print(f"[spend] gate warn: {e}")

    try:
        # ponytail: URL-substring probe only; no DOM parsing until this misfires
        driver.get("https://www.naukri.com/mnjuser/profile")
        time.sleep(TIMING_CFG["nav_wait"])
        if "login" in (driver.current_url or "").lower():
            raise SystemExit(f"refused: naukri logged out in profile {PROFILE_PATH}. Open Firefox with that profile and log in first (or upload profile ZIP via /naukri), then rerun.")
        print("[gate] naukri login ok")
    except SystemExit:
        raise
    except Exception as e:
        print(f"[gate] login probe warn: {e}")

    counts = {"applied": 0, "review": 0, "skipped": 0, "failed": 0}
    global_processed = 0
    visited = load_visited()
    budget_exhausted = False
    overload_halt = None  # ponytail: persistent model overload stops the run; reports still written
    spend_halt = None  # ponytail: OpenRouter key at 50% stops the run; reports still written
    run = run_id()
    _RUN_ID = run
    capture_meta = {}
    visit_results = []
    manual_links = []
    processed_this_run = set()
    started = datetime.now().isoformat()
    budget_start = load_budget()
    try:
        for slug in SEARCH_SLUGS:
            if _stop_requested:
                print("[stop] stop requested — aborting run")
                break
            if budget_exhausted or (DRY_RUN and counts["applied"] >= 1):
                break
            print(f"\n=== JOB TYPE: {slug} ===")
            type_counts = {"applied": 0, "review": 0, "skipped": 0, "failed": 0}
            urls, meta = collect_job_urls_for(slug, visited)
            capture_meta[slug] = meta
            for i, url in enumerate(urls[:PER_TYPE_JOBS], start=1):
                if _stop_requested:
                    print("[stop] stop requested — stopping current type")
                    break
                if global_processed >= MAX_JOBS:
                    print(f"Reached global cap MAX_JOBS={MAX_JOBS}; stopping.")
                    break
                budget = load_budget()
                if not budget_ok(budget, DAILY_CALL_LIMIT) or (DRY_RUN and counts["applied"] >= 1):
                    # ponytail: sampling stop reuses budget break points; no new state
                    if DRY_RUN and counts["applied"] >= 1:
                        print("[dry] 1 applied — sampling stop.")
                    else:
                        budget_exhausted = True
                    break
                if global_processed > 0 and global_processed % 20 == 0:
                    # ponytail: ≤3 meter pings per run; halt only on confirmed numbers
                    try:
                        from gemini_api import openrouter_spend as _spend
                        _sp = _spend()
                        if _sp is not None and _sp["pct"] >= 0.5:
                            spend_halt = f"key at ${_sp['usage']:.2f}/${_sp['limit']:.2f}"
                            print(f"[halt] OpenRouter {spend_halt} — stopping run, reports will be written.")
                            break
                    except Exception as e:
                        print(f"[spend] checkpoint warn: {e}")
                try:
                    result = process_job(url, slug)
                except ModelOverloaded as e:
                    overload_halt = str(e)
                    print(f"[halt] {e} — stopping run, reports will be written.")
                    break
                mark_visited(visited, url, result.status, job_type=slug.replace("-jobs", ""))
                save_visited(visited)
                result.attempt_number = visited[url]["attempts"]
                processed_this_run.add(url)
                bucket = result.status if result.status in type_counts else "failed"
                type_counts[bucket] += 1
                counts[bucket] += 1
                global_processed += 1
                visit_results.append(result)
                print(f"[{slug}] [{i}/{min(len(urls), PER_TYPE_JOBS)}] {result.status}: {url}")
            for u in urls:
                if u not in processed_this_run:
                    manual_links.append({
                        "url": u,
                        "job_type": slug.replace("-jobs", ""),
                        "status": "unprocessed",
                        "reason": "not reached (budget/global cap or per-type limit)",
                    })
            if budget_exhausted:
                print("[budget] Gemini daily call limit reached — stopping run.")
            if overload_halt:
                print(f"[halt] model overloaded — run halted: {overload_halt}")
                break
            if spend_halt:
                print(f"[halt] spend cap — run halted: {spend_halt}")
                break
            print(f"--- type {slug} done: {type_counts} ---")
            if _stop_requested:
                break
        if _stop_requested:
            print(f"\nSTOPPED by user. {counts}")
        elif overload_halt:
            print(f"\nHALTED (model overloaded). {counts} reason={overload_halt}")
        elif spend_halt:
            print(f"\nHALTED (spend cap). {counts} reason={spend_halt}")
        else:
            print(f"\nDONE. {counts}")
        if REPORTS_CFG["capture_enabled"] and capture_meta:
            payload = {
                "run_id": run,
                "started_at": started,
                "config_snapshot": {
                    "max_pages_per_type": MAX_PAGES_PER_TYPE,
                    "per_type_jobs": PER_TYPE_JOBS,
                },
                "job_types": capture_meta,
                "totals": {
                    "links_captured_all_types": sum(
                        m["total_links_captured"] for m in capture_meta.values()),
                    "net_new_actionable_all_types": sum(
                        m["net_new_actionable_urls"] for m in capture_meta.values()),
                },
            }
            print(f"[report] capture written: {write_capture_report(REPORTS_CFG['dir'], run, payload)}")
        if REPORTS_CFG["visit_enabled"] and visit_results:
            budget_end = load_budget()
            from state import load_curation_budget
            curation_end = load_curation_budget()
            history_agreement = {"claimed_applied": 0, "confirmed": 0, "extras_on_history": 0}
            try:
                # ponytail: one history sweep upgrades false failures; counts below already reflect flips
                _flips, _pending, history_agreement = _apply_history_verdict(visit_results, max_pages=5)
            except Exception as e:
                print(f"[verify] history verdict warn: {e}")
            try:
                from gemini_api import openrouter_spend as _spend_end
                spend_end = _spend_end()
            except Exception:
                spend_end = None
            payload = {
                "run_id": run,
                "started_at": started,
                "finished_at": datetime.now().isoformat(),
                "budget_at_start": budget_start,
                "budget_at_end": budget_end,
                "curation_budget_at_end": curation_end,
                "spillover": spillover_block(visit_results),
                "openrouter_spend": spend_end,
                "halt_reason": spend_halt or overload_halt,
                "history_agreement": history_agreement,
                "results": visit_items(visit_results, started),
                "summary": build_visit_summary(visit_results),
            }
            print(f"[report] visit written: {write_visit_report(REPORTS_CFG['dir'], run, payload)}")
            forms = forms_items(visit_results, run)
            print(f"[report] forms written: {write_forms_report(REPORTS_CFG['dir'], run, {'run_id': run, 'count': len(forms), 'items': forms})}")
        if REPORTS_CFG["manual_enabled"]:
            seen_urls = set()
            manual_items = []
            for it in manual_links:
                if it["url"] not in seen_urls:
                    seen_urls.add(it["url"])
                    manual_items.append(it)
            for r in visit_results:
                if r.status in ("failed", "review") and r.url not in seen_urls:
                    seen_urls.add(r.url)
                    manual_items.append({
                        "url": r.url,
                        "job_type": r.job_type,
                        "status": r.status,
                        "reason": r.reason,
                        "path_taken": r.path_taken,
                        "error_type": r.error_type,
                    })
            if manual_items:
                print(f"[report] manual written: {write_manual_report(REPORTS_CFG['dir'], run, manual_items)}")
        if overload_halt:
            # ponytail: reports landed above; exit 3 = halted (distinct from crash 1)
            raise SystemExit(3)
        if spend_halt:
            # ponytail: reports landed above; exit 4 = spend cap (distinct from halt 3)
            raise SystemExit(4)
    except (KeyboardInterrupt, InvalidSessionIdException) as e:
        print(f"Browser session died/interrupted; stopping cleanly. {counts} ({e!r})")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
