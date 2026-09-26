import json
import pytest

import gemini_api
import resume.review_loop as rl
from resume.review_loop import run_tailor_loop
from gemini_api import openrouter_complete as _real_complete  # bound pre-fixture, unshadowed


@pytest.fixture(autouse=True)
def stubbed(monkeypatch):
    state = {"calls": [], "scripted": []}
    monkeypatch.setattr(gemini_api, "openrouter_model", lambda kind="micro": {"proposer": "p", "reviewer": "r"}.get(kind))
    monkeypatch.setattr(gemini_api, "provider_for", lambda uid=None: "openrouter")

    def fake(model, system, user, timeout=40, max_tokens=None, preset="micro"):
        state["calls"].append({"model": model, "user": user, "preset": preset})
        return state["scripted"].pop(0)

    monkeypatch.setattr(gemini_api, "openrouter_complete", fake)
    monkeypatch.setattr(rl, "_ok", lambda uid: True)
    monkeypatch.setattr(rl, "_record", lambda uid: None)
    return state


def _pass(score=0.9):
    return json.dumps({"pass": True, "score": score, "what_it_did": "did", "why_failed": "", "what_to_change": []})


def _fail(score=0.3, change="add kubernetes"):
    return json.dumps({"pass": False, "score": score, "what_it_did": "tried", "why_failed": "missing kw", "what_to_change": [change]})


def test_pass_first_try(stubbed):
    stubbed["scripted"] = ["TAILORED v1", _pass()]
    r = run_tailor_loop(1, "JD python", "BASE md")
    assert r["verdict"] == "pass" and r["final_md"] == "TAILORED v1" and len(r["attempts"]) == 1


def test_fail_retries_with_feedback(stubbed):
    stubbed["scripted"] = ["TAILORED v1", _fail(), "TAILORED v2", _pass()]
    r = run_tailor_loop(1, "JD python", "BASE md")
    assert r["verdict"] == "pass" and len(r["attempts"]) == 2
    assert "add kubernetes" in stubbed["calls"][2]["user"]  # feedback triple injected into retry


def test_exhausted_returns_best(stubbed):
    stubbed["scripted"] = ["V1", _fail(0.2), "V2", _fail(0.5), "V3", _fail(0.4)]
    r = run_tailor_loop(1, "JD", "BASE")
    assert r["verdict"] == "best_effort" and r["final_md"] == "V2" and r["best_score"] == 0.5


def test_no_models_fail_open_zero_calls(stubbed, monkeypatch):
    monkeypatch.setattr(gemini_api, "openrouter_model", lambda kind="micro": None)
    r = run_tailor_loop(1, "JD", "BASE")
    assert r == {"verdict": "fail_open", "attempts": [], "final_md": None, "best_score": 0.0}
    assert stubbed["calls"] == []


def test_reviewer_parse_error_counts_as_fail(stubbed):
    stubbed["scripted"] = ["V1", "not json{{{", "V2", "still not json", "V3", _pass()]
    r = run_tailor_loop(1, "JD", "BASE")
    assert r["attempts"][0]["review"]["why_failed"] == "reviewer_parse_error"
    assert r["verdict"] == "pass" and len(r["attempts"]) == 3


def test_preset_caps_on_wire(stubbed):
    stubbed["scripted"] = ["V1", _pass()]
    run_tailor_loop(1, "JD", "BASE")
    assert [c["preset"] for c in stubbed["calls"]] == ["proposer", "reviewer"]


def test_clamp_and_402(monkeypatch):
    import io
    import urllib.error as _urlerr
    import urllib.request as _url
    monkeypatch.setattr(gemini_api, "openrouter_complete", _real_complete)
    openrouter_complete = _real_complete
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}

    def fake_open(req, timeout=40):
        seen.update(json.loads(req.data.decode()))
        if seen.get("trap402"):
            raise _urlerr.HTTPError(req.full_url, 402, "Payment Required", {}, io.BytesIO(b"{}"))
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": " hi "}}]}).encode())

    monkeypatch.setattr(_url, "urlopen", fake_open)
    assert openrouter_complete("m", "s", "u", max_tokens=16384) == "hi"  # clamped to 4000
    assert seen["max_tokens"] == 4000
    assert openrouter_complete("m", "s", "u") == "hi"  # micro preset cap
    assert seen["max_tokens"] == 50
    assert openrouter_complete("m", "s", "u", preset="form") == "hi"  # form preset cap
    assert seen["max_tokens"] == 500
    seen["trap402"] = True
    with pytest.raises(RuntimeError, match="openrouter_402"):
        openrouter_complete("m", "s", "u")


def test_402_in_loop_fails_open(stubbed):
    stubbed["scripted"] = []
    import gemini_api as _ga
    orig = _ga.openrouter_complete
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise RuntimeError("openrouter_402: key affords < requested; lower max_tokens or add credits")

    _ga.openrouter_complete = boom
    try:
        r = run_tailor_loop(1, "JD", "BASE")
    finally:
        _ga.openrouter_complete = orig
    assert r["verdict"] == "fail_open" and r["final_md"] is None
    assert len(calls) == 1  # no retry — price won't drop
