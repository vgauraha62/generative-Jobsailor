"""Work-history/skills/metrics structured answers — self-contained fixture user.

Ponytail: these tests once read live uid-4 data and broke when a real resume
landed there. Now they build their own synthetic engineer and drop it after.
"""
import json

import pytest

from resume.rag.manager import get_manager
from tests.conftest import reset_user, drop_user
from web.per_user import shard

UID = 204

_FIXTURE_MD = """# Fixture Engineer — AI Engineer

## AI Engineer, Cactus Communications
2021 — 2023
- Built RAG pipelines with LLM orchestration and Dockerized PyTorch services serving 50,000 daily users at 100% uptime SLO.
- Improved retrieval accuracy to 97% and cut inference cost by 40%.

## AI Engineer, Execve
2023 — 2025
- Shipped LLM chat features to production with 100% test coverage on golden sets.
- Grew adoption to 50,000 weekly users while holding latency budgets.
"""

_FIXTURE_PROFILE = {
    "resume_facts": {
        "name": "Fixture Engineer",
        "skills": "RAG, Docker, LLM, PyTorch, Python, FastAPI",
    },
    "user_preferences": {},
}


@pytest.fixture(scope="module")
def fx():
    reset_user(UID, "fixture204@pool.com", "Fixture")
    s = shard(UID)
    (s / "resumes").mkdir(parents=True, exist_ok=True)
    (s / "resumes" / "base.md").write_text(_FIXTURE_MD)
    (s / "candidate_profile.json").write_text(json.dumps(_FIXTURE_PROFILE))
    m = get_manager(UID)
    m.query("warmup", use_cache=False)  # ponytail: build index here; latency asserts measure queries, not ingest
    yield m
    drop_user(UID)


def test_work_history_structured_summary(fx):
    res = fx.query("what is my work history?", use_cache=False)
    assert res is not None
    assert "Work History" in res["answer"] or "AI Engineer" in res["answer"]
    assert "Cactus" in res["answer"]
    assert "Execve" in res["answer"]
    assert res["verified"] is True
    assert res["latency_ms"] < 2500


def test_work_history_company_verification_positive(fx):
    res1 = fx.query("did i work for execve?", use_cache=False)
    assert res1["answer"].startswith("Yes —")
    assert "Execve" in res1["answer"]

    res2 = fx.query("did i work for cactus communications?", use_cache=False)
    assert res2["answer"].startswith("Yes —")
    assert "Cactus" in res2["answer"]


def test_work_history_company_verification_negative(fx):
    res = fx.query("did i work for google?", use_cache=False)
    assert res["answer"].startswith("No —")
    assert "Cactus" in res["answer"] or "Execve" in res["answer"]


def test_skills_and_metrics_structured(fx):
    res_s = fx.query("Summarize my core technical skills and tools", use_cache=False)
    assert "Core skills:" in res_s["answer"]
    assert any(k in res_s["answer"].lower() for k in ["rag", "docker", "llm", "pytorch"])

    res_m = fx.query("What are my key quantified revenue and leadership metrics?", use_cache=False)
    assert "Key metrics:" in res_m["answer"]
    assert any(k in res_m["answer"] for k in ["50,000", "100%", "97%", "40%"])
