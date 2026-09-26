import json

import pytest

from tests.conftest import make_client, reset_user, drop_user
from web.per_user import record_audit, shard_reports

UID = 107


@pytest.fixture()
def client107():
    reset_user(UID, "aud@pool.com", "Aud")
    yield make_client(UID)
    drop_user(UID)


def _lines(uid=UID):
    p = shard_reports(uid) / "audit.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def test_audit_login_logout(client107):
    assert client107.post("/logout").status_code in (200, 303, 307)
    acts = [l["action"] for l in _lines()]
    assert "logout" in acts


def test_audit_credentials_save_no_secrets(client107):
    r = client107.post("/api/credentials", json={"slugs": [], "gemini_key": "SUPER-SECRET-KEY", "gemini_model": "m"})
    assert r.status_code == 200
    lines = _lines()
    assert any(l["action"] == "credentials_save" for l in lines)
    blob = json.dumps(lines)
    assert "SUPER-SECRET-KEY" not in blob


def test_audit_run_start_stop(client107, monkeypatch):
    import web.routes_run as rr
    monkeypatch.setattr(rr, "_load_cfg", lambda: {"search": {"max_run_types": 3}, "reports": {"dir": "reports"}})
    import subprocess
    from unittest.mock import MagicMock, patch as _p
    with _p.object(rr, "_load_cfg", return_value={"search": {"max_run_types": 3}, "reports": {"dir": "reports"}}), \
         _p("candidate_profile.load_candidate_profile", return_value={}), \
         _p("candidate_profile.find_sentinels", return_value=[]), \
         _p("gemini_api.health_check", return_value={"ok": True, "model": "x"}), \
         _p("subprocess.Popen") as mock_pop:
        mock_proc = MagicMock()
        mock_proc.pid = 99991
        mock_proc.returncode = None
        mock_proc.poll = MagicMock(return_value=None)
        mock_proc.wait = MagicMock()
        mock_pop.return_value = mock_proc
        r = client107.post("/api/run", json={"types": ["python"], "live": False})
        assert r.status_code == 200, r.text
    acts = [l["action"] for l in _lines()]
    assert "run_start" in acts
    # cleanup per-user lock left behind
    from web.per_user import get_user_reports_dir
    (get_user_reports_dir(UID) / "run.lock").unlink(missing_ok=True)


def test_audit_never_bricks():
    record_audit(None, "x")  # no uid, no dir panic
    record_audit(UID, "x", {"k": "v"})
