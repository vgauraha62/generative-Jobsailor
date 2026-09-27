"""Timestamped JSON reports for capture and visit phases.

Owns its own output location: creates reports/<dir> on first write and
never relies on a caller to have made it. Pure aside from file I/O — no
Selenium/network dependency.

Report files are one-per-run and timestamped so history accumulates:
    reports/capture_<run_id>.json
    reports/visit_<run_id>.json
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime


@dataclass
class JobResult:
    status: str
    job_type: str = ""
    url: str = ""
    attempt_number: int = 0
    reason: str | None = None
    error_type: str | None = None
    traceback: str | None = None
    path_taken: str | None = None
    duration_seconds: float = 0.0
    gemini_calls_this_job: int = 0
    curation_score: float | None = None
    curation_performed: bool = False
    resume_path: str | None = None
    upload_status: str | None = None
    curation_calls_this_job: int = 0
    screenshot: str | None = None
    gemini_error: str | None = None
    verified: str | None = None


def _ensure_dir(directory: str):
    os.makedirs(directory, exist_ok=True)


def _write(path: str, payload: dict):
    _ensure_dir(os.path.dirname(path) or ".")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)


def run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def write_capture_report(directory: str, run_id_str: str, payload: dict) -> str:
    path = os.path.join(directory, f"capture_{run_id_str}.json")
    _write(path, payload)
    return path


def write_visit_report(directory: str, run_id_str: str, payload: dict) -> str:
    path = os.path.join(directory, f"visit_{run_id_str}.json")
    _write(path, payload)
    return path


def write_manual_report(directory: str, run_id_str: str, items: list) -> str:
    """Personal-review list of URLs the bot did not successfully apply to."""
    by_status = {}
    for it in items:
        by_status[it["status"]] = by_status.get(it["status"], 0) + 1
    payload = {
        "run_id": run_id_str,
        "generated_at": datetime.now().isoformat(),
        "count": len(items),
        "summary": by_status,
        "items": items,
    }
    path = os.path.join(directory, f"manual_{run_id_str}.json")
    _write(path, payload)
    return path


def write_forms_report(directory: str, run_id_str: str, payload: dict) -> str:
    path = os.path.join(directory, f"forms_{run_id_str}.json")
    _write(path, payload)
    return path


def forms_items(results, run_id_str=None) -> list:
    """Flat per-question rows (chat transcript + full-form plan) for forms_<run_id>.json."""
    # ponytail: projection of captured answers, no new capture; NEEDS_REVIEW never an answer
    items = []
    for r in results:
        base = {"run_id": run_id_str, "url": r.url, "job_type": r.job_type,
                "status": r.status, "path_taken": r.path_taken}
        for e in (getattr(r, "chat_transcript", None) or []):
            if e.get("type") == "submit" or (e.get("answer") or "").strip() in ("", "NEEDS_REVIEW"):
                continue
            items.append({**base, "q_idx": e.get("q_idx"), "type": e.get("type"),
                          "q": e.get("q"), "options": e.get("options"),
                          "answer": e.get("answer"), "provider": e.get("provider", "gemini"),
                          "profile_hash": e.get("profile_hash"),
                          "accepted": e.get("accepted"),
                          "timestamp": e.get("timestamp")})
        for i, p in enumerate(getattr(r, "form_plan", None) or [], start=1):
            if (p.get("answer") or "").strip() in ("", "NEEDS_REVIEW"):
                continue
            items.append({**base, "q_idx": i, "type": "form:" + str(p.get("type")),
                          "q": p.get("label"), "options": None,
                          "answer": p.get("answer"), "provider": p.get("provider", "gemini"),
                          "profile_hash": p.get("profile_hash"),
                          "timestamp": None})
    return items


def spillover_block(results) -> dict:
    """Switch report: did quota spill to OpenRouter mid-run, and when first."""
    # ponytail: derived from stamped rows; no new state
    n_or = 0
    first_at = None
    for r in results:
        for e in (getattr(r, "chat_transcript", None) or []):
            if e.get("provider") == "openrouter":
                n_or += 1
                if e.get("timestamp") and (first_at is None or e["timestamp"] < first_at):
                    first_at = e["timestamp"]
        for p in (getattr(r, "form_plan", None) or []):
            if not (p.get("answer") or "").strip() or (p.get("answer") or "").strip() == "NEEDS_REVIEW":
                continue
            if p.get("provider") == "openrouter":
                n_or += 1
    return {"happened": n_or > 0, "answers_via_openrouter": n_or, "first_spill_at": first_at}


def visit_items(results, started=None) -> list:
    """Per-result JSON rows for visit_<run_id>.json (transcript kept when present)."""
    return [
        {
            "url": r.url,
            "job_type": r.job_type,
            "status": r.status,
            "attempt_number": r.attempt_number,
            "path_taken": r.path_taken,
            "duration_seconds": r.duration_seconds,
            "gemini_calls_this_job": r.gemini_calls_this_job,
            "curation_calls_this_job": getattr(r, "curation_calls_this_job", 0),
            "curation_score": getattr(r, "curation_score", None),
            "curation_performed": getattr(r, "curation_performed", False),
            "resume_path": getattr(r, "resume_path", None),
            "upload_status": getattr(r, "upload_status", None),
            "screenshot": getattr(r, "screenshot", None),
            "gemini_error": getattr(r, "gemini_error", None),
            "reason": r.reason,
            "error_type": r.error_type,
            "traceback": r.traceback,
            "chat_transcript": getattr(r, "chat_transcript", None),
            "verified": getattr(r, "verified", None),
            "attempted_at": started,
        }
        for r in results
    ]


def build_visit_summary(results) -> dict:
    by_status = {"applied": 0, "review": 0, "skipped": 0, "failed": 0}
    by_job_type = {}
    error_counts = {}
    durations = []
    curation_scores = []
    by_upload = {}
    curation_performed = 0
    curated_applied = 0
    kept_applied = 0
    curated_total = 0
    kept_total = 0
    histogram = {"0.0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
    answers_gemini = 0
    answers_openrouter = 0
    answers_cache = 0
    applied_verification = {"direct": 0, "banner": 0, "revisit": 0, "history": 0, "unmarked": 0}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        by_job_type.setdefault(r.job_type, {})
        by_job_type[r.job_type][r.status] = by_job_type[r.job_type].get(r.status, 0) + 1
        if r.error_type:
            error_counts[r.error_type] = error_counts.get(r.error_type, 0) + 1
        if r.status == "applied":
            durations.append(r.duration_seconds)
            verification = getattr(r, "verified", None)
            applied_verification[verification if verification in applied_verification else "unmarked"] += 1
        cs = getattr(r, "curation_score", None)
        if cs is not None:
            curation_scores.append(float(cs))
            if cs < 0.2:
                histogram["0.0-0.2"] += 1
            elif cs < 0.4:
                histogram["0.2-0.4"] += 1
            elif cs < 0.6:
                histogram["0.4-0.6"] += 1
            elif cs < 0.8:
                histogram["0.6-0.8"] += 1
            else:
                histogram["0.8-1.0"] += 1
        if getattr(r, "curation_performed", False):
            curation_performed += 1
            curated_total += 1
            if r.status == "applied":
                curated_applied += 1
        else:
            if cs is not None:
                kept_total += 1
                if r.status == "applied":
                    kept_applied += 1
        us = getattr(r, "upload_status", None) or "none"
        by_upload[us] = by_upload.get(us, 0) + 1
        for e in (getattr(r, "chat_transcript", None) or []):
            if e.get("type") == "submit" or e.get("accepted") is False or not (e.get("answer") or "").strip() or (e.get("answer") or "").strip() == "NEEDS_REVIEW":
                continue
            if e.get("provider") == "openrouter":
                answers_openrouter += 1
            elif e.get("provider") == "cache":
                answers_cache += 1
            else:
                answers_gemini += 1
        for p in (getattr(r, "form_plan", None) or []):
            if not (p.get("answer") or "").strip() or (p.get("answer") or "").strip() == "NEEDS_REVIEW":
                continue  # ponytail: verdicts/empties are never answers — same guard as chat loop
            if p.get("provider") == "openrouter":
                answers_openrouter += 1
            elif p.get("provider") == "cache":
                answers_cache += 1
            else:
                answers_gemini += 1
    curated_rate = (curated_applied / curated_total) if curated_total else 0.0
    kept_rate = (kept_applied / kept_total) if kept_total else 0.0
    return {
        "by_status": by_status,
        "by_job_type": by_job_type,
        "gemini_calls_total": sum(r.gemini_calls_this_job for r in results),
        "answers_gemini": answers_gemini,
        "answers_openrouter": answers_openrouter,
        "answers_cache": answers_cache,
        "applied_verification": applied_verification,
        "curation_calls_total": sum(getattr(r, "curation_calls_this_job", 0) for r in results),
        "curation_performed": curation_performed,
        "curation_skipped_high_score": kept_total,
        "avg_curation_score": (sum(curation_scores) / len(curation_scores)) if curation_scores else 0.0,
        "curation_score_histogram": histogram,
        "by_upload_status": by_upload,
        "applied_rate_curated": round(curated_rate, 3),
        "applied_rate_kept": round(kept_rate, 3),
        "applied_rate_delta_curated_vs_kept": round(curated_rate - kept_rate, 3),
        "avg_duration_seconds_applied": (sum(durations) / len(durations)) if durations else 0.0,
        "top_error_types": dict(sorted(error_counts.items(), key=lambda kv: kv[1], reverse=True)),
    }
