"""Session-based auth now with users table (email + bcrypt)."""
import os, time, bcrypt
from fastapi import Request, HTTPException, status
try:
    from web.db import get_user_by_email, get_user_by_id, update_last_active
except Exception:
    get_user_by_email = get_user_by_id = update_last_active = lambda *a, **k: None

_MAX_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300
_failed_attempts: list[float] = []

def _prune_old_attempts():
    cutoff = time.time() - _LOCKOUT_SECONDS
    while _failed_attempts and _failed_attempts[0] < cutoff:
        _failed_attempts.pop(0)

def is_locked_out() -> bool:
    _prune_old_attempts()
    return len(_failed_attempts) >= _MAX_ATTEMPTS

def record_failed_attempt(): _failed_attempts.append(time.time())
def clear_failed_attempts(): _failed_attempts.clear()

def verify_credentials(email: str, password: str):
    try:
        from web.db import get_user_by_name, ensure_legacy_user
    except:
        get_user_by_name = lambda *a,**k: None
        ensure_legacy_user = lambda *a,**k: None
    u = get_user_by_email(email) if get_user_by_email else None
    if not u:
        u = get_user_by_name(email) if get_user_by_name else None
    if u:
        if bcrypt.checkpw(password.encode("utf-8"), u["password_hash"].encode("utf-8")):
            return u
        # fallback to env if hash rotated
        try:
            from dotenv import load_dotenv
            load_dotenv()
            env_user = os.environ.get("WEB_UI_USER")
            env_hash = os.environ.get("WEB_UI_PASSWORD_HASH")
            if env_user and env_hash and email.lower() in (env_user.lower(), (os.environ.get("WEB_UI_EMAIL") or "").lower(), (env_user+"@local").lower()):
                if bcrypt.checkpw(password.encode(), env_hash.encode()):
                    # sync new hash
                    try:
                        ensure_legacy_user(u["email"], u["name"], env_hash)
                        u = get_user_by_email(email) or get_user_by_name(email) or u
                        return u
                    except: pass
        except: pass
        return None
    # DB miss — fallback to env single-operator exception
    try:
        from dotenv import load_dotenv
        load_dotenv()
        env_user = os.environ.get("WEB_UI_USER")
        env_hash = os.environ.get("WEB_UI_PASSWORD_HASH")
        env_email = os.environ.get("WEB_UI_EMAIL") or (env_user + "@local" if env_user and "@" not in env_user else env_user)
        if env_user and env_hash and email.lower() in (env_user.lower(), (env_email or "").lower(), env_user.lower()+"@local"):
            if bcrypt.checkpw(password.encode(), env_hash.encode()):
                try:
                    u2 = ensure_legacy_user(env_email, env_user, env_hash)
                    if u2: return u2
                except: pass
                # return ephemeral legacy identity even if DB write fails
                return {"id": 0, "email": env_email, "name": env_user, "password_hash": env_hash, "is_deleted": 0}
    except: pass
    return None

def require_auth(request: Request):
    uid = request.session.get("user_id")
    if not uid:
        if not request.session.get("authenticated"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
        return True
    u = get_user_by_id(uid) if get_user_by_id else None
    if not u:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try: update_last_active(uid)
    except: pass
    request.state.user = u
    request.state.is_admin = bool(u.get("is_admin"))
    return True

def require_admin(request: Request):
    require_auth(request)
    if not getattr(request.state, "is_admin", False):
        # allow legacy admin email even if flag not set yet
        u = getattr(request.state, "user", None)
        if u and u.get("email","").lower() == "vaibhavgauraha62@gmail.com":
            return True
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return True

def get_current_user(request: Request):
    uid = request.session.get("user_id")
    if uid and get_user_by_id:
        return get_user_by_id(uid)
    return None

def is_admin_user(user):
    if not user: return False
    if user.get("is_admin"): return True
    return user.get("email","").lower() == "vaibhavgauraha62@gmail.com"
