"""Shared per-user test fixtures. Realistic formats stay (parsers need them); helpers live here once."""
import base64
import json
import os
import shutil
import pytest
from starlette.testclient import TestClient
from itsdangerous import TimestampSigner

from web.server import app
from web.db import _conn
from web.per_user import shard, shard_reports

_TABLES = ("users", "candidate_profiles", "reports", "resumes", "configs", "jd_refs", "tailor_runs")


def make_client(uid: int):
    client = TestClient(app)
    secret = os.environ.get("WEB_UI_SECRET_KEY", "jobsailor-secret-key-1234567890")
    b64 = base64.b64encode(json.dumps({"user_id": uid, "authenticated": True}).encode())
    client.cookies.set("jobsailor_session", TimestampSigner(secret).sign(b64).decode())
    return client


def reset_user(uid: int, email: str, name: str):
    import bcrypt
    conn = _conn()
    try:
        for t in _TABLES:
            conn.execute(f"DELETE FROM {t} WHERE {'id' if t == 'users' else 'user_id'} IN (?)", (uid,))
        pw = bcrypt.hashpw(b"testpass123", bcrypt.gensalt()).decode("utf-8")
        conn.execute("INSERT OR REPLACE INTO users (id, email, name, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?, 0, datetime('now'))", (uid, email, name, pw))
        conn.commit()
    finally:
        conn.close()
    for p in (shard(uid), shard_reports(uid)):
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
        p.mkdir(parents=True, exist_ok=True)


def drop_user(uid: int):
    conn = _conn()
    try:
        for t in _TABLES:
            conn.execute(f"DELETE FROM {t} WHERE {'id' if t == 'users' else 'user_id'} IN (?)", (uid,))
        conn.commit()
    finally:
        conn.close()
    for p in (shard(uid), shard_reports(uid)):
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
