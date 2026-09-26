"""Read-only endpoints for the JobSailor control panel.

Everything here reads existing state - visited.json, gemini_budget.json,
config.json, candidate_profile.json, and reports/*.json - and writes
nothing. That's deliberate: this router is included in server.py with the
auth dependency applied once at the router level, so nothing here can ever
ship unprotected, but nothing here can mutate state either. Mutating
endpoints (config-as-form save, profile editor, run trigger) are a
separate router added in a later step, reviewed with more scrutiny.
"""
import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

import state
import config_loader
import candidate_profile

router = APIRouter(prefix="/api")

# NOTE: adjust this if your config_loader.py's public entry point isn't
# named load_config() - e.g. it might be get_config() or CONFIG (a
# module-level constant rather than a function). Everything else in this
# file is independent of that one name.
_config = config_loader.load_config()
REPORTS_DIR = Path(_config["reports"]["dir"])

# run_id comes from the URL - constrain it before it ever touches a
# filesystem path, so a crafted run_id can't walk out of reports/.
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _user_ctx(request):
    try:
        from fastapi import Request as _Req
        uid = request.session.get("user_id") if hasattr(request, "session") else None
        is_admin = False
        if uid:
            try:
                from web.db import get_user_by_id
                u = get_user_by_id(uid)
                if u and u.get("is_admin"):
                    is_admin = True
                if u and u.get("email","").lower() == "vaibhavgauraha62@gmail.com":
                    is_admin = True
            except: pass
        return uid, is_admin
    except: return None, False

def _load_per_user_visited(uid):
    if uid:
        try:
            from web.per_user import get_user_visited_path
            p = get_user_visited_path(uid)
            if p.exists():
                with open(p) as f: return json.load(f)
            else:
                return {}
        except: pass
    return state.load_visited()

def _get_user_tz(uid):
    if not uid:
        return None
    try:
        from web.db import get_user_by_id
        u = get_user_by_id(uid)
        if u and u.get("timezone"):
            return u["timezone"]
    except: pass
    return "Asia/Kolkata"

def _load_per_user_budget(uid, kind="gemini"):
    tz = _get_user_tz(uid)
    if uid:
        try:
            from web.per_user import load_user_budget
            return load_user_budget(uid, kind, tz)
        except: pass
    if kind == "curation":
        return state.load_curation_budget(tz)
    if kind == "rag":
        return state.load_rag_budget(tz)
    return state.load_budget(tz)

def _openrouter_spend_status():
    # ponytail: live meter per status call; None keeps shape when unconfigured/down
    try:
        from gemini_api import openrouter_spend
        return openrouter_spend()
    except Exception:
        return None

def _load_per_user_profile(uid):
    if uid:
        try:
            from web.per_user import get_user_profile_path
            p = get_user_profile_path(uid)
            if p.exists():
                with open(p) as f: return json.load(f)
            else:
                return {"resume_facts": {"name": "NEEDS_REVIEW", "email": "NEEDS_REVIEW", "phone": "NEEDS_REVIEW", "highest_qualification": "NEEDS_REVIEW", "institution": "NEEDS_REVIEW", "total_experience_years": "NEEDS_REVIEW", "relevant_experience_years": "NEEDS_REVIEW", "current_location": "NEEDS_REVIEW", "skills": "NEEDS_REVIEW"}, "user_preferences": {"current_ctc_lpa": "NEEDS_REVIEW", "expected_ctc_lpa": "NEEDS_REVIEW", "notice_period_days": "NEEDS_REVIEW", "willing_to_relocate": "NEEDS_REVIEW", "work_authorization": "NEEDS_REVIEW", "passport_valid": "NEEDS_REVIEW"}}
        except: pass
    return {"resume_facts": {"name": "NEEDS_REVIEW", "email": "NEEDS_REVIEW", "phone": "NEEDS_REVIEW", "highest_qualification": "NEEDS_REVIEW", "institution": "NEEDS_REVIEW", "total_experience_years": "NEEDS_REVIEW", "relevant_experience_years": "NEEDS_REVIEW", "current_location": "NEEDS_REVIEW", "skills": "NEEDS_REVIEW"}, "user_preferences": {"current_ctc_lpa": "NEEDS_REVIEW", "expected_ctc_lpa": "NEEDS_REVIEW", "notice_period_days": "NEEDS_REVIEW", "willing_to_relocate": "NEEDS_REVIEW", "work_authorization": "NEEDS_REVIEW", "passport_valid": "NEEDS_REVIEW"}}

