import sqlite3, os
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "users.db"

def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def ensure_legacy_user(email, name, phash):
    from dotenv import load_dotenv
    load_dotenv()
    if not email or not phash:
        # re-read env if missing (import order)
        import os as _os, bcrypt as _bc
        email = email or _os.environ.get("WEB_UI_EMAIL") or (_os.environ.get("WEB_UI_USER","") + "@local" if _os.environ.get("WEB_UI_USER") and "@" not in _os.environ.get("WEB_UI_USER","") else _os.environ.get("WEB_UI_USER"))
        name = name or _os.environ.get("WEB_UI_USER")
        phash = phash or _os.environ.get("WEB_UI_PASSWORD_HASH")
    if not email or not name or not phash:
        return None
    conn = _conn()
    cur = conn.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE", (email,))
    row = cur.fetchone()
    if not row:
        cur = conn.execute("SELECT * FROM users WHERE name=? COLLATE NOCASE", (name,))
        row = cur.fetchone()
    if row:
        if row["is_deleted"]:
            conn.execute("UPDATE users SET is_deleted=0, purge_at=NULL, password_hash=?, email=? WHERE id=?", (phash, email, row["id"]))
            conn.commit()
        elif row["password_hash"] != phash:
            conn.execute("UPDATE users SET password_hash=? WHERE id=?", (phash, row["id"]))
            conn.commit()
        conn.close()
        return get_user_by_email(email) or get_user_by_name(name)
    try:
        cur = conn.execute("INSERT INTO users (email,name,password_hash,created_at) VALUES (?,?,?,datetime('now'))", (email, name, phash))
        conn.commit()
        uid = cur.lastrowid
        conn.close()
        return get_user_by_id(uid) or {"id": uid, "email": email, "name": name, "password_hash": phash}
    except Exception:
        conn.close()
        return get_user_by_email(email) or get_user_by_name(name)

def _ensure_is_admin_column(conn):
    cur = conn.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in cur.fetchall()]
    if "is_admin" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
        conn.commit()

def _ensure_timezone_columns(conn):
    cur = conn.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in cur.fetchall()]
    if "timezone" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN timezone TEXT DEFAULT 'Asia/Kolkata'")
        conn.commit()
    if "timezone_locked" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN timezone_locked INTEGER DEFAULT 0")
        conn.commit()
    if "timezone_locked_at" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN timezone_locked_at TEXT")
        conn.commit()
    try:
        conn.execute("UPDATE users SET timezone='Asia/Kolkata' WHERE timezone IS NULL")
        conn.commit()
    except Exception:
        pass

