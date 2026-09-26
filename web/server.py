"""JobSailor web control panel - FastAPI app."""
import os, json, zipfile, io
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Request, Depends, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from web import auth
from web.routes_status import router as status_router
from web.routes_curation import router as curation_router
from web.routes_run import router as run_router
from web.routes_credentials import router as cred_router
from web.routes_rag import router as rag_router
from web.routes_timezone import router as tz_router

SECRET_KEY = os.environ.get("WEB_UI_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("WEB_UI_SECRET_KEY must be set in .env (signs session cookies). Run: venv/bin/python scripts/generate_password_hash.py")

STATIC_DIR = Path(__file__).parent / "static"
ASSETS_DIR = STATIC_DIR / "assets"

app = FastAPI(title="JobSailor Control Panel")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="jobsailor_session", max_age=60*60*12, same_site="lax", https_only=False)

app.mount("/static/assets", StaticFiles(directory=ASSETS_DIR), name="assets")
app.include_router(status_router, dependencies=[Depends(auth.require_auth)])
app.include_router(curation_router, dependencies=[Depends(auth.require_auth)])
app.include_router(run_router, dependencies=[Depends(auth.require_auth)])
app.include_router(cred_router, dependencies=[Depends(auth.require_auth)])
app.include_router(rag_router, dependencies=[Depends(auth.require_auth)])
app.include_router(tz_router, dependencies=[Depends(auth.require_auth)])

@app.exception_handler(HTTPException)
async def auth_redirect_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401:
        wants_html = "text/html" in request.headers.get("accept", "")
        if wants_html:
            return RedirectResponse(url="/login", status_code=303)
        return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    if request.session.get("user_id") or request.session.get("authenticated"):
        return RedirectResponse(url="/dashboard", status_code=303)
    p = STATIC_DIR / "landing.html"
    if p.exists(): return p.read_text()
    return RedirectResponse(url="/login", status_code=303)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user_id") or request.session.get("authenticated"):
        return RedirectResponse(url="/dashboard", status_code=303)
    return (STATIC_DIR / "login.html").read_text()

@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    # support both username (legacy) and email
    email = username.strip()
    if auth.is_locked_out():
        return HTMLResponse(_login_error_page("Too many failed attempts. Wait 5 minutes and try again."), status_code=429)
    user = auth.verify_credentials(email, password)
    if user:
        auth.clear_failed_attempts()
        request.session["user_id"] = user["id"]
        request.session["authenticated"] = True
        try:
            from web.per_user import record_audit
            record_audit(user["id"], "login", {"email": email})
        except Exception:
            pass
        return RedirectResponse(url="/dashboard", status_code=303)
    auth.record_failed_attempt()
    return HTMLResponse(_login_error_page("Incorrect email or password. Check email and password — use at least 8 chars, 1 number, 1 capital."), status_code=401)

@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    if request.session.get("user_id") or request.session.get("authenticated"):
        return RedirectResponse(url="/dashboard", status_code=303)
    p = STATIC_DIR / "signup.html"
    return p.read_text() if p.exists() else HTMLResponse("Signup not available", status_code=404)

@app.post("/api/signup")
async def signup_api(request: Request):
    try:
        data = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if not name: raise HTTPException(status_code=400, detail="Name is required")
    if not email or "@" not in email: raise HTTPException(status_code=400, detail="Enter a valid email")
    if len(password) < 8 or not any(c.isdigit() for c in password) or not any(c.isupper() for c in password):
        raise HTTPException(status_code=400, detail="Use at least 8 characters, 1 number, 1 capital")
    import bcrypt
    from web.db import get_user_by_email, create_user
    if get_user_by_email(email):
        raise HTTPException(status_code=400, detail="Email already registered")
    phash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    uid = create_user(email, name, phash)
    request.session["user_id"] = uid
    request.session["authenticated"] = True
    try:
        from web.per_user import record_audit
        record_audit(uid, "signup", {"email": email})
    except Exception:
        pass
    return {"ok": True}

@app.post("/logout")
async def logout(request: Request):
    try:
        from web.per_user import record_audit
        if request.session.get("user_id"):
            record_audit(request.session.get("user_id"), "logout")
    except Exception:
        pass
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)

def _login_error_page(message: str) -> str:
    page = (STATIC_DIR / "login.html").read_text()
    banner = f'<p class="error" role="alert">{message}</p>'
    return page.replace('<div id="error-slot"></div>', banner)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request, _=Depends(auth.require_auth)):
    # ponytail: no-cache like chat/credentials — stale HTML hid the theme toggle
    return HTMLResponse(content=(STATIC_DIR / "dashboard.html").read_text(), headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"})

@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, _=Depends(auth.require_auth)):
    return HTMLResponse(content=(STATIC_DIR / "reports.html").read_text(), headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"})

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, _=Depends(auth.require_auth)):
    return HTMLResponse(content=(STATIC_DIR / "settings.html").read_text(), headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"})

@app.get("/help", response_class=HTMLResponse)
async def help_page(request: Request, _=Depends(auth.require_auth)):
    return HTMLResponse(content=(STATIC_DIR / "help.html").read_text(), headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"})

@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, _=Depends(auth.require_auth)):
    return HTMLResponse(content=(STATIC_DIR / "chat.html").read_text(), headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"})

@app.get("/credentials", response_class=HTMLResponse)
async def credentials_page(request: Request, _=Depends(auth.require_auth)):
    return HTMLResponse(content=(STATIC_DIR / "credentials.html").read_text(), headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"})

@app.get("/api/export")
async def export_data(request: Request, _=Depends(auth.require_auth)):
    from web.db import get_user_by_id
    from web.per_user import get_user_shard, get_user_reports_dir
    uid = request.session.get("user_id")
    user = get_user_by_id(uid) if uid else None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if user:
            user_safe = dict(user)
            user_safe.pop("password_hash", None)
            z.writestr("user.json", json.dumps(user_safe, indent=2, default=str))
        if uid:
            shard = get_user_shard(uid)
            rep_dir = get_user_reports_dir(uid)
            for f in shard.glob("*"):
                # ponytail: dotfiles (.env.gemini) never leave the server — exports key-free by construction
                if f.is_file() and not f.name.startswith("."):
                    z.write(str(f), arcname=f.name)
            for rf in rep_dir.glob("*.json"):
                if rf.is_file():
                    z.write(str(rf), arcname=f"reports/{rf.name}")
            try:
                from web.per_user import get_user_chat_dir
                chat_dir = get_user_chat_dir(uid)
                for cf in chat_dir.glob("*.jsonl"):
                    if cf.is_file():
                        z.write(str(cf), arcname=f"chats/{cf.name}")
            except Exception:
                pass
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": f"attachment; filename=jobsailor_user_{uid}_export.zip"})

@app.post("/api/delete")
async def delete_account(request: Request, _=Depends(auth.require_auth)):
    try:
        data = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    confirm = data.get("confirm")
    password = data.get("password") or ""
    if confirm != "DELETE":
        raise HTTPException(status_code=400, detail="Type exactly DELETE to confirm")
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from web.db import get_user_by_id, soft_delete
    user = get_user_by_id(uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    import bcrypt
    if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        raise HTTPException(status_code=400, detail="Password incorrect. Re-enter your current password.")
    soft_delete(uid)
    # also export before delete? client already has button
    try:
        from web.per_user import record_audit
        record_audit(uid, "delete_account")
    except Exception:
        pass
    request.session.clear()
    import datetime
    purge = (datetime.datetime.now() + datetime.timedelta(days=30)).date().isoformat()
    return {"ok": True, "purge_at": purge}