def _reports_dirs_for_user(uid, is_admin, cfg):
    base = Path(cfg.get("reports", {}).get("dir", "reports"))
    if is_admin:
        try:
            from web.db import get_all_users
            dirs = [base]
            for u in get_all_users():
                d = base / str(u["id"])
                if d.exists(): dirs.append(d)
            for p in Path("data/users").glob("*/reports"):
                if p not in dirs: dirs.append(p)
            return dirs
        except: return [base]
    if uid:
        try:
            from web.per_user import get_user_reports_dir
            # for new regular user, do NOT leak global base — only own shard
            return [get_user_reports_dir(uid)]
        except: return [base]
    return [base]

@router.get("/status")
async def get_status(request: Request = None):
    """Budget, ledger breakdown, and outstanding profile sentinels - the
    single call the dashboard's top summary panel needs."""
    from fastapi import Request as _R
    uid, is_admin = _user_ctx(request)
    # per-user or admin aggregate
    if is_admin:
        visited = {}
        try:
            from web.db import get_all_users
            for u in get_all_users():
                vd = _load_per_user_visited(u["id"])
                visited.update({f"{u['id']}:{k}":v for k,v in vd.items()})
        except: visited = {}
        # do not include global to avoid double after shard migration
    else:
        visited = _load_per_user_visited(uid)
    by_status: dict[str, int] = {}
    for rec in visited.values():
        by_status[rec["status"]] = by_status.get(rec["status"], 0) + 1

    if is_admin:
        # aggregate budgets? show own + sum? show max
        budget = state.load_budget()
        curation_budget = state.load_curation_budget()
        # for admin display per-user budgets in table separately
    else:
        budget = _load_per_user_budget(uid, "gemini")
        curation_budget = _load_per_user_budget(uid, "curation")
    cfg = config_loader.load_config()

    profile = _load_per_user_profile(uid) if not is_admin else candidate_profile.load_candidate_profile()
    sentinels = candidate_profile.find_sentinels(profile)

    active = None
    active_path = cfg.get("resume_curation", {}).get("active_resume", "resumes/active.json")
    try:
        if Path(active_path).exists():
            with open(active_path) as f:
                active = json.load(f)
    except Exception:
        active = None

    # per-user reports dirs
    reports_dirs = _reports_dirs_for_user(uid, is_admin, cfg)
    primary_reports_dir = reports_dirs[0] if reports_dirs else Path(cfg.get("reports", {}).get("dir", "reports"))

    rolling = []
    daily_changed = 0
    daily_uploaded = 0
    daily_total = 0
    try:
        all_visit = []
        seen_run = set()
        for d in reports_dirs:
            for p in sorted(d.glob("visit_*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                rid = p.stem.replace("visit_","")
                if rid not in seen_run:
                    seen_run.add(rid)
                    all_visit.append(p)
        all_visit = sorted(all_visit, key=lambda p: p.stat().st_mtime, reverse=True)
        today = budget.get("day") or curation_budget.get("day")
        for vf in all_visit:
            try:
                with open(vf) as fh:
                    data = json.load(fh)
                report_day = None
                if isinstance(data.get("budget_at_end"), dict):
                    report_day = data["budget_at_end"].get("day")
                if not report_day and isinstance(data.get("curation_budget_at_end"), dict):
                    report_day = data["curation_budget_at_end"].get("day")
                if not report_day:
                    started = data.get("started_at") or ""
                    if len(started) >= 10:
                        report_day = started[:10]
                if not report_day:
                    run_id_val = data.get("run_id") or vf.stem.replace("visit_", "")
                    if len(run_id_val) >= 8 and run_id_val[:8].isdigit():
                        report_day = f"{run_id_val[:4]}-{run_id_val[4:6]}-{run_id_val[6:8]}"
                if today and report_day != today:
                    continue
                summary = data.get("summary", {})
                daily_changed += int(summary.get("curation_performed") or 0)
                by_up = summary.get("by_upload_status") or {}
                daily_uploaded += int(by_up.get("uploaded") or 0)
                daily_total += 1
            except Exception:
                continue
        rolling_files = all_visit[:5]
        for vf in rolling_files:
            with open(vf) as fh:
                data = json.load(fh)
            summary = data.get("summary", {})
            rolling.append({"run_id": data.get("run_id"), "by_status": summary.get("by_status", {}), "summary": summary})
    except Exception:
        rolling = []

    # per-user active_resume
    if not is_admin and uid:
        try:
            from web.per_user import get_user_shard
            shard = get_user_shard(uid)
            cand = shard / "candidate_profile.json"
            # prefer per-user profile for active check
            if cand.exists():
                # read per-user active resume
                per_active = shard / "resumes" / "active.json"
                if per_active.exists():
                    with open(per_active) as f: active = json.load(f)
        except: pass

    upload_screenshots = []
    try:
        pngs = []
        for d in reports_dirs:
            pngs.extend([p for p in d.glob("*.png") if p.name.startswith("upload_") or p.name.startswith("visit_")])
        pngs = [p for p in pngs if p.stat().st_size > 1024]
        for p in sorted(pngs, key=lambda x: x.stat().st_mtime, reverse=True)[:10]:
            upload_screenshots.append({"file": p.name, "modified": p.stat().st_mtime})
    except Exception:
        upload_screenshots = []

    all_screenshots = []
    try:
        pngs = []
        for d in reports_dirs:
            pngs.extend([p for p in d.glob("*.png") if p.name.startswith("upload_") or p.name.startswith("visit_")])
        pngs = [p for p in pngs if p.stat().st_size > 1024]
        all_screenshots = sorted([p.name for p in pngs], reverse=True)
    except Exception:
        all_screenshots = []

    run_state_info = {"running": False, "live": None}
    try:
        # per-user lock
        lock_path = primary_reports_dir / "run.lock"
        state_path = primary_reports_dir / "run_state.json"
        if is_admin:
            if not lock_path.exists():
                lock_path = Path(cfg.get("reports", {}).get("dir", "reports")) / "run.lock"
            if not state_path.exists():
                state_path = Path(cfg.get("reports", {}).get("dir", "reports")) / "run_state.json"
        if lock_path.exists():
            try:
                ld = json.loads(lock_path.read_text())
                run_state_info = {"running": True, "live": bool(ld.get("live")), "run_id": ld.get("run_id"), "types": ld.get("types", [])}
            except Exception:
                pass
        elif state_path.exists():
            try:
                sd = json.loads(state_path.read_text())
                run_state_info = {"running": False, "live": bool(sd.get("live")), "run_id": sd.get("run_id"), "types": sd.get("types", [])}
            except Exception:
                pass
    except Exception:
        pass

    gemini_health = {"ok": True, "last_checked": None, "error": None}
    try:
        import gemini_api as _ga
        if hasattr(_ga, "last_health"):
            gemini_health = _ga.last_health
    except Exception:
        pass

    needs_credentials = (not is_admin and len(visited)==0) or len(sentinels)>0
    # if no profile file at all for user, needs_credentials True
    if not is_admin and uid:
        try:
            from web.per_user import get_user_profile_path, get_user_shard
            pp = get_user_profile_path(uid)
            if not pp.exists():
                needs_credentials = True
        except: pass

    # admin aggregate extra
    admin_users = []
    if is_admin:
        try:
            from web.db import get_all_users
            for u in get_all_users():
                vd = _load_per_user_visited(u["id"])
                bd = _load_per_user_budget(u["id"], "gemini")
                cbd = _load_per_user_budget(u["id"], "curation")
                rbd = _load_per_user_budget(u["id"], "rag")
                admin_users.append({"id": u["id"], "email": u["email"], "name": u["name"], "is_admin": bool(u["is_admin"]), "ledger_total": len(vd), "budget": f"{bd.get('calls_used',0)}/{cfg['gemini']['daily_call_limit']}", "curation": f"{cbd.get('calls_used',0)}/{cfg.get('resume_curation',{}).get('gemini_daily_limit',50)}", "rag": f"{rbd.get('calls_used',0)}/{cfg.get('rag',{}).get('daily_call_limit',50)}", "timezone": u.get("timezone") or "Asia/Kolkata", "timezone_locked": bool(u.get("timezone_locked")), "last_active": u.get("last_active_at")})
        except: pass

    rag_budget = _load_per_user_budget(uid, "rag")
    tz = _get_user_tz(uid)
    urow = None
    try:
        from web.db import get_user_by_id as _g2
        urow = _g2(uid) if uid else None
    except: pass
    return {
        "budget": {
            "day": budget["day"],
            "calls_used": budget["calls_used"],
            "daily_limit": cfg["gemini"]["daily_call_limit"],
            "timezone": budget.get("timezone") or tz,
            "reset_at": budget.get("reset_at"),
            "next_reset_at": budget.get("next_reset_at"),
            "last_call_at": budget.get("last_call_at"),
        },
        "curation_budget": {
            "day": curation_budget["day"],
            "calls_used": curation_budget["calls_used"],
            "daily_limit": cfg.get("resume_curation", {}).get("gemini_daily_limit", 50),
            "threshold": cfg.get("resume_curation", {}).get("match_threshold", 0.5),
            "timezone": curation_budget.get("timezone") or tz,
            "reset_at": curation_budget.get("reset_at"),
            "next_reset_at": curation_budget.get("next_reset_at"),
            "last_call_at": curation_budget.get("last_call_at"),
        },
        "rag_budget": {
            "day": rag_budget["day"],
            "calls_used": rag_budget.get("calls_used", 0),
            "daily_limit": cfg.get("rag", {}).get("daily_call_limit", 50),
            "timezone": rag_budget.get("timezone") or tz,
            "reset_at": rag_budget.get("reset_at"),
            "next_reset_at": rag_budget.get("next_reset_at"),
            "last_call_at": rag_budget.get("last_call_at"),
        },
        "timezone": {"name": tz, "locked": bool(urow.get("timezone_locked")) if urow else False, "locked_at": urow.get("timezone_locked_at") if urow else None} if urow else {"name": tz, "locked": False, "locked_at": None},
        "budgets": {
            "gemini": {"day": budget["day"], "calls_used": budget["calls_used"], "daily_limit": cfg["gemini"]["daily_call_limit"], "timezone": budget.get("timezone") or tz, "reset_at": budget.get("reset_at"), "next_reset_at": budget.get("next_reset_at"), "last_call_at": budget.get("last_call_at")},
            "curation": {"day": curation_budget["day"], "calls_used": curation_budget["calls_used"], "daily_limit": cfg.get("resume_curation", {}).get("gemini_daily_limit", 50), "timezone": curation_budget.get("timezone") or tz, "reset_at": curation_budget.get("reset_at"), "next_reset_at": curation_budget.get("next_reset_at"), "last_call_at": curation_budget.get("last_call_at")},
            "rag": {"day": rag_budget["day"], "calls_used": rag_budget.get("calls_used", 0), "daily_limit": cfg.get("rag", {}).get("daily_call_limit", 50), "timezone": rag_budget.get("timezone") or tz, "reset_at": rag_budget.get("reset_at"), "next_reset_at": rag_budget.get("next_reset_at"), "last_call_at": rag_budget.get("last_call_at")},
            "openrouter": _openrouter_spend_status(),
        },
        "curation_trace": {
            "changed_total": daily_changed,
            "uploaded_total": daily_uploaded,
            "runs_with_curation": daily_total,
            "day": budget.get("day"),
        },
        "upload_screenshots": upload_screenshots,
        "all_screenshots_total": len(all_screenshots),
        "active_resume": active,
        "rolling_5": rolling,
        "ledger": {
            "total_urls": len(visited),
            "by_status": by_status,
        },
        "profile_sentinels": sentinels,
        "dry_run_default": cfg["apply"]["dry_run"],
        "run_state": run_state_info,
        "gemini_health": gemini_health,
        "is_admin": is_admin,
        "needs_credentials": needs_credentials,
        "admin_users": admin_users,
    }


@router.get("/errors")
async def list_errors(request: Request = None, limit: int = 20):
    limit = max(1, min(limit, 100))
    uid, is_admin = _user_ctx(request)
    cfg = config_loader.load_config()
    dirs = _reports_dirs_for_user(uid, is_admin, cfg)
    items = []
    for d in dirs:
        p = d / "errors.jsonl"
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    items.append(json.loads(line))
                except Exception:
                    continue
        except Exception:
            continue
    items.sort(key=lambda e: e.get("at", ""), reverse=True)
    return {"errors": items[:limit], "total": len(items)}


@router.get("/reports")
async def list_reports(request: Request = None):
    uid, is_admin = _user_ctx(request)
    # build dirs list
    try:
        cfg_tmp = config_loader.load_config()
        dirs = _reports_dirs_for_user(uid, is_admin, cfg_tmp)
    except: dirs = [REPORTS_DIR]
    items = []
    for d in dirs:
        if not d.exists(): continue
        for f in d.glob("*.json"):
            if f.name.startswith("capture_"):
                kind, run_id = "capture", f.stem[len("capture_"):]
            elif f.name.startswith("visit_"):
                kind, run_id = "visit", f.stem[len("visit_"):]
            elif f.name.startswith("manual_"):
                kind, run_id = "manual", f.stem[len("manual_"):]
            else:
                continue
            items.append({
                "run_id": run_id,
                "kind": kind,
                "filename": f.name,
                "modified_at": f.stat().st_mtime,
            })
    items.sort(key=lambda x: x["modified_at"], reverse=True)
    return {"reports": items}


@router.get("/reports/{kind}/{run_id}")
async def get_report(kind: str, run_id: str, request: Request = None):
    if kind not in ("capture", "visit", "manual"):
        raise HTTPException(status_code=400, detail="kind must be 'capture', 'visit', or 'manual'")
    if not _RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="invalid run_id")
    uid, is_admin = _user_ctx(request)
    cfg_tmp = config_loader.load_config()
    dirs = _reports_dirs_for_user(uid, is_admin, cfg_tmp)
    for d in dirs:
        path = d / f"{kind}_{run_id}.json"
        if path.exists():
            with open(path) as fh:
                return json.load(fh)
    raise HTTPException(status_code=404, detail="report not found")


@router.get("/config")
async def get_config():
    """Current config.json, as-is. Nothing secret lives in here (the
    Gemini key stays in .env), so this is safe to return unfiltered."""
    return config_loader.load_config()


@router.get("/screenshots")
async def list_screenshots(request: Request = None, page: int = 0, limit: int = 3):
    if limit not in (3, 6, 12) and limit != 3:
        limit = 3
    if page < 0:
        page = 0
    uid, is_admin = _user_ctx(request)
    cfg = config_loader.load_config()
    dirs = _reports_dirs_for_user(uid, is_admin, cfg)
    files = []
    for d in dirs:
        files.extend([p for p in d.glob("*.png") if p.name.startswith("upload_") or p.name.startswith("visit_")])
    files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
    files = [p for p in files if p.stat().st_size > 1024]
    total = len(files)
    pages = (total + limit - 1) // limit if total else 1
    start = page * limit
    items = []
    for p in files[start:start+limit]:
        items.append({"file": p.name, "modified": p.stat().st_mtime, "size": p.stat().st_size})
    return {"items": items, "total": total, "pages": pages, "page": page, "limit": limit}


@router.get("/screenshots/file/{name}")
async def get_screenshot_file(name: str, request: Request = None):
    if not re.match(r"^[A-Za-z0-9_\-\.]+\.png$", name):
        raise HTTPException(status_code=400, detail="invalid name")
    uid, is_admin = _user_ctx(request)
    cfg = config_loader.load_config()
    dirs = _reports_dirs_for_user(uid, is_admin, cfg)
    for d in dirs:
        path = d / name
        if path.exists() and path.is_file():
            from fastapi.responses import FileResponse
            return FileResponse(str(path), media_type="image/png")
    raise HTTPException(status_code=404, detail="not found")


@router.get("/profile")
async def get_profile(request: Request = None):
    uid, is_admin = _user_ctx(request)
    profile = _load_per_user_profile(uid) if not is_admin else candidate_profile.load_candidate_profile()
    return {
        "profile": profile,
        "sentinels": candidate_profile.find_sentinels(profile),
    }

@router.get("/budget/raw")
async def get_budget_raw(request: Request = None):
    uid, is_admin = _user_ctx(request)
    if not uid:
        from fastapi import HTTPException as _HE; raise _HE(status_code=401, detail="Not authenticated")
    cfg = config_loader.load_config()
    return {
        "gemini": _load_per_user_budget(uid, "gemini"),
        "curation": _load_per_user_budget(uid, "curation"),
        "rag": _load_per_user_budget(uid, "rag"),
        "limits": {"gemini": cfg["gemini"]["daily_call_limit"], "curation": cfg.get("resume_curation", {}).get("gemini_daily_limit", 50), "rag": cfg.get("rag", {}).get("daily_call_limit", 50)},
    }

@router.get("/timezone")
async def get_timezone(request: Request = None):
    uid, _ = _user_ctx(request)
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from web.db import get_user_by_id
    u = get_user_by_id(uid)
    if not u: raise HTTPException(status_code=404, detail="User not found")
    return {"timezone": u.get("timezone") or "Asia/Kolkata", "locked": bool(u.get("timezone_locked")), "locked_at": u.get("timezone_locked_at")}

@router.post("/admin/users/{user_id}/timezone")
async def admin_set_timezone(user_id: int, request: Request = None):
    uid, is_admin = _user_ctx(request)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    tz = (data.get("timezone") or "").strip()
    if not tz:
        raise HTTPException(status_code=400, detail="timezone required")
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid timezone")
    from web.db import get_user_by_id, _conn
    target = get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Target user not found")
    old = target.get("timezone")
    conn = _conn()
    conn.execute("UPDATE users SET timezone=?, timezone_locked=1, timezone_locked_at=datetime('now') WHERE id=?", (tz, user_id))
    conn.commit()
    conn.close()
    try:
        p = Path("reports/timezone_changes.jsonl")
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(json.dumps({"at": __import__("datetime").datetime.now().isoformat(), "by_admin": uid, "user_id": user_id, "old_tz": old, "new_tz": tz, "reason": data.get("reason","")}) + "\n")
    except Exception:
        pass
    try:
        from web.per_user import record_audit
        record_audit(user_id, "timezone_admin", {"by_admin": uid, "new_tz": tz})
    except Exception:
        pass
    return {"ok": True, "timezone": tz}
