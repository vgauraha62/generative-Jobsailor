import json
import zipfile
import io
import pytest

from tests.conftest import make_client, reset_user, drop_user
from web.per_user import shard, shard_reports

UID_ALICE = 101
UID_BOB = 102


@pytest.fixture(autouse=True)
def clean_isolated_users():
    """Ensure clean shards and DB state before and after each test."""
    reset_user(UID_ALICE, "alice@iso.com", "Alice")
    reset_user(UID_BOB, "bob@iso.com", "Bob")
    yield
    drop_user(UID_ALICE)
    drop_user(UID_BOB)


def test_credentials_and_profile_isolation():
    """Verify credentials and candidate profiles are strictly isolated per user."""
    alice_client = make_client(UID_ALICE)
    bob_client = make_client(UID_BOB)

    # 1. Alice saves credentials
    alice_payload = {
        "profile": {
            "resume_facts": {
                "name": "Alice Wonderland",
                "email": "alice@iso.com",
                "phone": "9111111111",
                "skills": "Rust, Distributed Systems, Raft",
                "highest_qualification": "PhD",
                "institution": "MIT",
                "total_experience_years": 8,
                "relevant_experience_years": 8,
                "current_location": "Boston, MA"
            },
            "user_preferences": {
                "current_ctc_lpa": 35.0,
                "expected_ctc_lpa": 50.0,
                "notice_period_days": 60,
                "willing_to_relocate": True
            }
        },
        "slugs": ["rust-developer", "distributed-systems"],
        "gemini_key": "SECRET_KEY_ALICE_12345"
    }
    res = alice_client.post("/api/credentials", json=alice_payload)
    assert res.status_code == 200

    # 2. Bob requests credentials - MUST NOT see Alice's data
    res_bob = bob_client.get("/api/credentials")
    assert res_bob.status_code == 200
    bob_profile = res_bob.json()["profile"]
    assert bob_profile["resume_facts"]["name"] == "NEEDS_REVIEW"
    assert bob_profile["resume_facts"]["skills"] == "NEEDS_REVIEW"
    assert bob_profile["user_preferences"]["current_ctc_lpa"] == "NEEDS_REVIEW"
    assert res_bob.json()["config"]["search"]["slugs"] == []
    assert not (shard(UID_BOB) / ".env.gemini").exists()

    # 3. Bob saves his own credentials
    bob_payload = {
        "profile": {
            "resume_facts": {
                "name": "Bob Builder",
                "email": "bob@iso.com",
                "phone": "9222222222",
                "skills": "React, TypeScript, CSS",
                "highest_qualification": "BTech",
                "institution": "IIT Delhi",
                "total_experience_years": 3,
                "relevant_experience_years": 3,
                "current_location": "New Delhi"
            },
            "user_preferences": {
                "current_ctc_lpa": 12.0,
                "expected_ctc_lpa": 18.0,
                "notice_period_days": 15,
                "willing_to_relocate": False
            }
        },
        "slugs": ["frontend-developer"],
        "gemini_key": "SECRET_KEY_BOB_99999"
    }
    res = bob_client.post("/api/credentials", json=bob_payload)
    assert res.status_code == 200

    # 4. Verify Alice still has her original profile and keys intact
    res_alice = alice_client.get("/api/credentials")
    assert res_alice.status_code == 200
    a_prof = res_alice.json()["profile"]
    assert a_prof["resume_facts"]["name"] == "Alice Wonderland"
    assert a_prof["resume_facts"]["skills"] == "Rust, Distributed Systems, Raft"
    assert a_prof["user_preferences"]["current_ctc_lpa"] == 35.0
    assert res_alice.json()["config"]["search"]["slugs"] == ["rust-developer", "distributed-systems"]
    assert "SECRET_KEY_ALICE_12345" in (shard(UID_ALICE) / ".env.gemini").read_text()
    assert "SECRET_KEY_BOB_99999" in (shard(UID_BOB) / ".env.gemini").read_text()


