import pytest

from tests.conftest import reset_user, drop_user
from web.db import _conn, record_jd, record_tailor_run
from web.per_user import shard
from reporting import JobResult, visit_items

UID = 105
JD = "We need Python and Docker. Kubernetes is a must-have. 3+ years experience."


@pytest.fixture()
def u105():
    reset_user(UID, "erin@store.com", "Erin")
    yield UID
    drop_user(UID)


def test_jd_stored_once(u105):
    h1 = record_jd(UID, "http://x", "T", "C", JD)
    h2 = record_jd(UID, "http://x", "T", "C", JD)
    assert h1 == h2 and h1 is not None
    conn = _conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM jd_refs WHERE user_id=?", (UID,)).fetchone()[0]
        row = conn.execute("SELECT url, jd_text FROM jd_refs WHERE jd_hash=?", (h1,)).fetchone()
    finally:
        conn.close()
    assert n == 1 and row["url"] == "http://x" and "Kubernetes" in row["jd_text"]


def test_curate_persists_verdict(u105, monkeypatch):
    import resume.scorer as _sc, resume.curator as _cu, resume.review_loop as _rl
    monkeypatch.setattr(_sc, "score_jd_vs_resume", lambda jd, md, timeout=20: {"score": 0.3, "keywords": ["python"], "matched": ["python"], "missing": ["kubernetes"]})
    monkeypatch.setattr(_cu, "curate_md", lambda base, jd, timeout=40: "TAILORED")
    monkeypatch.setattr(_rl, "run_tailor_loop", lambda uid, jd, base, threshold=0.75: {"verdict": "pass", "attempts": [{"n": 1}], "final_md": "TAILORED", "best_score": 0.9})
    (shard(UID) / "resumes").mkdir(parents=True, exist_ok=True)
    (shard(UID) / "resumes" / "base.md").write_text("BASE Python Docker")
    from resume.rag.manager import get_manager, invalidate_manager
    invalidate_manager(UID)
    res = get_manager(UID).curate_for_jd(JD + " extra padding to be long enough here")
    assert res["tailor_run_id"] and res["jd_hash"]
    conn = _conn()
    try:
        row = conn.execute("SELECT verdict, best_score, keywords_json, attempts_json FROM tailor_runs WHERE id=?", (res["tailor_run_id"],)).fetchone()
        n = conn.execute("SELECT COUNT(*) FROM jd_refs WHERE user_id=?", (UID,)).fetchone()[0]
    finally:
        conn.close()
        invalidate_manager(UID)
    assert row["verdict"] == "pass" and row["best_score"] == 0.9
    assert "kubernetes" in row["keywords_json"] and n == 1


def test_visit_items_keep_transcript():
    r1 = JobResult(status="applied", job_type="python-jobs", url="http://a")
    r1.chat_transcript = [{"q": "CTC?", "a": "9.5"}]
    r2 = JobResult(status="failed", job_type="python-jobs", url="http://b")
    rows = visit_items([r1, r2], "2026-09-21T00:00:00")
    assert rows[0]["chat_transcript"] == [{"q": "CTC?", "a": "9.5"}]
    assert rows[1]["chat_transcript"] is None and rows[0]["attempted_at"] == "2026-09-21T00:00:00"


def test_dead_tables_gone():
    conn = _conn()
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "visited" not in names and "budgets" not in names
    assert {"jd_refs", "tailor_runs"} <= names
