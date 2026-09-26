import pytest
from web.routes_credentials import _extract_facts_pytesseract

def test_extract_facts_candidate_a():
    resume_text = """
    Dr. Sarah Connor, Ph.D.
    Email: sarah.connor@cyberdyne.io | Phone: +1-415-555-2671 | Location: San Francisco, CA
    GitHub: github.com/sconnor | LinkedIn: linkedin.com/in/sconnor

    PROFESSIONAL SUMMARY
    Senior Machine Learning Scientist with 6+ years of experience building production AI systems.

    TECHNICAL SKILLS
    Languages & Frameworks: Python, PyTorch, C++, CUDA, Triton, Jax
    Infrastructure: Docker, Kubernetes, AWS, Terraform, CI/CD, Git

    EDUCATION
    Doctor of Philosophy in Computer Science - Stanford University (2018)
    Bachelor of Science in Electrical Engineering - MIT (2014)

    EXPERIENCE
    Lead AI Researcher | OpenAI | 2021 - Present
    """
    facts = _extract_facts_pytesseract(resume_text)
    assert facts.get("name") == "Sarah Connor"
    assert facts.get("email") == "sarah.connor@cyberdyne.io"
    assert "4155552671" in facts.get("phone", "")
    assert "San Francisco" in facts.get("current_location", "")
    assert facts.get("highest_qualification") == "PhD"
    assert facts.get("institution") == "Stanford University"
    assert facts.get("total_experience_years") == 6
    assert facts.get("relevant_experience_years") == 6
    assert "PyTorch" in facts.get("skills", "")

def test_extract_facts_candidate_b():
    resume_text = """
    RAJESH KUMAR
    Senior Java Backend Developer
    rajesh.kumar99@gmail.com | +91 9876543210 | Bengaluru, Karnataka

    SUMMARY
    Backend Engineer with 4 years experience in microservices and distributed systems.

    SKILLS
    Java, Spring Boot, Microservices, PostgreSQL, Kafka, Redis, Docker, Kubernetes, AWS

    EDUCATION
    B.Tech in Computer Science and Engineering
    National Institute of Technology Surathkal
    """
    facts = _extract_facts_pytesseract(resume_text)
    assert facts.get("name") == "Rajesh Kumar"
    assert facts.get("email") == "rajesh.kumar99@gmail.com"
    assert facts.get("phone") == "9876543210"
    assert "Bengaluru" in facts.get("current_location", "")
    assert facts.get("highest_qualification") == "BTech"
    assert "National Institute of Technology" in facts.get("institution", "")
    assert facts.get("total_experience_years") == 4
    assert "Java" in facts.get("skills", "")

def test_extract_facts_candidate_c():
    resume_text = """
    ALEX CHEN (Senior DevOps Engineer)
    alex.chen@cloudtech.org
    Phone: (555) 345-6789
    City: Seattle, WA

    EXPERTISE & SKILLS
    Cloud: GCP, AWS, Azure
    Tools: Kubernetes, Docker, Helm, ArgoCD, Terraform, Prometheus

    EDUCATION
    Master of Computer Applications - University of Washington
    """
    facts = _extract_facts_pytesseract(resume_text)
    assert facts.get("name") == "Alex Chen"
    assert facts.get("email") == "alex.chen@cloudtech.org"
    assert "3456789" in facts.get("phone", "")
    assert "Seattle" in facts.get("current_location", "")
    assert facts.get("highest_qualification") == "MCA"
    assert "University of Washington" in facts.get("institution", "")
    assert "Kubernetes" in facts.get("skills", "")

def test_extract_facts_telecom_sales_manager():
    resume_text = """
    SNAPSHOT: Results-driven Jio Centre Manager with 19+ years of experience in Telecom Sales, P&L Ownership, and Large-Team Leadership.

    CORE COMPETENCY
    P&L Management & Revenue Growth (+80 LPM)
    Channel Partner Development (PLI & Retail)
    Customer Acquisition (Fiber/AirFiber) & Retention (Churn Reduction)

    AREAS OF EXPERTISE
    Sales and Marketing/ Business Development
    Distribution Management

    CAREER SCAN
    2022 to Till Date – Jio Center Manager – Reliance Jio Infocom Ltd.
    Aug 17 to 2022 - Zonal Sales Manager - Bharti Airtel Ltd.

    EXTRAMURAL ENGAGEMENTS
    Academic:
    MA In Sanskrit ( full time)from Ravishankar University (2003-2005)
    BA classic (full time) from Ravishankar University (2000-2003)

    Personal Details
    Contact Address : A-2, 501, Star Altair, Bhugaon, Pune, Maharashtra
    Date of Birth : 28th Oct 1980

    Place: Pune
    Date:                                                                               Awnish Sharma
    """
    facts = _extract_facts_pytesseract(resume_text, filename="Resume_Awnish sharma_updated.docx")
    assert "Awnish" in facts.get("name", "")
    assert facts.get("highest_qualification") == "MA"
    assert "Ravishankar University" in facts.get("institution", "")
    assert facts.get("total_experience_years") == 19
    assert "Pune" in facts.get("current_location", "")
    assert "P&L Management" in facts.get("skills", "")
    assert "Personal Details" not in facts.get("skills", "")

