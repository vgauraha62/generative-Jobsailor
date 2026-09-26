import re
from typing import List, Dict, Any, Optional


_NUM_RE = re.compile(r"(\d+(?:\.\d+)?\s*%|\b\d{4}\s*[-–]\s*(?:Present|\d{4})\b|₹\s*\d+|\b\d+\s*(?:years|months|days|LPM|GB|ms)\b)", re.I)
_PROPER_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b")


def _extract_facts(text: str) -> dict:
    nums = set(m.strip().lower() for m in _NUM_RE.findall(text))
    props = set(m.strip() for m in _PROPER_RE.findall(text))
    return {"nums": nums, "props": props, "lower": text.lower()}


def _norm(s: str) -> str:
    return re.sub(r"[^\w\s]", " ", s.lower()).strip()

def verify_answer(answer: str, retrieved: List[dict]) -> dict:
    if not answer or not answer.strip():
        return {"verified": False, "reason": "empty_answer", "needs_review": True}
    if answer and ("matched:" in answer.lower() and "missing:" in answer.lower()):
        return {"verified": True, "reason": "structured_json_reasoning", "needs_review": False}
    if not retrieved:
        return {"verified": False, "reason": "no_context", "needs_review": True}
    ctx = " ".join((d.get("content","") + " " + (d.get("_parent",{}).get("content","") if isinstance(d.get("_parent"), dict) else "")) for d in retrieved)
    ctx_n = _norm(ctx)
    ctx_facts = _extract_facts(ctx)
    ans_facts = _extract_facts(answer)
    ans_n = _norm(answer)
    missing_nums = []
    for n in ans_facts["nums"]:
        if _norm(n) not in ctx_n and n.lower() not in ctx.lower():
            missing_nums.append(n)
    if missing_nums and len(ctx_facts["nums"]) == 0:
        missing_nums = []
    missing_props = []
    for p in ans_facts["props"]:
        if _norm(p) not in ctx_n and p not in ctx:
            if len(p.split()) >= 2 and p.lower() not in ["candidate data"]:
                missing_props.append(p)
    if missing_nums or len(missing_props) > 1:
        if not missing_nums and len(missing_props) <= 1:
            return {"verified": True, "reason": "grounded", "needs_review": False}
        return {"verified": False, "reason": f"unsupported: nums={missing_nums} props={missing_props}", "needs_review": True, "missing_nums": missing_nums, "missing_props": missing_props}
    return {"verified": True, "reason": "grounded", "needs_review": False}


def guard(answer: str, retrieved: List[dict]) -> str:
    v = verify_answer(answer, retrieved)
    if not v["verified"]:
        return "NEEDS_REVIEW"
    return answer
