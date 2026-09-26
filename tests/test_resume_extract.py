import pytest

from tests.conftest import make_client, reset_user, drop_user
from web.routes_credentials import _extract_facts_pytesseract as fx

UID = 106

HEADER = """ACME SOLUTIONS PVT LTD
Priya Nair
priya.nair@example.com | +91 98765 43210 | Pune
PROFESSIONAL SUMMARY
Software Engineer with 4 years experience.
EXPERIENCE
References: Rahul Menon
EDUCATION
Bachelor of Technology - College of Engineering Pune
"""


def test_name_proximity_beats_company_line():
    f = fx(HEADER)
    assert f["name"] == "Priya Nair"
    assert f["email"] == "priya.nair@example.com"
    assert f["phone"] == "9876543210"


def test_obfuscated_email_and_split_phone():
    raw = "Priya Nair\npriya [at] example [dot] com\nCall: 98765\n43210\n"
    f = fx(raw)
    assert f["email"] == "priya@example.com"
    assert f["phone"] == "9876543210"


def test_contact_below_name():
    raw = "priya.nair@example.com\n+91-9876543210\nPriya Nair\n"
    f = fx(raw)
    assert f["name"] == "Priya Nair"


@pytest.fixture()
def client106():
    reset_user(UID, "finn@merge.com", "Finn")
    yield make_client(UID)
    drop_user(UID)


def test_reupload_clears_stale_phone(client106):
    prof = {"resume_facts": {"name": "Finn", "email": "f@x.com", "phone": "9112233445", "highest_qualification": "NEEDS_REVIEW", "institution": "NEEDS_REVIEW", "total_experience_years": "NEEDS_REVIEW", "relevant_experience_years": "NEEDS_REVIEW", "current_location": "NEEDS_REVIEW", "skills": "NEEDS_REVIEW"},
            "user_preferences": {"current_ctc_lpa": "NEEDS_REVIEW", "expected_ctc_lpa": "NEEDS_REVIEW", "notice_period_days": "NEEDS_REVIEW", "willing_to_relocate": False, "work_authorization": "NEEDS_REVIEW", "passport_valid": False}}
    assert client106.post("/api/credentials", json={"slugs": [], "profile": prof}).status_code == 200
    up = client106.post("/api/credentials/resume", files={"file": ("cv.txt", b"Finn\nf@x.com\n", "text/plain")})
    assert up.status_code == 200
    reread = client106.get("/api/credentials").json()["profile"]
    assert reread["resume_facts"]["phone"] in (None, "", "NEEDS_REVIEW")  # stale value cleared
    assert reread["resume_facts"]["name"] == "Finn"


def test_ocr_page_reads_rendered_text(tmp_path):
    import pymupdf
    from resume.ingest import ocr_page
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 120), "Priya Nair", fontsize=28)
    page.insert_text((72, 160), "priya@example.com", fontsize=18)
    pdf = str(tmp_path / "hdr.pdf")
    doc.save(pdf)
    text = ocr_page(pdf)
    assert "priya" in text.lower()


DECOY_PERSONAL = """Awnish Sharma
awnish.sharma@example.com | 98110 22334 | Bengaluru
PROFESSIONAL SUMMARY
Backend engineer.
PERSONAL DETAILS
Father: Rajesh Sharma
Mother: Sunita Sharma
Marital Status: Married
DECLARATION
I hereby declare the above is true.
Date: 2026-01-01
Sunita Sharma
"""


def test_decoy_relative_in_personal_details():
    f = fx(DECOY_PERSONAL)
    assert f["name"] == "Awnish Sharma"


DECOY_REF = """Awnish Sharma
PROFESSIONAL SUMMARY
REFERENCES
Rahul Verma
Contact: 98110 22334 awnish.sharma@example.com
Sunita Sharma
"""


def test_decoy_in_references():
    f = fx(DECOY_REF)
    assert f["name"] == "Awnish Sharma"
    assert f["phone"] == "9811022334"


def test_second_resume_resets_identity(client106):
    a = client106.post("/api/credentials/resume", files={"file": ("a.txt", b"Awnish Sharma\nawnish@example.com\n98110 22334\n", "text/plain")})
    assert a.status_code == 200
    assert a.json()["merged"]["resume_facts"]["name"] == "Awnish Sharma"
    b = client106.post("/api/credentials/resume", files={"file": ("b.txt", b"Priya Nair\npriya@example.com\n", "text/plain")})
    bj = b.json()
    assert bj["merged"]["resume_facts"]["name"] == "Priya Nair"
    assert bj["merged"]["resume_facts"]["email"] == "priya@example.com"
    assert bj["merged"]["resume_facts"]["phone"] in (None, "", "NEEDS_REVIEW")  # no Awnish residue
