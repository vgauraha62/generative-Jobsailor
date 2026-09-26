import io
import zipfile
import pytest

import gemini_api
from gemini_api import provider_for
from tests.conftest import make_client, reset_user, drop_user
from web.per_user import shard

UID = 104


@pytest.fixture()
def client104():
    reset_user(UID, "dave@pool.com", "Dave")
    yield make_client(UID)
    drop_user(UID)


def test_owned_key_never_touches_openrouter(client104, monkeypatch):
    (shard(UID) / ".env.gemini").write_text("GEMINI_API_KEY=OWN-KEY\nGEMINI_MODEL=m\n")
    assert provider_for(UID) == "gemini_own"
    calls = []
    monkeypatch.setattr(gemini_api, "openrouter_complete", lambda *a, **k: calls.append(1))
    from resume.review_loop import run_tailor_loop
    r = run_tailor_loop(UID, "JD", "BASE")
    assert r["verdict"] == "fail_open" and r["final_md"] is None and calls == []


def test_empty_save_reverts_to_pool(client104, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    assert client104.post("/api/credentials", json={"slugs": [], "gemini_key": "OWN-KEY"}).status_code == 200
    assert provider_for(UID) == "gemini_own"
    assert client104.post("/api/credentials", json={"slugs": []}).status_code == 200
    gem = shard(UID) / ".env.gemini"
    assert "GEMINI_API_KEY" not in (gem.read_text() if gem.exists() else "")
    assert provider_for(UID) != "gemini_own"
    assert client104.get("/api/credentials").json()["provider"] != "gemini_own"


def test_export_has_no_secrets(client104):
    (shard(UID) / ".env.gemini").write_text("GEMINI_API_KEY=SUPER-SECRET\nOPENROUTER_API_KEY=OP-SECRET\n")
    (shard(UID) / "candidate_profile.json").write_text("{}")
    res = client104.get("/api/export")
    assert res.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(res.content))
    assert not any(n.startswith(".") or "/." in n for n in z.namelist())
    blob = "".join(z.read(n).decode("utf-8", errors="ignore") for n in z.namelist())
    assert "SUPER-SECRET" not in blob and "OP-SECRET" not in blob
