from resume.jd import extract_jd, has_surface

class FakeEl:
    def __init__(self, text=""): self.text=text
class FakeDriver:
    def __init__(self, els=None, body=""):
        self._els=els or {}
        self._body=body
        self.page_source=body
    def find_elements(self, by, xp):
        return self._els.get(xp, [])
    def find_element(self, by, xp):
        if xp=="body":
            return FakeEl(self._body)
        raise Exception("not found")

def test_extract_jd_primary():
    d=FakeDriver(els={"//div[contains(@class,'styles_JDC__dang-inner-html')]":[FakeEl("x"*200)]})
    assert len(extract_jd(d))>=200

def test_extract_jd_fallback_body():
    d=FakeDriver(body="body text fallback "*20)
    assert len(extract_jd(d))>0

def test_has_surface_none():
    d=FakeDriver(els={})
    assert has_surface(d)=="none"

def test_has_surface_chat():
    d=FakeDriver(els={"//ul[contains(@id,'chatList_')]":[FakeEl()], "[class*='form-field'], [class*='formField'], [class*='styles_form-box']":[]})
    assert has_surface(d)=="chat_widget"

def test_has_surface_both():
    d=FakeDriver(els={"//ul[contains(@id,'chatList_')]":[FakeEl()], "[class*='form-field'], [class*='formField'], [class*='styles_form-box']":[FakeEl()]})
    assert has_surface(d)=="both"
