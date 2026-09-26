import re
import json


def _norm_tokens(s: str) -> set:
    return set(re.findall(r"[a-zA-Z][a-zA-Z0-9\+\#\.]{1,}", s.lower()))


def _extract_keywords_gemini(jd_text: str, timeout=20) -> list:
    from gemini_api import bard_flash_response_curation
    prompt = (
        "Extract 20-30 comma-separated keywords (skills, tools, domains, techniques) "
        "from this job description. Return ONLY JSON array of strings, lowercase, no prose.\n\n"
        f"JD:\n{jd_text[:6000]}"
    )
    raw = bard_flash_response_curation(prompt, timeout)
    try:
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        arr = json.loads(cleaned)
        if isinstance(arr, list):
            return [str(x).strip().lower() for x in arr if str(x).strip()]
    except Exception:
        pass
    toks = re.split(r"[,;\n]+", raw.lower())
    return [t.strip() for t in toks if t.strip()][:30]


def score_jd_vs_resume(jd_text: str, resume_md: str, timeout=20) -> dict:
    if not jd_text or not jd_text.strip() or len(jd_text.strip()) < 20:
        return {"score": 0.0, "keywords": [], "matched": [], "missing": [], "reason": "empty_jd"}
    keywords = _extract_keywords_gemini(jd_text, timeout)
    if not keywords:
        return {"score": 0.0, "keywords": [], "matched": [], "missing": []}
    resume_tokens = _norm_tokens(resume_md)
    resume_lower = resume_md.lower()
    matched = []
    missing = []
    for kw in keywords:
        kw_norm = kw.lower().strip()
        if not kw_norm:
            continue
        if kw_norm in resume_lower or kw_norm in resume_tokens or any(tok in resume_lower for tok in kw_norm.split()):
            matched.append(kw)
        else:
            missing.append(kw)
    score = len(matched) / len(keywords) if keywords else 0.0
    return {"score": round(score, 3), "keywords": keywords, "matched": matched, "missing": missing}
