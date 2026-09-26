import json
import os
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

VISITED_PATH = "visited.json"
BUDGET_PATH = "gemini_budget.json"
CURATION_BUDGET_PATH = "resume_curation_budget.json"
RAG_BUDGET_PATH = "rag_budget.json"


def _resolve_tz(tz_name=None):
    if tz_name and ZoneInfo:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    return None

def _now_in_tz(tz_name=None):
    z = _resolve_tz(tz_name)
    if z:
        return datetime.now(z)
    return datetime.now()

def _budget_day(tz_name=None):
    return _now_in_tz(tz_name).date().isoformat()

def _budget_reset_info(tz_name=None):
    now = _now_in_tz(tz_name)
    tz_str = tz_name or "local"
    try:
        reset_at = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        next_reset = (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat()
    except Exception:
        reset_at = now.isoformat()
        next_reset = (now + timedelta(days=1)).isoformat()
    return reset_at, next_reset, tz_str

def _new_budget(tz_name=None):
    day = _budget_day(tz_name)
    reset_at, next_reset, tz_str = _budget_reset_info(tz_name)
    return {"day": day, "calls_used": 0, "timezone": tz_str, "reset_at": reset_at, "next_reset_at": next_reset}

def _ensure_budget_fields(b, tz_name=None):
    if "timezone" not in b:
        b["timezone"] = tz_name or b.get("timezone") or "local"
    if "reset_at" not in b:
        b["reset_at"], b["next_reset_at"], _ = _budget_reset_info(tz_name or b.get("timezone"))
        if b["reset_at"] is None:
            b["reset_at"] = datetime.now().isoformat()
        if b["next_reset_at"] is None:
            b["next_reset_at"] = (datetime.now() + timedelta(days=1)).isoformat()
    return b

def load_visited() -> dict:
    if not os.path.exists(VISITED_PATH):
        return {}
    with open(VISITED_PATH) as f:
        return json.load(f)


def save_visited(data: dict):
    tmp = VISITED_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, VISITED_PATH)


def should_skip(url: str, visited: dict, live: bool, max_retries: int) -> bool:
    rec = visited.get(url)
    if not rec:
        return False
    if rec["status"] in ("applied", "skipped"):
        return True
    if rec["status"] == "review" and not live:
        return True
    if rec["status"] == "failed" and rec["attempts"] >= max_retries:
        return True
    return False


def bucket_against_ledger(url: str, visited: dict, live: bool, max_retries: int) -> str:
    rec = visited.get(url)
    if not rec:
        return "new"
    if rec["status"] == "applied":
        return "applied"
    if rec["status"] == "skipped":
        return "skipped"
    if rec["status"] == "review":
        return "review" if not live else "new"
    if rec["status"] == "failed":
        return "failed_exhausted" if rec["attempts"] >= max_retries else "failed_retryable"
    return "new"


def mark_visited(visited: dict, url: str, status: str, job_type: str):
    rec = visited.get(url, {"attempts": 0})
    rec["status"] = status
    rec["attempts"] = rec.get("attempts", 0) + 1
    rec["last_seen"] = datetime.now().isoformat()
    rec["job_type"] = job_type
    visited[url] = rec


def load_budget(tz_name=None) -> dict:
    today = _budget_day(tz_name)
    if os.path.exists(BUDGET_PATH):
        try:
            with open(BUDGET_PATH) as f:
                b = json.load(f)
            if b.get("day") == today:
                return _ensure_budget_fields(b, tz_name)
        except Exception:
            pass
    b = _new_budget(tz_name)
    try:
        save_budget(b)
    except Exception:
        pass
    return b


def save_budget(b: dict):
    tmp = BUDGET_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(b, f)
    os.replace(tmp, BUDGET_PATH)


def budget_ok(b: dict, limit: int) -> bool:
    return b["calls_used"] < limit


def record_gemini_call(b: dict):
    b["calls_used"] += 1
    b["last_call_at"] = datetime.now().isoformat()
    save_budget(b)


def load_curation_budget(tz_name=None) -> dict:
    today = _budget_day(tz_name)
    if os.path.exists(CURATION_BUDGET_PATH):
        try:
            with open(CURATION_BUDGET_PATH) as f:
                b = json.load(f)
            if b.get("day") == today:
                return _ensure_budget_fields(b, tz_name)
        except Exception:
            pass
    b = _new_budget(tz_name)
    try:
        save_curation_budget(b)
    except Exception:
        pass
    return b


def save_curation_budget(b: dict):
    tmp = CURATION_BUDGET_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(b, f)
    os.replace(tmp, CURATION_BUDGET_PATH)


def curation_budget_ok(b: dict, limit: int) -> bool:
    return b["calls_used"] < limit


def record_curation_call(b: dict):
    b["calls_used"] += 1
    b["last_call_at"] = datetime.now().isoformat()
    save_curation_budget(b)


def load_rag_budget(tz_name=None) -> dict:
    today = _budget_day(tz_name)
    if os.path.exists(RAG_BUDGET_PATH):
        try:
            with open(RAG_BUDGET_PATH) as f:
                b = json.load(f)
            if b.get("day") == today:
                return _ensure_budget_fields(b, tz_name)
        except Exception:
            pass
    b = _new_budget(tz_name)
    try:
        save_rag_budget(b)
    except Exception:
        pass
    return b


def save_rag_budget(b: dict):
    tmp = RAG_BUDGET_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(b, f)
    os.replace(tmp, RAG_BUDGET_PATH)


def rag_budget_ok(b: dict, limit: int) -> bool:
    return b["calls_used"] < limit


def record_rag_call(b: dict):
    b["calls_used"] += 1
    b["last_call_at"] = datetime.now().isoformat()
    save_rag_budget(b)
