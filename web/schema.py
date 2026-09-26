"""Single home for LLM-shaped JSON schemas. Stdlib only, no deps."""
import hashlib
from typing import TypedDict

ReviewVerdict = TypedDict("ReviewVerdict", {"pass": bool, "score": float, "what_it_did": str, "why_failed": str, "what_to_change": list})


class JdRef(TypedDict):
    jd_hash: str
    user_id: int
    url: str
    title: str
    company: str
    jd_text: str
    fetched_at: str


class TailorRun(TypedDict):
    id: int
    user_id: int
    jd_hash: str
    verdict: str
    best_score: float
    keywords_json: str
    attempts_json: str
    created_at: str


def jd_hash(url: str, jd_text: str) -> str:
    return hashlib.sha256(f"{url or ''}\n{jd_text}".encode("utf-8")).hexdigest()[:12]
