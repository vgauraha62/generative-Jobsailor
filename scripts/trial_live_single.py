"""Live single-URL trial with real Gemini + real driver, per-Q screenshots.

Usage: venv/bin/python scripts/trial_live_single.py [--url <naukri_url>]

If no URL, uses a known chat job from last capture.

Creates: reports/trial_live_<run_id>.json + .md + visit_chat_q PNGs under reports/
"""
import os, sys, json, time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from reporting import write_visit_report, write_capture_report, run_id, build_visit_summary
from config_loader import load_config
import state

def pick_url():
    cfg = load_config()
    d = Path(cfg["reports"]["dir"])
    caps = sorted(d.glob("capture_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if caps:
        data = json.loads(caps[0].read_text())
        for slug, info in data.get("job_types", {}).items():
            urls = info.get("urls") or []
            if urls:
                return urls[0], slug
    return "https://www.naukri.com/job-listings-ai-ml-engineer-pinakee-digital-technology-bengaluru-2-to-5-years-060726502342", "python-jobs"

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=None)
    args = p.parse_args()
    cfg = load_config()
    # ensure live env
    url, slug = (args.url, "python-jobs") if args.url else pick_url()
    print(f"[trial_live] url={url} slug={slug}")
    # health check
    try:
        import gemini_api
        hk = gemini_api.health_check(timeout=5)
        print(f"[health] {hk}")
        if not hk.get("ok") and ("unauth" in (hk.get("error") or "").lower() or "api key" in (hk.get("error") or "").lower()):
            print(f"[trial_live] abort: {hk.get('error')}")
            sys.exit(2)
        if "quota" in (hk.get("error") or "").lower():
            print("[trial_live] quota exhausted warning — proceeding, expect failures")
    except Exception as e:
        print(f"[trial_live] health warn: {e}")

    # Force live for this script: patch DRY_RUN False via CLI style
    import apply_jobs
    apply_jobs.DRY_RUN = False
    print("[trial_live] DRY_RUN forced False — live submit ACTIVE")
    # ensure budgets have headroom warning
    b = state.load_budget()
    print(f"[budget] {b} limit {apply_jobs.DAILY_CALL_LIMIT}")
    cb = state.load_curation_budget()
    print(f"[curation] {cb}")

    # Run single job via process_job (handles driver, counters, visited)
    from apply_jobs import process_job
    started = datetime.now().isoformat()
    rid = run_id()
    # ensure log dir
    log_path = Path(cfg["reports"]["dir"]) / f"run_{rid}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    import io, contextlib
    # capture stdout to log
    import sys as _sys
    orig_stdout = _sys.stdout
    logf = open(log_path, "w")
    try:
        _sys.stdout = logf
        print(f"[trial_live] run_id={rid} starting {url}")
        res = process_job(url, slug)
        print(f"[trial_live] result {res.status} {res.path_taken} {res.reason}")
        # also log transcript
        if getattr(res, "chat_transcript", None):
            for e in res.chat_transcript:
                print(f"[trial_live] Q{e['q_idx']} {e['type']} {e['q']!r} -> {e['answer']!r} screenshots {e.get('screenshot_after_save')} {e.get('screenshot_new_q')}")
        _sys.stdout = orig_stdout
    finally:
        _sys.stdout = orig_stdout
        try: logf.close()
        except: pass

    visit_results = [res]
    summary = build_visit_summary(visit_results)
    # write visit + manual
    from state import load_budget, load_curation_budget
    budget_end = load_budget()
    curation_end = load_curation_budget()
    payload = {
        "run_id": rid, "started_at": started, "finished_at": datetime.now().isoformat(),
        "budget_at_start": b, "budget_at_end": budget_end, "curation_budget_at_end": curation_end,
        "results": [{
            "url": r.url, "job_type": r.job_type, "status": r.status, "attempt_number": r.attempt_number,
            "path_taken": r.path_taken, "duration_seconds": r.duration_seconds,
            "gemini_calls_this_job": r.gemini_calls_this_job, "curation_calls_this_job": getattr(r, "curation_calls_this_job", 0),
            "curation_score": r.curation_score, "curation_performed": r.curation_performed, "resume_path": r.resume_path, "upload_status": r.upload_status,
            "screenshot": getattr(r, "screenshot", None), "screenshots": getattr(r, "screenshots", []), "chat_transcript": getattr(r, "chat_transcript", []),
            "gemini_error": getattr(r, "gemini_error", None), "reason": r.reason, "error_type": r.error_type, "traceback": r.traceback,
            "attempted_at": started} for r in visit_results],
        "summary": summary,
    }
    visit_path = write_visit_report(cfg["reports"]["dir"], rid, payload)
    # capture mock single
    cap_payload = {"run_id": rid, "started_at": started, "config_snapshot": {"live_trial": True, "url": url}, "job_types": {slug: {"pages_scraped": 1, "urls": [url], "net_new_actionable_urls": 1}}, "totals": {"links_captured_all_types": 1, "net_new_actionable_all_types": 1}}
    cap_path = write_capture_report(cfg["reports"]["dir"], rid, cap_payload)
    manual_path = None
    if res.status in ("failed","review"):
        from reporting import write_manual_report
        manual_path = write_manual_report(cfg["reports"]["dir"], rid, [{"url": url, "job_type": slug.replace("-jobs",""), "status": res.status, "reason": res.reason, "path_taken": res.path_taken}])

    # validate summary
    print(f"[trial_live] wrote {visit_path} status={res.status} path={res.path_taken}")
    # save trial summary
    trial_path = Path(cfg["reports"]["dir"]) / f"trial_live_{rid}.json"
    trial_path.write_text(json.dumps({"run_id": rid, "url": url, "result": {"status": res.status, "path": res.path_taken, "reason": res.reason, "upload": res.upload_status, "chat_transcript": getattr(res, "chat_transcript", []), "screenshots": getattr(res, "screenshots", [])}, "budget": budget_end, "curation": curation_end}, indent=2))
    md_path = Path(cfg["reports"]["dir"]) / f"trial_live_{rid}.md"
    md = [f"# Live Trial Single {rid}", f"- url: {url}", f"- status: {res.status} path: {res.path_taken} reason: {res.reason}", f"- upload: {res.upload_status} curation: {res.curation_score} {res.curation_performed}", f"- gemini_calls: {res.gemini_calls_this_job}"]
    if getattr(res, "chat_transcript", None):
        md.append("")
        md.append("## Chat Q1..Qn")
        for e in res.chat_transcript:
            md.append(f"- Q{e['q_idx']} {e['type']} `{e['q']}` → `{e['answer']}` after_save: `{e.get('screenshot_after_save')}` new_q: `{e.get('screenshot_new_q')}`")
    md.append("")
    md.append(f"## Artifacts\n- visit: `{visit_path}`\n- capture: `{cap_path}`\n- log: `{log_path}`\n- per-Q PNGs: `{getattr(res,'screenshots',[])}`")
    # invariant check
    inv_ok = not (res.path_taken == "full_form" and res.reason == "no form fields found" and getattr(res, "chat_transcript", []))
    md.append(f"\n## Invariant `form_field → not no form fields` : {'PASS' if inv_ok else 'FAIL'}")
    md_path.write_text("\n".join(md))
    print(f"[trial_live] wrote {trial_path} and {md_path} invariant {inv_ok}")
    # show run_state
    run_state = Path(cfg["reports"]["dir"]) / "run_state.json"
    if run_state.exists():
        print(run_state.read_text())
    sys.exit(0 if inv_ok else 1)

if __name__ == "__main__":
    main()
