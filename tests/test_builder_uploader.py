import os
from resume.builder import md_to_pdf

def test_md_to_pdf(tmp_path):
    md = tmp_path/"x.md"
    md.write_text("# Title\n\nHello world\n\n- bullet")
    pdf = tmp_path/"x.pdf"
    md_to_pdf(str(md), str(pdf))
    assert pdf.exists()
    assert pdf.stat().st_size > 500

def test_uploader_no_input(tmp_path):
    from resume.uploader import upload_to_naukri
    pdf = tmp_path/"r.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    class FakeDriver:
        def get(self,u): pass
        def find_elements(self,*a,**k): return []
        def find_element(self,*a,**k): raise Exception("no")
        def save_screenshot(self,p): open(p,"wb").write(b"fake")
        @property
        def page_source(self): return ""
    ok, info = upload_to_naukri(FakeDriver(), str(pdf), timeout=1)
    assert ok is False
    assert info["step"] in ("find_input","outer")

def test_uploader_send_keys(tmp_path):
    from resume.uploader import upload_to_naukri
    pdf = tmp_path/"r.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    class FakeInput:
        def get_attribute(self,a): return "<input type=file>"
        def is_displayed(self): return True
        def send_keys(self,p): assert p.endswith(".pdf")
    class FakeDriver:
        def get(self,u): pass
        def find_elements(self,by,xp):
            if "input" in xp: return [FakeInput()]
            return []
        @property
        def page_source(self): return "successfully uploaded"
    ok, _ = upload_to_naukri(FakeDriver(), str(pdf), timeout=1)
    assert ok is True

def test_uploader_large_file(tmp_path):
    from resume.uploader import upload_to_naukri
    pdf = tmp_path/"big.pdf"
    pdf.write_bytes(b"x"*(2*1024*1024+1))
    class FakeDriver:
        def get(self,u): pass
        @property
        def page_source(self): return ""
    ok, info = upload_to_naukri(FakeDriver(), str(pdf), timeout=1)
    assert ok is False
    assert info["error"]=="file_too_large"
