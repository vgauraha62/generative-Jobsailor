import re
import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class ChildChunk:
    chunk_id: str
    parent_id: str
    user_id: int
    category: str
    content: str
    company: Optional[str] = None
    role: Optional[str] = None
    temporal_span: Optional[str] = None
    metrics: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)


@dataclass
class ParentChunk:
    parent_id: str
    user_id: int
    category: str
    title: str
    content: str
    children: List[ChildChunk] = field(default_factory=list)
    company: Optional[str] = None
    role: Optional[str] = None
    temporal_span: Optional[str] = None
    metrics: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)


_METRIC_RE = re.compile(r"(\d+\s*%|\d+\s*x|\d+\.?\d*\s*ms|\d+\s*GB|₹\s*\d+|LPM|\d+k|\d+,\d+)", re.I)
_TEMPORAL_RE = re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}\s*[–\-]\s*(?:Present|\d{4}|[A-Za-z]+\s+\d{4})", re.I)
_SKILL_HINTS = ["python","rag","llm","pytorch","docker","aws","gcp","langgraph","chromadb","pinecone","triton","cuda","c++","prompt"]

_CATEGORY_MAP = {
    "experience": "work_experience",
    "work": "work_experience",
    "education": "education",
    "project": "project",
    "skill": "skills",
    "open source": "project",
    "grant": "work_experience",
    "compliance": "work_experience",
}

_JOB_SPLIT_RE = re.compile(r"(?=^(?:AI Engineer|AI\/ML Developer|Data Scientist|Open Source|Education|Compliance Binding|Grant Management|LLM as a Judge)[\s,]*.*(?:\d{4}|Present))", re.M)


def _detect_category(title: str, body: str) -> str:
    low = title.lower()
    for k, v in _CATEGORY_MAP.items():
        if k in low:
            return v
    if any(w in low for w in ["engineer","developer","labs","inc"]):
        return "work_experience"
    if "education" in body.lower()[:500] or "year" in body.lower()[:500] and "percentage" in body.lower()[:800]:
        return "education"
    return "general"


def _extract_metrics(text: str) -> List[str]:
    return [m.strip() for m in _METRIC_RE.findall(text)][:6]


def _extract_temporal(text: str) -> Optional[str]:
    m = _TEMPORAL_RE.search(text)
    return m.group(0).strip() if m else None


def _extract_company_role(title: str):
    parts = re.split(r",|\s*-\s*", title)
    company = parts[1].strip() if len(parts) > 1 else None
    role = parts[0].strip() if parts else title
    if len(role) > 80:
        role = role[:80]
    return company, role


def _split_bullets(text: str) -> List[str]:
    bullets = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s[0] in "•-·*":
            bullets.append(s.lstrip("•-·* ").strip())
        elif len(s) > 40:
            bullets.append(s)
    return bullets


def _section_split(md_text: str) -> List[str]:
    hsplit = re.split(r"(?m)^#{1,3}\s+", md_text)
    if len(hsplit) > 2:
        return [s for s in hsplit if s.strip()]
    jobs = _JOB_SPLIT_RE.split(md_text)
    if len(jobs) > 1:
        return [j.strip() for j in jobs if j.strip()]
    return [md_text]


def chunk_resume(md_text: str, user_id: int) -> List[ParentChunk]:
    md_text = md_text.strip()
    if not md_text:
        return []
    sections = _section_split(md_text)
    parents: List[ParentChunk] = []
    for idx, sec in enumerate(sections):
        if not sec.strip():
            continue
        lines = sec.splitlines()
        title = lines[0].strip()[:120] if lines else f"section_{idx}"
        body = "\n".join(lines[1:]) if len(lines) > 1 else sec
        cat = _detect_category(title, body)
        temporal = _extract_temporal(title + " " + body[:400])
        company, role = _extract_company_role(title)
        metrics = _extract_metrics(body)
        skills = [s for s in _SKILL_HINTS if s.lower() in body.lower()][:8]
        pid_raw = f"{user_id}_{cat}_{title}_{idx}"
        parent_id = f"usr_{user_id}_{cat}_{hashlib.sha256(pid_raw.encode()).hexdigest()[:8]}"
        bullets = _split_bullets(body)
        if not bullets:
            bullets = [body.strip()[:2000]]
        parent_content = f"{title}\n{body.strip()[:8000]}"
        pc = ParentChunk(
            parent_id=parent_id, user_id=user_id, category=cat, title=title,
            content=parent_content, company=company, role=role,
            temporal_span=temporal, metrics=metrics, skills=skills,
        )
        for bidx, bullet in enumerate(bullets):
            if not bullet.strip():
                continue
            cid_raw = f"{parent_id}_{bidx}_{bullet[:40]}"
            cid = f"{parent_id}_{hashlib.sha256(cid_raw.encode()).hexdigest()[:6]}"
            b_metrics = _extract_metrics(bullet)
            b_skills = [s for s in skills if s.lower() in bullet.lower()]
            pc.children.append(ChildChunk(
                chunk_id=cid, parent_id=parent_id, user_id=user_id,
                category=cat, content=bullet.strip()[:1200],
                company=company, role=role, temporal_span=temporal,
                metrics=b_metrics, skills=b_skills,
            ))
        parents.append(pc)
    if not parents:
        pid = f"usr_{user_id}_general_{hashlib.sha256(md_text[:100].encode()).hexdigest()[:8]}"
        pc = ParentChunk(parent_id=pid, user_id=user_id, category="general", title="Resume", content=md_text[:8000])
        pc.children.append(ChildChunk(chunk_id=f"{pid}_0", parent_id=pid, user_id=user_id, category="general", content=md_text[:1200]))
        parents.append(pc)
    return parents


def chunks_to_records(parents: List[ParentChunk]) -> List[dict]:
    recs = []
    for p in parents:
        recs.append({
            "chunk_id": p.parent_id, "parent_id": None, "user_id": p.user_id,
            "category": p.category, "content": p.content, "title": p.title,
            "company": p.company, "role": p.role, "temporal_span": p.temporal_span,
            "metrics": json.dumps(p.metrics), "skills": json.dumps(p.skills),
            "is_parent": 1,
        })
        for c in p.children:
            recs.append({
                "chunk_id": c.chunk_id, "parent_id": c.parent_id, "user_id": c.user_id,
                "category": c.category, "content": c.content, "title": "",
                "company": c.company, "role": c.role, "temporal_span": c.temporal_span,
                "metrics": json.dumps(c.metrics), "skills": json.dumps(c.skills),
                "is_parent": 0,
            })
    return recs
