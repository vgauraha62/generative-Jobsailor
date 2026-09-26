import os, json, tempfile
import resume.ingest as ingest

def test_ingest_pdf(tmp_path):
    src = "/home/vg/opensource/JobSailor/resume/vaibhav_gauraha_7987458402.pdf"
    meta = ingest.ingest(src)
    assert os.path.exists(ingest.BASE_MD)
    assert os.path.exists(ingest.BASE_META)
    assert os.path.exists(ingest.ACTIVE_JSON)
    assert meta["chars"] > 1000
    assert len(meta["sha"]) == 12

def test_ingest_unsupported(tmp_path):
    try:
        ingest.ingest("/tmp/x.odt")
        assert False
    except ValueError as e:
        assert "unsupported" in str(e)

def test_needs_ocr():
    assert ingest._needs_ocr("") is True
    assert ingest._needs_ocr("   ") is True
    assert ingest._needs_ocr("a " * 10) is True
    assert ingest._needs_ocr("word " * 100) is False

def test_normalize_empty():
    md = ingest._normalize_to_md("", "x.pdf")
    assert "empty" in md.lower()
