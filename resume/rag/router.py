import re
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any


class RouteTarget(str, Enum):
    SINGLE_DOC = "SINGLE_DOC"
    MULTI_DOC = "MULTI_DOC"


@dataclass
class RouteDecision:
    target: RouteTarget
    confidence: float
    rewritten_query: str
    target_key: Optional[str] = None
    domain: str = "resume"
    reason: str = ""


_PROFILE_KEYS = {
    "phone": ["phone","mobile","contact number","telephone"],
    "email": ["email","mail"],
    "name": ["your name","candidate name"],
    "expected_ctc": ["expected ctc","expected salary","expect ctc","expect salary"],
    "current_ctc": ["current ctc","current salary","salary","compensation"],
    "notice_period": ["notice period","notice", "joining"],
    "experience": ["total experience","years of experience","total years"],
    "location": ["current location","located","where are you","city","location preference","preferred location"],
    "work_authorization": ["work authorization","authorized to work","visa","sponsorship","citizen"],
    "qualification": ["qualification","degree","education","highest qualification"],
    "skills": ["skills","tech stack","technologies"],
}

_MULTI_HINTS = ["how many","list all","summarize","compare","gap","tailor","match","analyze","what are all","count","why","explain","describe a time","tell me about"]

_REPORT_HINTS = ["applied","skipped","failed","report","run","visit","status","job type","applied rate","application","applications","succeed","success","failure","failures"]

_JD_HINT = 2000


def _normalize(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower())


def _is_jd_query(q: str) -> bool:
    low = _normalize(q)
    if "job description" in low or "job title" in low or "position overview" in low:
        return True
    if any(h in low for h in ["is this in my resume", "is this in m yresume", "in my resume", "match this jd", "match my resume", "fit for this role", "can i apply"]):
        if len(q) > 60:
            return True
    if any(h in low for h in ["qualifications & requirements", "qualifications and requirements", "minimum qualifications", "professional qualifications"]):
        return True
    if any(h in low for h in ["contract to hire", "interview mode", "key responsibility", "position overview", "years of industry experience"]):
        return True
    if ("responsibilities" in low or "requirements" in low) and len(q) > 140:
        return True
    if len(q) > 350 and ("skills" in low or "experience" in low or "qualification" in low or "requirements" in low):
        return True
    return False


def _detect_domain(q: str) -> str:
    low = _normalize(q)
    if _is_jd_query(q):
        return "jd"
    if any(k in low for k in _REPORT_HINTS):
        return "reports"
    if len(q) > _JD_HINT and any(w in low for w in ["requirements","responsibilities","qualifications","job description"]):
        return "jd"
    if any(k in low for k in ["chunk","bullet","achievement","metric"]):
        return "chunks"
    if any(k in low for k in ["ctc","notice","phone","email","location","authorization","qualification"]):
        if "skills" in low and any(h in low for h in _MULTI_HINTS):
            return "resume"
        return "profile"
    return "resume"


def _is_single_doc(q: str) -> tuple[bool, str | None]:
    if _is_jd_query(q):
        return False, None
    low = _normalize(q)
    if any(h in low for h in _MULTI_HINTS):
        if "ctc" in low or "notice" in low or "location" in low:
            pass
        else:
            return False, None
    for key, syns in _PROFILE_KEYS.items():
        for s in syns:
            if s in low and len(low) < 80:
                return True, key
    if re.search(r"https?://", q):
        return True, "url"
    if re.match(r"^\s*(what is|give me|tell me)?\s*(my|your)?\s*(phone|email|name|ctc|notice|location|skills|qualification).*?\??\s*$", low):
        if len(low.split()) <= 6:
            return True, "profile_field"
    return False, None


def _is_multi_doc(q: str) -> bool:
    if _is_jd_query(q):
        return True
    low = _normalize(q)
    if any(h in low for h in _MULTI_HINTS):
        return True
    if len(q.split()) > 18:
        return True
    if "?" in q and len(q) > 80:
        return True
    return False


def _gemini_fallback(q: str) -> Optional[RouteDecision]:
    try:
        from gemini_api import bard_flash_response
        prompt = f'Classify as SINGLE_DOC (1 doc lookup, atomic fact) or MULTI_DOC (needs retrieval across many chunks). Reply ONLY one label.\nQuestion: {q}'
        ans = bard_flash_response(prompt, timeout=5)
        if ans:
            t = ans.strip().upper()
            if "SINGLE" in t:
                return RouteDecision(target=RouteTarget.SINGLE_DOC, confidence=0.6, rewritten_query=q.strip(), domain=_detect_domain(q), reason="gemini_fallback_single")
            if "MULTI" in t:
                return RouteDecision(target=RouteTarget.MULTI_DOC, confidence=0.6, rewritten_query=q.strip(), domain=_detect_domain(q), reason="gemini_fallback_multi")
    except Exception:
        pass
    return None


def classify_query(query: str, context: Optional[Dict[str, Any]] = None) -> RouteDecision:
    q = (query or "").strip()
    if not q:
        return RouteDecision(target=RouteTarget.SINGLE_DOC, confidence=1.0, rewritten_query=q, reason="empty")
    
    if _is_jd_query(q):
        return RouteDecision(target=RouteTarget.MULTI_DOC, confidence=0.95, rewritten_query=q, domain="jd", reason="jd_match_query")

    if len(q) > _JD_HINT:
        hybrid = (q[:1200] + " ... " + q[-800:]) if len(q) > 2000 else q
        reason = "long_jd_paste_hybrid" if len(q) > 2000 else "long_jd_paste"
        return RouteDecision(target=RouteTarget.MULTI_DOC, confidence=0.9, rewritten_query=hybrid, domain="jd", reason=reason)

    is_single, key = _is_single_doc(q)
    is_multi = _is_multi_doc(q)
    domain = _detect_domain(q)

    if is_multi:
        return RouteDecision(target=RouteTarget.MULTI_DOC, confidence=0.88, rewritten_query=q, target_key=key if is_single else None, domain=domain, reason="rule_multi_hint")
    if is_single and not is_multi:
        return RouteDecision(target=RouteTarget.SINGLE_DOC, confidence=0.92, rewritten_query=q, target_key=key, domain=domain, reason=f"rule_single:{key}")
    fb = _gemini_fallback(q)
    if fb:
        return fb
    return RouteDecision(target=RouteTarget.MULTI_DOC, confidence=0.55, rewritten_query=q, target_key=key, domain=domain, reason="default_multi")