def init_db():
    conn = _conn()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_active_at TEXT,
        is_deleted INTEGER DEFAULT 0,
        purge_at TEXT,
        is_admin INTEGER DEFAULT 0
    )""")
    conn.commit()
    _ensure_is_admin_column(conn)
    _ensure_timezone_columns(conn)
    # per-user data tables (free sqlite)
    conn.execute("CREATE TABLE IF NOT EXISTS candidate_profiles (user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, profile_json TEXT NOT NULL, updated_at TEXT DEFAULT (datetime('now')))")
    # ponytail: visited/budgets tables deleted (zero readers; JSON files are live). LLM-shaped data goes to jd_refs/tailor_runs.
    conn.execute("DROP TABLE IF EXISTS visited")
    conn.execute("DROP TABLE IF EXISTS budgets")
    conn.execute("CREATE TABLE IF NOT EXISTS jd_refs (jd_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, url TEXT DEFAULT '', title TEXT DEFAULT '', company TEXT DEFAULT '', jd_text TEXT NOT NULL, fetched_at TEXT DEFAULT (datetime('now')))")
    conn.execute("CREATE TABLE IF NOT EXISTS tailor_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, jd_hash TEXT NOT NULL REFERENCES jd_refs(jd_hash) ON DELETE CASCADE, verdict TEXT NOT NULL, best_score REAL DEFAULT 0, keywords_json TEXT DEFAULT '[]', attempts_json TEXT DEFAULT '[]', created_at TEXT DEFAULT (datetime('now')))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tailor_user ON tailor_runs(user_id)")
    conn.execute("CREATE TABLE IF NOT EXISTS configs (user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, raw_json TEXT NOT NULL, updated_at TEXT DEFAULT (datetime('now')))")
    conn.execute("CREATE TABLE IF NOT EXISTS reports (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, kind TEXT NOT NULL, run_id TEXT NOT NULL, payload_json TEXT NOT NULL, UNIQUE(user_id,kind,run_id))")
    conn.execute("CREATE TABLE IF NOT EXISTS resumes (user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, kind TEXT NOT NULL, sha TEXT, path TEXT NOT NULL, UNIQUE(user_id,kind,sha))")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")
    conn.close()
    try:
        from dotenv import load_dotenv
        load_dotenv()
        import os, bcrypt
        env_user = os.environ.get("WEB_UI_USER")
        env_hash = os.environ.get("WEB_UI_PASSWORD_HASH")
        if env_user and env_hash:
            env_email = os.environ.get("WEB_UI_EMAIL") or (env_user + "@local" if "@" not in env_user else env_user)
            ensure_legacy_user(env_email, env_user, env_hash)
        # ensure admin vaibhavgauraha62@gmail.com is_admin=1
        admin_email = "vaibhavgauraha62@gmail.com"
        conn2 = _conn()
        cur = conn2.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE", (admin_email,))
        row = cur.fetchone()
        if row and not row["is_admin"]:
            conn2.execute("UPDATE users SET is_admin=1 WHERE id=?", (row["id"],))
            conn2.commit()
        elif not row:
            # create placeholder admin if not exists and env has admin creds? leave for first signup with that email
            pass
        conn2.close()
    except Exception:
        pass

def get_user_by_email(email):
    conn = _conn()
    cur = conn.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE AND is_deleted=0", (email,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_id(uid):
    conn = _conn()
    cur = conn.execute("SELECT * FROM users WHERE id=? AND is_deleted=0", (uid,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_name(name):
    conn = _conn()
    cur = conn.execute("SELECT * FROM users WHERE name=? COLLATE NOCASE AND is_deleted=0", (name,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(email, name, password_hash):
    conn = _conn()
    cur = conn.execute("INSERT INTO users (email,name,password_hash,created_at) VALUES (?,?,?,datetime('now'))", (email, name, password_hash))
    conn.commit()
    uid = cur.lastrowid
    conn.close()
    return uid

def update_last_active(uid):
    conn = _conn()
    conn.execute("UPDATE users SET last_active_at=datetime('now') WHERE id=?", (uid,))
    conn.commit()
    conn.close()

def soft_delete(uid):
    conn = _conn()
    conn.execute("UPDATE users SET is_deleted=1, purge_at=datetime('now','+30 days') WHERE id=?", (uid,))
    conn.commit()
    conn.close()


def record_jd(uid, url="", title="", company="", jd_text=""):
    """Store a JD once per hash; returns jd_hash or None. Best-effort, never raises."""
    try:
        from web.schema import jd_hash
        if not uid or not (jd_text or "").strip():
            return None
        h = jd_hash(url or "", jd_text)
        conn = _conn()
        try:
            conn.execute("INSERT OR IGNORE INTO jd_refs (jd_hash, user_id, url, title, company, jd_text) VALUES (?,?,?,?,?,?)", (h, int(uid), url or "", title or "", company or "", jd_text))
            conn.commit()
        finally:
            conn.close()
        return h
    except Exception:
        return None


def record_tailor_run(uid, jd_hash, verdict, best_score=0.0, keywords=None, attempts=None):
    """Store a loop verdict; returns row id or None. Best-effort, never raises."""
    import json as _js
    if not uid or not jd_hash:
        return None
    try:
        conn = _conn()
        try:
            cur = conn.execute("INSERT INTO tailor_runs (user_id, jd_hash, verdict, best_score, keywords_json, attempts_json) VALUES (?,?,?,?,?,?)", (int(uid), jd_hash, verdict, float(best_score or 0), _js.dumps(keywords or {}), _js.dumps(attempts or [])))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()
    except Exception:
        return None

def all_user_data(uid):
    conn = _conn()
    cur = conn.execute("SELECT * FROM users WHERE id=?", (uid,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_users():
    conn = _conn()
    cur = conn.execute("SELECT id,email,name,is_admin,created_at,last_active_at,is_deleted,purge_at FROM users WHERE is_deleted=0 ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_user_shard(uid):
    p = Path(__file__).parent.parent / "data" / "users" / str(uid)
    p.mkdir(parents=True, exist_ok=True)
    return p

# init on import
try:
    init_db()
except Exception:
    pass
