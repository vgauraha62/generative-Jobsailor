"""Proposer->reviewer resume tailor loop. Plain functions, no LangChain."""

import json

PROPOSER_SYS = (
    "You rewrite a resume in markdown for ONE job description. Curate every section "
    "that benefits from JD keywords: intro, summary, skills, work descriptions. "
    "Keep one-liner bullets truthful — never invent experience, never add NEEDS_REVIEW. "
    "Return ONLY the full tailored markdown, no fence, no commentary."
)

REVIEWER_SYS = (
    "You judge a tailored resume against the JD. Return ONLY strict JSON, no fence: "
    '{"pass":bool,"score":0..1,"what_it_did":str,"why_failed":str,'
    '"what_to_change":[str],"missing_keywords":[str]}. '
    "Fail on invented experience or missing must-have JD keywords."
)


def _limit() -> int:
    try:
        from config_loader import load_config as _lc
        return int((_lc().get("resume_curation", {}) or {}).get("gemini_daily_limit", 50))
    except Exception:
        return 50


def _ok(uid) -> bool:
    try:
        if uid:
            from web.per_user import load_user_budget as _lub
            return _lub(int(uid), "curation", None).get("calls_used", 0) < _limit()
        from state import load_curation_budget as _lcb, curation_budget_ok as _bok
        return _bok(_lcb(None), _limit())
    except Exception:
        return True


def _record(uid):
    try:
        if uid:
            from web.per_user import record_user_budget_call as _rec
            _rec(int(uid), "curation", None)
        else:
            from state import load_curation_budget as _lcb, record_curation_call as _rcc
            _rcc(_lcb(None))
    except Exception:
        pass


def _parse_review(raw: str) -> dict:
    try:
        txt = (raw or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        d = json.loads(txt)
        return {"pass": bool(d.get("pass")), "score": float(d.get("score", 0) or 0),
                "what_it_did": str(d.get("what_it_did", ""))[:500],
                "why_failed": str(d.get("why_failed", ""))[:500],
                "what_to_change": [str(x)[:200] for x in (d.get("what_to_change") or [])][:5]}
    except Exception:
        return {"pass": False, "score": 0.0, "what_it_did": "", "why_failed": "reviewer_parse_error", "what_to_change": []}


def run_tailor_loop(uid, jd_text: str, base_md: str, threshold: float = 0.75) -> dict:
    """Returns {verdict, attempts, final_md|None, best_score}. final_md None = caller uses single-pass."""
    from gemini_api import openrouter_complete, openrouter_model, provider_for
    if provider_for(uid) != "openrouter":
        return {"verdict": "fail_open", "attempts": [], "final_md": None, "best_score": 0.0}
    proposer, reviewer = openrouter_model("proposer"), openrouter_model("reviewer")
    if not (proposer and reviewer):
        return {"verdict": "fail_open", "attempts": [], "final_md": None, "best_score": 0.0}
    attempts, best_md, best_score, feedback = [], None, -1.0, ""
    for n in range(1, 4):
        # ponytail: plain for-attempt loop, 1 + 2 retries max, then best-effort
        if not _ok(uid):
            break
        try:
            user = f"BASE RESUME:\n{base_md[:8000]}\n\nJOB DESCRIPTION:\n{jd_text[:6000]}"
            if feedback:
                user += f"\n\nPREVIOUS ATTEMPT FEEDBACK (fix exactly this):\n{feedback[:2000]}"
            tailored = openrouter_complete(proposer, PROPOSER_SYS, user, preset="proposer")
            _record(uid)
            raw = openrouter_complete(reviewer, REVIEWER_SYS, f"JD:\n{jd_text[:6000]}\n\nBASE:\n{base_md[:4000]}\n\nTAILORED:\n{tailored[:8000]}", preset="reviewer")
            _record(uid)
        except Exception as e:
            attempts.append({"n": n, "error": str(e)[:200]})
            break
        rev = _parse_review(raw)
        if "NEEDS_REVIEW" in tailored and "NEEDS_REVIEW" not in base_md:
            rev = {"pass": False, "score": 0.0, "what_it_did": rev["what_it_did"],
                   "why_failed": "hallucinated NEEDS_REVIEW", "what_to_change": rev["what_to_change"]}
        attempts.append({"n": n, "tailored": tailored, "review": rev, "score": rev["score"]})
        if rev["score"] > best_score:
            best_md, best_score = tailored, rev["score"]
        if rev["pass"] and rev["score"] >= threshold:
            return {"verdict": "pass", "attempts": attempts, "final_md": tailored, "best_score": rev["score"]}
        feedback = f"WHAT IT DID: {rev['what_it_did']}\nWHY IT FAILED: {rev['why_failed']}\nWHAT TO CHANGE: {'; '.join(rev['what_to_change'])}"
    if best_md is None:
        return {"verdict": "fail_open", "attempts": attempts, "final_md": None, "best_score": 0.0}
    return {"verdict": "best_effort", "attempts": attempts, "final_md": best_md, "best_score": best_score}
