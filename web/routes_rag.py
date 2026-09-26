import json
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import JSONResponse
from web.auth import require_auth, is_admin_user

router = APIRouter(prefix="/api/rag")


def _persist_chat(uid: int, q: str, res: dict, request: Request):
    try:
        from web.per_user import get_user_chat_path
        day = datetime.now(timezone.utc).date().isoformat()
        p = get_user_chat_path(uid, day)
        ip = request.client.host if request.client else ""
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:12] if ip else ""
        record = {
            "v": 1,
            "uid": uid,
            "ts": datetime.now(timezone.utc).isoformat(),
            "ts_day": day,
            "query": {"raw": q, "norm": q.lower().strip()[:500], "len": len(q)},
            "route": {"target": res.get("route"), "domain": res.get("domain"), "reason": res.get("reason")},
            "cache": {"tier": res.get("cached"), "hit": res.get("cached") in ("L1","L2","direct"), "matched_q": res.get("matched_q")},
            "retrieval": {"retrieved": len(res.get("chunks") or []), "chunks": [{"chunk_id": c.get("chunk_id"), "title": c.get("title","")[:80], "content_snippet": (c.get("content") or "")[:300]} for c in (res.get("chunks") or [])[:3]]},
            "generation": {"answer": (res.get("answer") or "")[:2000], "verified": res.get("verified"), "latency_ms": res.get("latency_ms")},
            "ip_hash": ip_hash,
        }
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


@router.post("/query")
async def rag_query(request: Request, _=Depends(require_auth)):
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    q = (data.get("q") or data.get("query") or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="q/query required")
    scope = data.get("scope", "auto")
    use_cache = bool(data.get("use_cache", True))
    verify = bool(data.get("verify", True))
    try:
        from web.db import get_user_by_id as _g
        tz = (_g(uid) or {}).get("timezone") or "Asia/Kolkata"
        from web.per_user import load_user_budget as _lub
        from config_loader import load_config as _lc
        rb = _lub(uid, "rag", tz)
        lim = _lc().get("rag", {}).get("daily_call_limit", 50)
        direct = q.lower().strip() in ("profile","reports","skills","metrics") or False
        is_miss = True
        if not direct:
            from resume.rag.manager import get_manager as _gm2
            _m2 = _gm2(uid)
            is_miss = q.lower().strip() not in [str(k).lower() for k in getattr(_m2.cache, 'store', {}).keys()] if hasattr(_m2, 'cache') else True
        if rb.get("calls_used", 0) >= lim and is_miss:
            raise HTTPException(status_code=429, detail=f"RAG daily limit {lim} reached. Resets at midnight {tz}.")
    except HTTPException:
        raise
    except Exception:
        pass
    from resume.rag.manager import get_manager
    m = get_manager(uid)
    try:
        res = m.query(q, scope=scope, use_cache=use_cache, verify=verify)
        try:
            if res.get("cached") not in ("L1","L2","direct") or res.get("route") == "miss":
                if res.get("answer") and res.get("answer") != "NEEDS_REVIEW":
                    from web.per_user import record_user_budget_call as _rec
                    _rec(uid, "rag", tz)
        except Exception:
            pass
    except Exception as e:
        res = {"answer": "NEEDS_REVIEW", "route": "error", "domain": "error", "cached": "miss", "verified": False, "chunks": [], "reason": str(e)[:300]}
        _persist_chat(uid, q, res, request)
        try:
            from web.per_user import record_audit
            record_audit(uid, "chat_query", {"q": q[:120], "route": "error"})
        except Exception:
            pass
        public_err = {k: v for k, v in res.items() if k not in ("matched_q","reason")}
        public_err["cached"] = "miss"
        return JSONResponse(status_code=200, content=public_err)
    _persist_chat(uid, q, res, request)
    try:
        from web.per_user import record_audit
        record_audit(uid, "chat_query", {"q": q[:120], "route": res.get("route"), "cached": res.get("cached")})
    except Exception:
        pass
    tier = res.get("cached","")
    hit = tier in ("L1","L2","direct","hit")
    public = {k: v for k, v in res.items() if k not in ("matched_q","reason")}
    public["cached"] = "hit" if hit else "miss"
    public["verified"] = bool(res.get("verified"))
    if "chunks" in public:
        public["chunks"] = public["chunks"][:3]
    return public


@router.post("/reindex")
async def rag_reindex(request: Request, _=Depends(require_auth)):
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from resume.rag.manager import get_manager
    m = get_manager(uid)
    stats = m.rebuild_index()
    try:
        from web.per_user import record_audit
        record_audit(uid, "rag_reindex", {"stats": stats} if isinstance(stats, dict) else None)
    except Exception:
        pass
    return {"ok": True, "stats": stats, "manager_stats": m.get_stats()}


@router.get("/stats")
async def rag_stats(request: Request, _=Depends(require_auth)):
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from resume.rag.manager import get_manager
    m = get_manager(uid)
    return m.get_stats()


@router.get("/chats")
async def rag_chats(request: Request, day: str = "", limit: int = 100, _=Depends(require_auth)):
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if day and not day.replace("-","").replace("_","").isalnum():
        raise HTTPException(status_code=400, detail="invalid day")
    from web.per_user import get_user_chat_dir, get_user_chat_path
    from pathlib import Path
    chat_dir = get_user_chat_dir(uid)
    if day:
        p = get_user_chat_path(uid, day)
        if not p.exists():
            return {"chats": [], "day": day}
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]
        chats = []
        for l in lines:
            try:
                chats.append(json.loads(l))
            except Exception:
                continue
        return {"chats": chats, "day": day, "count": len(chats)}
    files = sorted(chat_dir.glob("chat_*.jsonl"))
    out = []
    for f in files[-7:]:
        out.append({"file": f.name, "size": f.stat().st_size, "modified": f.stat().st_mtime})
    return {"files": out, "chat_dir": str(chat_dir)}


@router.post("/curate")
async def rag_curate(request: Request, _=Depends(require_auth)):
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    jd = (data.get("jd") or data.get("jd_text") or "").strip()
    if not jd:
        raise HTTPException(status_code=400, detail="jd/jd_text required")
    from resume.rag.manager import get_manager
    m = get_manager(uid)
    res = m.curate_for_jd(jd)
    try:
        from web.per_user import record_audit
        record_audit(uid, "rag_curate", {"jd_hash": res.get("jd_hash"), "verdict": (res.get("review") or {}).get("verdict") if isinstance(res.get("review"), dict) else None})
    except Exception:
        pass
    return res
