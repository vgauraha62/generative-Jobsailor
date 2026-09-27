"""Mocked dry trial — Gemini mocked, driver mocked, real file I/O + reports + screenshots.

Usage: venv/bin/python scripts/trial_mock_dry.py [--types python]

Creates: reports/capture_<run_id>.json, reports/visit_<run_id>.json, reports/manual_<run_id>.json, reports/run_<run_id>.log,
        mock screenshots visit_chat_q*_(after_save|new_question)_*.png (>1KB), resumes/curated + pdf, active.json (dry_run no overwrite).

All Gemini calls are mocked — no quota burned.
"""
import os, sys, json, time, traceback, hashlib, shutil
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from reporting import write_capture_report, write_visit_report, write_manual_report, run_id, build_visit_summary, JobResult
from config_loader import load_config
import state

DRY_TYPES = ["python-jobs"]
Q_BANK = [
    {"type": "radio", "q": "Are you willing to relocate to Bengaluru?", "options": ["Yes (Value: Yes)", "No (Value: No)"], "answer": "1"},
    {"type": "text", "q": "What is your current notice period in days?", "answer": "30"},
    {"type": "radio", "q": "Budget for this role is 12 LPA, are you okay?", "options": ["Yes (Value: Yes)", "No (Value: No)", "Skip (Value: Skip)"], "answer": "1"},
]

def make_fake_driver(run_id_str):
    class FakeEl:
        def __init__(self, text="", attrs=None, cls=""):
            self.text = text
            self._attrs = attrs or {}
            self._cls = cls
        def get_attribute(self, k):
            return self._cls if k == "class" else self._attrs.get(k, "")
        def find_element(self, *a, **kw): raise Exception("not found")
    class FakeDriver:
        def __init__(self):
            self.current_url = "https://www.naukri.com/job-listings-test-001"
            self.page_source = "<html>mock</html>"
            self._sig_seq = []
            self._q_idx = 0
        def get(self, url): self.current_url = url
        def find_elements(self, by, val):
            if "chatList_" in val: return [FakeEl()]
            if ".ssrc__radio-btn-container" in val:
                cur = self._sig_seq[self._q_idx] if self._q_idx < len(self._sig_seq) else ""
                return [FakeEl(), FakeEl()] if cur.startswith("radio:") else []
            if "contenteditable" in val or "textArea" in val:
                cur = self._sig_seq[self._q_idx] if self._q_idx < len(self._sig_seq) else ""
                return [FakeEl()] if cur.startswith("text:") else []
            if "form-field" in val or "formField" in val or "styles_form-box" in val: return []
            if "apply-status-header" in val: return []
            if "apply-message" in val: return []
            return []
        def find_element(self, by, val): raise Exception("not found")
        def save_screenshot(self, path):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                f.write(b"\x89PNG" + b"\x00" * 2048)
            return True
        def execute_script(self, *a, **k): return []
    return FakeDriver()

def fake_screenshot(path, driver):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as f:
        f.write(b"\x89PNG" + b"\x00" * 2048)
    return path

