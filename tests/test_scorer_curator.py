import resume.scorer as scorer
import resume.curator as curator
import gemini_api

def test_score_empty_jd():
    assert scorer.score_jd_vs_resume("", "some resume")["score"]==0.0
    assert scorer.score_jd_vs_resume("   ", "md")["reason"]=="empty_jd"

def test_score_match(monkeypatch):
    monkeypatch.setattr(gemini_api, "bard_flash_response_curation", lambda q,t=None: '["python","docker"]')
    r=scorer.score_jd_vs_resume("jd with python docker", "resume has python docker")
    assert r["score"]==1.0
    assert "python" in r["matched"]

def test_score_missing(monkeypatch):
    monkeypatch.setattr(gemini_api, "bard_flash_response_curation", lambda q,t=None: '["kubernetes"]')
    r=scorer.score_jd_vs_resume("jd", "resume no match")
    assert r["score"]==0.0

def test_curator_fallback_short(monkeypatch):
    monkeypatch.setattr(gemini_api, "bard_flash_response_curation", lambda q,t=None: "short")
    base="a"*300
    out=curator.curate_md(base, "jd")
    assert out==base

def test_curator_ok(monkeypatch):
    monkeypatch.setattr(gemini_api, "bard_flash_response_curation", lambda q,t=None: "# New\n"+("x "*100))
    out=curator.curate_md("base "*100, "jd")
    assert "New" in out

def test_save_curated(tmp_path):
    p,h=curator.save_curated("# md", "jd text", out_dir=str(tmp_path))
    import os
    assert os.path.exists(p)
    assert len(h)==10