def test_resume_upload_and_facts_isolation():
    """Verify resume uploads are isolated and completely overwrite only the uploader's facts."""
    alice_client = make_client(UID_ALICE)
    bob_client = make_client(UID_BOB)

    # Alice uploads ML Scientist resume
    alice_resume = """
    DR. ALICE WONDER
    Email: alice.wonder@ai-labs.org | Phone: +1-617-555-0199 | Boston, MA
    
    TECHNICAL SKILLS
    Python, PyTorch, CUDA, Transformers, Jax, Triton
    
    EDUCATION
    Doctor of Philosophy in Computer Science - Harvard University
    """
    res_a = alice_client.post("/api/credentials/resume", files={"file": ("alice_cv.txt", alice_resume.encode("utf-8"), "text/plain")})
    assert res_a.status_code == 200
    facts_a = res_a.json()["merged"]["resume_facts"]
    assert facts_a["name"] == "Alice Wonder"
    assert facts_a["highest_qualification"] == "PhD"
    assert "Harvard University" in facts_a["institution"]

    # Bob uploads DevOps resume
    bob_resume = """
    BOB THE CONSTRUCTOR
    Email: bob.constructor@devops.net | Phone: +91 9888877777 | Hyderabad, Telangana
    
    SKILLS
    Kubernetes, Terraform, AWS, Docker, Linux, CI/CD
    
    EDUCATION
    Bachelor of Technology in Information Technology
    Indian Institute of Technology Hyderabad
    """
    res_b = bob_client.post("/api/credentials/resume", files={"file": ("bob_cv.txt", bob_resume.encode("utf-8"), "text/plain")})
    assert res_b.status_code == 200
    facts_b = res_b.json()["merged"]["resume_facts"]
    assert facts_b["name"] == "Bob The Constructor"
    assert facts_b["highest_qualification"] == "BTech"
    assert "IIT" in facts_b["institution"] or "Indian Institute of Technology" in facts_b["institution"]

    # Verify physical file shards
    alice_shard_facts = json.loads((shard(UID_ALICE) / "candidate_profile.json").read_text())["resume_facts"]
    bob_shard_facts = json.loads((shard(UID_BOB) / "candidate_profile.json").read_text())["resume_facts"]

    assert alice_shard_facts["name"] == "Alice Wonder"
    assert "PyTorch" in alice_shard_facts["skills"]
    assert "Bob" not in str(alice_shard_facts)

    assert bob_shard_facts["name"] == "Bob The Constructor"
    assert "Kubernetes" in bob_shard_facts["skills"]
    assert "Alice" not in str(bob_shard_facts)


def test_dashboard_status_and_ledger_isolation():
    """Verify visited jobs, daily counts, and dashboard summary never leak across users."""
    alice_client = make_client(UID_ALICE)
    bob_client = make_client(UID_BOB)

    # Set up Alice visited jobs
    alice_visited = {
        "job_hash_111": {"status": "applied", "applied_at": "2026-08-31T09:00:00", "title": "Senior AI Engineer", "company": "OpenAI"},
        "job_hash_222": {"status": "skipped", "skipped_at": "2026-08-31T09:15:00", "title": "Staff ML Researcher", "company": "Anthropic"}
    }
    (shard(UID_ALICE) / "visited.json").write_text(json.dumps(alice_visited))

    # Set up Bob visited jobs (empty or distinct)
    bob_visited = {
        "job_hash_333": {"status": "applied", "applied_at": "2026-08-31T09:30:00", "title": "DevOps Architect", "company": "Stripe"}
    }
    (shard(UID_BOB) / "visited.json").write_text(json.dumps(bob_visited))

    # Check Alice's status
    res_a = alice_client.get("/api/status")
    assert res_a.status_code == 200
    by_status_a = res_a.json()["ledger"]["by_status"]
    assert by_status_a.get("applied") == 1
    assert by_status_a.get("skipped") == 1

    # Check Bob's status
    res_b = bob_client.get("/api/status")
    assert res_b.status_code == 200
    by_status_b = res_b.json()["ledger"]["by_status"]
    assert by_status_b.get("applied") == 1
    assert by_status_b.get("skipped", 0) == 0


