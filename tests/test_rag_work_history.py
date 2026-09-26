import pytest
from resume.rag.manager import get_manager


def test_work_history_structured_summary():
    m = get_manager(4)
    res = m.query("what is my work history?", use_cache=False)
    assert res is not None
    assert "Work History" in res["answer"] or "AI Engineer" in res["answer"]
    assert "Cactus" in res["answer"]
    assert "Execve" in res["answer"]
    assert res["verified"] is True
    assert res["latency_ms"] < 2500


def test_work_history_company_verification_positive():
    m = get_manager(4)
    res1 = m.query("did i work for execve?", use_cache=False)
    assert res1["answer"].startswith("Yes —")
    assert "Execve" in res1["answer"]

    res2 = m.query("did i work for cactus communications?", use_cache=False)
    assert res2["answer"].startswith("Yes —")
    assert "Cactus" in res2["answer"]


def test_work_history_company_verification_negative():
    m = get_manager(4)
    res = m.query("did i work for google?", use_cache=False)
    assert res["answer"].startswith("No —")
    assert "Cactus" in res["answer"] or "Execve" in res["answer"]


def test_skills_and_metrics_structured():
    m = get_manager(4)
    res_s = m.query("Summarize my core technical skills and tools", use_cache=False)
    assert "Core skills:" in res_s["answer"]
    assert any(k in res_s["answer"].lower() for k in ["rag", "docker", "llm", "pytorch"])

    res_m = m.query("What are my key quantified revenue and leadership metrics?", use_cache=False)
    assert "Key metrics:" in res_m["answer"]
    assert any(k in res_m["answer"] for k in ["50,000", "100%", "97%", "40%"])
