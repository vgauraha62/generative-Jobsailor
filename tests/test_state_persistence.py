import pytest
from datetime import datetime, timezone

from tests.conftest import make_client, reset_user, drop_user
from web.routes_rag import _persist_chat

UID = 103


@pytest.fixture()
def client103():
    reset_user(UID, "carol@persist.com", "Carol")
    yield make_client(UID)
    drop_user(UID)


def test_chat_history_survives_refresh(client103):
    req = type("R", (), {"client": None})()
    _persist_chat(UID, "What are my skills?",
                  {"answer": "Python, Docker", "route": "SINGLE_DOC", "domain": "skills",
                   "cached": "direct", "verified": True, "chunks": [], "reason": "t", "latency_ms": 3}, req)
    day = datetime.now(timezone.utc).date().isoformat()
    res = client103.get(f"/api/rag/chats?day={day}&limit=100")
    assert res.status_code == 200
    chats = res.json()["chats"]
    assert any(c["query"]["raw"] == "What are my skills?"
               and "Python, Docker" in c["generation"]["answer"] for c in chats)


def test_resume_upload_autosaves_facts_keeps_prefs(client103):
    prefs = {"current_ctc_lpa": 9.5, "expected_ctc_lpa": 15.0, "notice_period_days": 30,
             "willing_to_relocate": True, "work_authorization": "Indian citizen", "passport_valid": True}
    save = client103.post("/api/credentials", json={
        "slugs": ["python-jobs"],
        "profile": {"resume_facts": {k: "NEEDS_REVIEW" for k in
                    ["name", "email", "phone", "highest_qualification", "institution",
                     "total_experience_years", "relevant_experience_years", "current_location", "skills"]},
                    "user_preferences": prefs}})
    assert save.status_code == 200
    resume = b"CAROL DANVERS\nEmail: carol@persist.com | Phone: 9112233445 | Pune\nSKILLS\nPython, Docker\nEDUCATION\nBachelor of Technology - College of Engineering Pune\n"
    up = client103.post("/api/credentials/resume", files={"file": ("cv.txt", resume, "text/plain")})
    assert up.status_code == 200
    reread = client103.get("/api/credentials").json()["profile"]
    assert reread["resume_facts"]["email"] == "carol@persist.com"  # autosaved, refresh-stable
    assert reread["user_preferences"]["current_ctc_lpa"] == 9.5  # never OCR-touched
    assert reread["user_preferences"]["notice_period_days"] == 30