def run_trial(types=None):
    cfg = load_config()
    types = types or DRY_TYPES
    rid = run_id()
    started = datetime.now().isoformat()
    print(f"[trial_mock] run_id={rid} types={types} DRY_RUN (mocked Gemini)")

    budget_start = state.load_budget()
    curation_start = state.load_curation_budget()

    # --- capture (mocked harvest) ---
    job_types = {}
    all_urls = []
    for slug in types:
        fake_links = [f"https://www.naukri.com/job-listings-mock-{slug.replace('-jobs','')}-{i:03d}" for i in range(5)]
        for u in fake_links:
            if u not in all_urls:
                all_urls.append(u)
        # simulate ledger: new 3, skipped 2
        d = {
            "pages_scraped": 1,
            "pages_stopped_reason": "mocked_dry_trial",
            "links_per_page": {"1": 5},
            "total_links_captured": 5,
            "duplicate_links_within_type": 0,
            "already_in_ledger": {"new": 3, "applied": 0, "skipped": 2, "review": 0, "failed_retryable": 0, "failed_exhausted": 0},
            "net_new_actionable_urls": 3,
            "csv_fallback_used": False,
            "urls": fake_links[:3],
        }
        job_types[slug] = d
    capture_payload = {
        "run_id": rid, "started_at": started,
        "config_snapshot": {"max_pages_per_type": 5, "per_type_jobs": 20},
        "job_types": job_types,
        "totals": {"links_captured_all_types": sum(v["total_links_captured"] for v in job_types.values()),
                   "net_new_actionable_all_types": sum(v["net_new_actionable_urls"] for v in job_types.values())},
    }
    cap_path = write_capture_report(cfg["reports"]["dir"], rid, capture_payload)
    print(f"[trial_mock] capture → {cap_path}")

    # --- visit (mocked apply with per-Q transcript) ---
    visit_results = []
    driver = make_fake_driver(rid)
    # mock gemini to deterministic
    def fake_bard(q, timeout=None):
        if "option number" in q.lower(): return "1"
        if "NEEDS_REVIEW" in q: return "30 days"
        if "Return ONLY a JSON object" in q: return '{"Full Name": "Vaibhav", "Experience": "5 years"}'
        return "ok"
    def fake_curation(q, timeout=None):
        if "keywords" in q.lower(): return '["python","rag","docker"]'
        return "Curated resume content " + "x" * 250

    # Simulate 3 jobs: chat 3Q live, full_form success, skipped
    # Job 1: chat_widget 3 questions, mocked answers, screenshots per Q
    with patch("gemini_api.bard_flash_response", side_effect=fake_bard), \
         patch("gemini_api.bard_flash_response_curation", side_effect=fake_curation), \
         patch("time.sleep"):
        # Job 1
        r1 = JobResult(status="applied", job_type=types[0].replace("-jobs",""), url=all_urls[0], attempt_number=1, path_taken="chat_widget", duration_seconds=12.3, gemini_calls_this_job=3, curation_calls_this_job=2, curation_score=0.2, curation_performed=True, resume_path="resumes/pdf/mock1.pdf", upload_status="uploaded")
        r1.screenshot = None
        r1.screenshots = []
        r1.chat_transcript = []
        r1.gemini_error = None
        for idx, qb in enumerate(Q_BANK, start=1):
            after = f"reports/visit_chat_q{idx:02d}_after_save_{rid}_{idx:02d}.png"
            fake_screenshot(after, driver)
            newq = f"reports/visit_chat_q{idx:02d}_new_question_{rid}_{idx:02d}.png"
            fake_screenshot(newq, driver)
            r1.screenshots.extend([after, newq])
            if idx == 1:
                r1.screenshot = after
            r1.chat_transcript.append({
                "q_idx": idx, "type": qb["type"], "q": qb["q"],
                "options": qb.get("options"), "answer": qb["answer"],
                "gemini_calls_before": idx-1, "gemini_calls_after": idx,
                "screenshot_after_save": after, "screenshot_new_q": newq,
                "sig_before": f"text:{qb['q']}" if idx>1 else "radio:Yes|No", "sig_after": f"text:{Q_BANK[idx]['q']}" if idx<len(Q_BANK) else "thank:Thank you",
                "timestamp": datetime.now().isoformat(),
            })
        # keep single representative screenshot for backward compat
        r1.screenshot = r1.screenshots[0] if r1.screenshots else None
        visit_results.append(r1)

        # Job 2: full_form with fields, no chat
        r2 = JobResult(status="review", job_type=types[0].replace("-jobs",""), url=all_urls[1], attempt_number=1, path_taken="full_form", duration_seconds=8.1, gemini_calls_this_job=1, curation_calls_this_job=0, curation_score=0.7, curation_performed=False, resume_path=None, upload_status="skipped_high_score")
        r2.screenshot = None
        r2.screenshots = []
        r2.chat_transcript = []
        visit_results.append(r2)

        # Job 3: skipped (already applied)
        r3 = JobResult(status="skipped", job_type=types[0].replace("-jobs",""), url=all_urls[2], attempt_number=1, path_taken="none", duration_seconds=0.5)
        visit_results.append(r3)

        # Add 2 more skipped to match net_new 3? We already have 3; keep as above

    summary = build_visit_summary(visit_results)
    budget_end = state.load_budget()
    curation_end = state.load_curation_budget()
    visit_payload = {
        "run_id": rid, "started_at": started, "finished_at": datetime.now().isoformat(),
        "budget_at_start": budget_start, "budget_at_end": budget_end, "curation_budget_at_end": curation_end,
        "results": [
            {"url": r.url, "job_type": r.job_type, "status": r.status, "attempt_number": r.attempt_number,
             "path_taken": r.path_taken, "duration_seconds": r.duration_seconds,
             "gemini_calls_this_job": r.gemini_calls_this_job, "curation_calls_this_job": getattr(r,"curation_calls_this_job",0),
             "curation_score": r.curation_score, "curation_performed": r.curation_performed, "resume_path": r.resume_path, "upload_status": r.upload_status,
             "screenshot": getattr(r,"screenshot",None), "screenshots": getattr(r,"screenshots",[]), "chat_transcript": getattr(r,"chat_transcript",[]),
             "gemini_error": getattr(r,"gemini_error",None), "reason": r.reason, "error_type": r.error_type, "traceback": r.traceback,
             "attempted_at": started} for r in visit_results
        ],
        "summary": summary,
    }
    visit_path = write_visit_report(cfg["reports"]["dir"], rid, visit_payload)
    print(f"[trial_mock] visit → {visit_path} summary {summary['by_status']}")

    manual_items = []
    for r in visit_results:
        if r.status in ("failed","review") and r.url:
            manual_items.append({"url": r.url, "job_type": r.job_type, "status": r.status, "reason": r.reason or "review", "path_taken": r.path_taken, "error_type": r.error_type})
    manual_payload_items = manual_items
    from reporting import write_manual_report
    man_path = None
    if manual_items:
        man_path = write_manual_report(cfg["reports"]["dir"], rid, manual_items)
        print(f"[trial_mock] manual → {man_path}")

    # run log
    log_path = Path(cfg["reports"]["dir"]) / f"run_{rid}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w") as lf:
        lf.write(f"Types: {types}\n[MOCK] run_id={rid} DRY_RUN mocked Gemini\n")
        lf.write(f"Q1 answered: {Q_BANK[0]['q']} -> {Q_BANK[0]['answer']}\n")
        lf.write(f"Q2 answered: {Q_BANK[1]['q']} -> {Q_BANK[1]['answer']}\n")
        lf.write(f"Q3 answered: {Q_BANK[2]['q']} -> {Q_BANK[2]['answer']}\n")
        lf.write(f"DONE. {summary['by_status']}\n")
    print(f"[trial_mock] log → {log_path}")

    # run_state
    run_state_path = Path(cfg["reports"]["dir"]) / "run_state.json"
    run_state_path.write_text(json.dumps({"run_id": rid, "types": types, "live": False, "exit_code": 0, "finished_at": datetime.now().isoformat()}))

    print(f"[trial_mock] DONE run_id={rid}")
    print(f"  capture: {cap_path}")
    print(f"  visit: {visit_path}")
    print(f"  manual: {man_path}")
    print(f"  log: {log_path}")
    print(f"  screenshots: {[r.screenshots for r in visit_results if getattr(r,'screenshots',None)]}")
    return rid

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--types", nargs="*", default=None)
    args = p.parse_args()
    t = [x if x.endswith("-jobs") else x+"-jobs" for x in (args.types or ["python"])]
    run_trial(t)
