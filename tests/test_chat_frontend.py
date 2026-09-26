import os
import json
import base64
import pytest
from starlette.testclient import TestClient
from itsdangerous import TimestampSigner

from web.server import app
from web.db import _conn

UID_TEST = 201


@pytest.fixture(autouse=True)
def clean_test_user():
    conn = _conn()
    conn.execute("DELETE FROM users WHERE id = ?", (UID_TEST,))
    conn.execute("DELETE FROM candidate_profiles WHERE user_id = ?", (UID_TEST,))
    conn.execute("DELETE FROM configs WHERE user_id = ?", (UID_TEST,))
    
    import bcrypt
    pw_hash = bcrypt.hashpw(b"testpass123", bcrypt.gensalt()).decode("utf-8")
    conn.execute("INSERT OR REPLACE INTO users (id, email, name, password_hash, is_admin, created_at) VALUES (?, ?, ?, ?, 0, datetime('now'))", (UID_TEST, "royal_chat@test.com", "Royal User", pw_hash))
    conn.commit()
    conn.close()
    
    yield
    
    conn = _conn()
    conn.execute("DELETE FROM users WHERE id = ?", (UID_TEST,))
    conn.execute("DELETE FROM candidate_profiles WHERE user_id = ?", (UID_TEST,))
    conn.execute("DELETE FROM configs WHERE user_id = ?", (UID_TEST,))
    conn.commit()
    conn.close()


def get_client(uid=UID_TEST):
    client = TestClient(app)
    secret = os.environ.get("WEB_UI_SECRET_KEY", "jobsailor-secret-key-1234567890")
    signer = TimestampSigner(secret)
    session_data = {"user_id": uid, "authenticated": True}
    b64_str = base64.b64encode(json.dumps(session_data).encode("utf-8"))
    signed = signer.sign(b64_str).decode("utf-8")
    client.cookies.set("jobsailor_session", signed)
    return client


def test_chat_page_auth_guard():
    """Verify unauthenticated requests to /chat are rejected with 401 Unauthorized."""
    unauth_client = TestClient(app)
    res = unauth_client.get("/chat", follow_redirects=False)
    assert res.status_code == 401


def test_chat_page_authenticated():
    """Verify authenticated user can load /chat HTML page with Royal theme elements."""
    client = get_client()
    res = client.get("/chat")
    assert res.status_code == 200
    html = res.text
    assert "JobSailor — Royal RAG Assistant" in html
    assert "royal-badge" in html
    assert "chat-input" in html
    assert "reindex-btn" in html
    assert "rag-stats" in html
    assert "--purple" in html


def test_chat_navbar_across_all_pages():
    """Verify all main app pages include the Chat / RAG link and chat-widget.js."""
    client = get_client()
    for route in ["/dashboard", "/reports", "/credentials", "/settings", "/help"]:
        res = client.get(route)
        assert res.status_code == 200, f"Failed on route {route}"
        assert 'href="/chat"' in res.text, f"Missing Chat link on {route}"
        assert 'chat-widget.js' in res.text, f"Missing chat-widget.js on {route}"


def test_rag_query_and_reindex_api():
    """Verify RAG query and reindex endpoints return valid JSON structures."""
    client = get_client()
    
    # Check stats
    res_stats = client.get("/api/rag/stats")
    assert res_stats.status_code == 200
    assert "chunks" in res_stats.json()
    assert "qa_cached" in res_stats.json()
    
    # Query direct single doc
    res_q = client.post("/api/rag/query", json={"query": "What is your email address?"})
    assert res_q.status_code == 200
    data = res_q.json()
    assert "answer" in data
    assert "route" in data
    assert "domain" in data
    assert "cached" in data
    assert "verified" in data
    assert "chunks" in data
