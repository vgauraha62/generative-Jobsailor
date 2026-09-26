import json
from pathlib import Path
from fastapi import APIRouter, Request, Depends, HTTPException
from web.auth import require_auth

router = APIRouter(prefix="/api/timezone")

@router.get("")
async def get_tz(request: Request, _=Depends(require_auth)):
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from web.db import get_user_by_id
    u = get_user_by_id(uid)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return {"timezone": u.get("timezone") or "Asia/Kolkata", "locked": bool(u.get("timezone_locked")), "locked_at": u.get("timezone_locked_at")}

@router.post("/confirm")
async def confirm_tz(request: Request, _=Depends(require_auth)):
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from web.db import get_user_by_id, _conn
    u = get_user_by_id(uid)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if u.get("timezone_locked"):
        raise HTTPException(status_code=403, detail="Timezone already locked. Contact admin via HELP > Raise Ticket to change.")
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
        raise HTTPException(status_code=400, detail="Invalid timezone. Use IANA like Asia/Kolkata or America/New_York")
    conn = _conn()
    conn.execute("UPDATE users SET timezone=?, timezone_locked=1, timezone_locked_at=datetime('now') WHERE id=?", (tz, uid))
    conn.commit()
    conn.close()
    try:
        from web.per_user import record_audit
        record_audit(uid, "timezone_confirm", {"timezone": tz})
    except Exception:
        pass
    return {"ok": True, "timezone": tz, "locked": True}

@router.post("/ticket")
async def ticket_tz(request: Request, _=Depends(require_auth)):
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    requested = (data.get("requested_timezone") or data.get("timezone") or "").strip()
    reason = (data.get("reason") or "").strip()
    if requested:
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(requested)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid requested_timezone")
    p = Path("reports/timezone_tickets.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps({"at": __import__("datetime").datetime.now().isoformat(), "user_id": uid, "requested_timezone": requested, "reason": reason}) + "\n")
    try:
        from web.per_user import record_audit
        record_audit(uid, "timezone_ticket", {"requested": requested})
    except Exception:
        pass
    return {"ok": True, "message": "Ticket raised. Admin will review."}