def test_screenshot_and_reports_isolation():
    """Verify screenshots and reports in one user's directory cannot be accessed by another user."""
    alice_client = make_client(UID_ALICE)
    bob_client = make_client(UID_BOB)

    # Create dummy screenshots in respective shard reports
    alice_png = shard_reports(UID_ALICE) / "visit_alice_screenshot_101.png"
    alice_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"A" * 2048)

    bob_png = shard_reports(UID_BOB) / "visit_bob_screenshot_102.png"
    bob_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"B" * 2048)

    # 1. Alice lists screenshots -> sees ONLY Alice's file
    res_a = alice_client.get("/api/screenshots")
    assert res_a.status_code == 200
    items_a = [item["file"] for item in res_a.json()["items"]]
    assert "visit_alice_screenshot_101.png" in items_a
    assert "visit_bob_screenshot_102.png" not in items_a

    # 2. Bob lists screenshots -> sees ONLY Bob's file
    res_b = bob_client.get("/api/screenshots")
    assert res_b.status_code == 200
    items_b = [item["file"] for item in res_b.json()["items"]]
    assert "visit_bob_screenshot_102.png" in items_b
    assert "visit_alice_screenshot_101.png" not in items_b

    # 3. Bob attempts to access Alice's screenshot directly -> MUST return 404
    res_cross = bob_client.get("/api/screenshots/file/visit_alice_screenshot_101.png")
    assert res_cross.status_code == 404

    # 4. Alice accesses her own screenshot -> 200 OK
    res_own = alice_client.get("/api/screenshots/file/visit_alice_screenshot_101.png")
    assert res_own.status_code == 200


def test_run_state_and_lock_isolation():
    """Verify a running automation job lock on User A does not mark User B as running."""
    alice_client = make_client(UID_ALICE)
    bob_client = make_client(UID_BOB)

    # Put a running lock in Alice's reports directory
    alice_lock = shard_reports(UID_ALICE) / "run.lock"
    alice_lock.write_text(json.dumps({"running": True, "run_id": "alice_active_run_999", "live": True}))

    # Alice status reports running
    res_a = alice_client.get("/api/status")
    assert res_a.status_code == 200
    assert res_a.json()["run_state"]["running"] is True
    assert res_a.json()["run_state"]["run_id"] == "alice_active_run_999"

    # Bob status MUST report running is False
    res_b = bob_client.get("/api/status")
    assert res_b.status_code == 200
    assert res_b.json()["run_state"]["running"] is False
    assert res_b.json()["run_state"].get("run_id") is None


def test_export_data_isolation():
    """Verify data export generates a zip strictly containing the requester's data and 0 cross-user files."""
    alice_client = make_client(UID_ALICE)
    bob_client = make_client(UID_BOB)

    # Populate Alice and Bob shards with distinct files
    (shard(UID_ALICE) / "candidate_profile.json").write_text(json.dumps({"name": "Alice Wonderland"}))
    (shard_reports(UID_ALICE) / "visit_alice_01.json").write_text(json.dumps({"job": "AI Engineer Alice"}))

    (shard(UID_BOB) / "candidate_profile.json").write_text(json.dumps({"name": "Bob Builder"}))
    (shard_reports(UID_BOB) / "visit_bob_01.json").write_text(json.dumps({"job": "DevOps Engineer Bob"}))

    # Alice exports
    res_a = alice_client.get("/api/export")
    assert res_a.status_code == 200
    zip_a = zipfile.ZipFile(io.BytesIO(res_a.content))
    namelist_a = zip_a.namelist()
    assert "user.json" in namelist_a
    user_a = json.loads(zip_a.read("user.json"))
    assert user_a["email"] == "alice@iso.com"
    assert "password_hash" not in user_a  # Password hash stripped

    all_text_a = "".join(zip_a.read(name).decode("utf-8", errors="ignore") for name in namelist_a)
    assert "Alice" in all_text_a
    assert "Bob" not in all_text_a

    # Bob exports
    res_b = bob_client.get("/api/export")
    assert res_b.status_code == 200
    zip_b = zipfile.ZipFile(io.BytesIO(res_b.content))
    namelist_b = zip_b.namelist()
    assert "user.json" in namelist_b
    user_b = json.loads(zip_b.read("user.json"))
    assert user_b["email"] == "bob@iso.com"

    all_text_b = "".join(zip_b.read(name).decode("utf-8", errors="ignore") for name in namelist_b)
    assert "Bob" in all_text_b
    assert "Alice" not in all_text_b
