"""Per-user answer cache: reuse successfully entered chat answers, never across users.

Seeded from that user's forms reports, consulted before Gemini, saved on
success. NEEDS_REVIEW is filtered at seed, save, and report time — it is a
verdict, never an answer. Entries are gated by profile hash: a profile edit
silently retires old entries, no purge needed.
"""

import difflib
import json
import os
from datetime import datetime

# ponytail: one file, stdlib only; O_APPEND + per-process dict, no locks; hash-gated, never cross-user

_NEEDS = "NEEDS_REVIEW"
_SIM_THRESHOLD = 0.9


class UnusableAnswer(Exception):
    """Gemini returned NEEDS_REVIEW or an invalid choice — abort the job, not the run."""

    def __init__(self, question, reason):
        super().__init__(f"unusable LLM answer for: {question} ({reason})")
        self.question = question
        self.reason = reason


def norm_q(s) -> str:
    """Single question normalizer — seed and lookup must use this one."""
    return " ".join(str(s or "").lower().split())


def profile_hash(profile) -> str:
    import hashlib as _hl
    try:
        return _hl.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()[:16]
    except Exception:
        return ""


def cache_path(uid) -> str:
    from web.per_user import shard as _sh
    return str(_sh(int(uid)) / "qa_cache.jsonl")


def _usable(row) -> bool:
    q = (row.get("q") or "").strip()
    a = (row.get("answer") or "").strip()
    return bool(q) and bool(a) and a != _NEEDS and q != _NEEDS


def load_seed(report_dir, prof_hash: str) -> dict:
    """Seed only confirmed answers from applications recorded as applied."""
    import glob as _glob
    seed = {}
    skipped = 0
    try:
        paths = sorted(_glob.glob(os.path.join(report_dir, "forms_*.json")))
    except Exception:
        return seed
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                items = (json.load(f) or {}).get("items", [])
        except Exception:
            continue
        for it in items:
            if it.get("status") != "applied" or it.get("accepted") is False:
                continue
            if not _usable(it):
                continue
            if not it.get("profile_hash"):
                skipped += 1  # ponytail: legacy rows predate hash stamping; unprovable age = unusable
                continue
            n = norm_q(it.get("q"))
            seed[n] = {"q": it.get("q"), "norm": n, "type": it.get("type"),
                       "options": it.get("options"), "answer": it.get("answer"),
                       "profile_hash": it.get("profile_hash")}
    if skipped:
        print(f"[cache] seed skipped {skipped} unhashed legacy rows")
    return seed


def load_file(uid) -> dict:
    """Prior-run entries; drops NEEDS_REVIEW and hash-mismatches later at lookup."""
    seed = {}
    try:
        with open(cache_path(uid), encoding="utf-8") as f:
            for line in f:
                try:
                    it = json.loads(line)
                except Exception:
                    continue
                if not _usable(it) or not it.get("norm"):
                    continue
                seed[it["norm"]] = it
    except Exception:
        pass
    return seed


def _options_match(cached_opts, cur_opts) -> bool:
    if not cur_opts:
        return True
    norm = lambda xs: sorted(norm_q(x) for x in (xs or []))
    return norm(cached_opts) == norm(cur_opts)


def remap_radio(hit, cur_options) -> str | None:
    """Map a cached positional digit onto current options via the selected value.

    Returns the current 1-based digit string, or None when the cached value
    is gone (caller falls through to Gemini). Never raises.
    """
    # ponytail: digits are positional; values are identity — remap, don't trust positions
    import re as _re
    try:
        opts = hit.get("options") or []
        digit = (hit.get("answer") or "").strip()
        if not digit.isdigit() or not (1 <= int(digit) <= len(opts)):
            return None
        strip = lambda s: _re.sub(r"^\d+\.\s*", "", norm_q(s))
        want = strip(opts[int(digit) - 1])
        for i, o in enumerate(cur_options or [], start=1):
            if strip(o) == want:
                return str(i)
        return None
    except Exception:
        return None


def lookup(cache: dict, question, qtype, options, prof_hash: str):
    """Exact normalized first, else similarity >= 0.9 + type + options + hash. Returns entry or None."""
    n = norm_q(question)
    hit = cache.get(n)
    if hit and hit.get("type") == qtype and hit.get("profile_hash") == prof_hash and _options_match(hit.get("options"), options):
        return hit
    best, best_score = None, 0.0
    for cnorm, e in cache.items():
        if e.get("type") != qtype or e.get("profile_hash") != prof_hash:
            continue
        if not _options_match(e.get("options"), options):
            continue
        s = difflib.SequenceMatcher(None, n, cnorm).ratio()
        if s > best_score:
            best, best_score = e, s
    if best is not None and best_score >= _SIM_THRESHOLD:
        return dict(best, _sim=round(best_score, 3))
    return None


class QACache:
    """In-memory dict + JSONL append. Best-effort file writes, never raises."""

    def __init__(self, uid=None, prof_hash: str = ""):
        self.uid = uid
        self.prof_hash = prof_hash
        self.mem = {}

    def find(self, qtype, question, options=None):
        """Lookup in this cache (hash-gated inside). Returns entry or None."""
        return lookup(self.mem, question, qtype, options, self.prof_hash)

    def save(self, qtype, question, options, answer, provider="gemini", run_id=""):
        if (answer or "").strip() in ("", _NEEDS):
            return  # ponytail: verdicts are never answers — enforced at save time
        n = norm_q(question)
        if not n:
            return
        e = {"q": question, "norm": n, "type": qtype, "options": options,
             "answer": answer, "provider": provider, "profile_hash": self.prof_hash,
             "ts": datetime.now().isoformat(), "run_id": run_id}
        self.mem[n] = e
        if self.uid is None:
            return
        try:
            with open(cache_path(self.uid), "a", encoding="utf-8") as f:
                f.write(json.dumps(e) + "\n")
        except Exception:
            pass
