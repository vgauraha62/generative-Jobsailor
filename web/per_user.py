import shutil, json
from pathlib import Path

def shard(uid: int) -> Path:
    p = Path("data/users") / str(uid)
    p.mkdir(parents=True, exist_ok=True)
    return p

def shard_reports(uid: int) -> Path:
    p = Path("reports") / str(uid)
    p.mkdir(parents=True, exist_ok=True)
    return p

def ensure_user_shard(uid: int):
    s = shard(uid)
    (s / "resumes").mkdir(exist_ok=True)
    (s / "reports").mkdir(exist_ok=True)
    return s

def get_user_config_path(uid: int) -> Path:
    return shard(uid) / "config.json"

def get_user_visited_path(uid: int) -> Path:
    return shard(uid) / "visited.json"

def get_user_budget_path(uid: int, kind: str) -> Path:
    mapping = {"gemini": "gemini_budget.json", "curation": "curation_budget.json", "rag": "rag_budget.json"}
    name = mapping.get(kind, f"{kind}_budget.json")
    return shard(uid) / name

def load_user_budget(uid: int, kind: str = "gemini", tz_name=None) -> dict:
    import json
    from datetime import datetime, timedelta
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        ZoneInfo = None
    def _now():
        if tz_name and ZoneInfo:
            try:
                return datetime.now(ZoneInfo(tz_name))
            except Exception:
                pass
        return datetime.now()
    today = _now().date().isoformat()
    p = get_user_budget_path(uid, kind)
    if p.exists():
        try:
            b = json.loads(p.read_text())
            if b.get("day") == today:
                if "timezone" not in b:
                    b["timezone"] = tz_name or "local"
                if "reset_at" not in b:
                    try:
                        ra = _now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
                        nra = (_now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat()
                    except Exception:
                        ra = _now().isoformat()
                        nra = (_now() + timedelta(days=1)).isoformat()
                    b["reset_at"] = ra
                    b["next_reset_at"] = nra
                return b
        except Exception:
            pass
    try:
        ra = _now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        nra = (_now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat()
    except Exception:
        ra = _now().isoformat()
        nra = (_now() + timedelta(days=1)).isoformat()
    b = {"day": today, "calls_used": 0, "timezone": tz_name or "local", "reset_at": ra, "next_reset_at": nra}
    try:
        p.write_text(json.dumps(b))
    except Exception:
        pass
    return b

def save_user_budget(uid: int, kind: str, data: dict):
    import json
    p = get_user_budget_path(uid, kind)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(p)

def record_user_budget_call(uid: int, kind: str, tz_name=None):
    from datetime import datetime
    b = load_user_budget(uid, kind, tz_name)
    b["calls_used"] = int(b.get("calls_used", 0)) + 1
    b["last_call_at"] = datetime.now().isoformat()
    save_user_budget(uid, kind, b)
    return b

def get_user_profile_path(uid: int) -> Path:
    return shard(uid) / "candidate_profile.json"

def get_user_reports_dir(uid: int) -> Path:
    return shard_reports(uid)

def get_user_chat_dir(uid: int) -> Path:
    p = shard(uid) / "chats"
    p.mkdir(parents=True, exist_ok=True)
    return p

def get_user_chat_path(uid: int, day: str) -> Path:
    safe = "".join(c for c in day if c.isalnum() or c in "-_")
    return get_user_chat_dir(uid) / f"chat_{safe}.jsonl"

def get_user_shard(uid: int) -> Path:
    return shard(uid)

def get_all_user_ids():
    base = Path("data/users")
    if not base.exists(): return []
    return [int(p.name) for p in base.iterdir() if p.is_dir() and p.name.isdigit()]

def record_audit(uid, action: str, detail=None):
    """Append one audit line. Best-effort, never raises. No secrets in detail."""
    # ponytail: JSONL append, no rotation lib; prune when it hurts
    try:
        from datetime import datetime
        d = shard_reports(int(uid))
        line = {"at": datetime.now().isoformat(), "user_id": int(uid), "action": action, "detail": detail}
        with open(d / "audit.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except Exception:
        pass

def migrate_global_to_user(uid: int):
    # Only migrate legacy single-operator data for uid 1
    if uid != 1:
        return
    try:
        sp = shard(uid)
        for name in ["visited.json", "gemini_budget.json", "curation_budget.json", "candidate_profile.json", "config.json"]:
            src = Path(name)
            dst = sp / name
            if src.exists() and not dst.exists():
                try: shutil.copy2(src, dst)
                except: pass
        for d in ["resumes"]:
            src = Path(d)
            dst = sp / d
            if src.exists() and not (dst / "base.md").exists():
                try: shutil.copytree(src, dst, dirs_exist_ok=True)
                except: pass
        base_reports = Path("reports")
        per_reports = shard_reports(uid)
        for f in base_reports.glob("*.json"):
            if f.name.startswith(("capture_","visit_","manual_")) and not (per_reports / f.name).exists():
                try: shutil.copy2(f, per_reports / f.name)
                except: pass
        for f in base_reports.glob("*.png"):
            if not (per_reports / f.name).exists():
                try: shutil.copy2(f, per_reports / f.name)
                except: pass
    except Exception as e:
        print(f"[migrate] warn {e}")
