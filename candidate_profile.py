"""Loader for the candidate profile (candidate_profile.json).

The profile is data, not logic, so it lives in a JSON file split into two parts:

- resume_facts: immutable ground truth extracted from the resume. Gemini must
  never contradict these.
- user_preferences: explicit choices that legitimately carry the literal
  sentinel "NEEDS_REVIEW" when not derivable from a document (e.g. CTC).

load_candidate_context() loads and parses the file exactly once and caches the
result for the lifetime of the process. This guarantees the three grounding
call sites (radio, text, form) can never raise from profile I/O mid-job: the
file's existence and validity are proven at startup, so the cache is warm
before any job-processing path runs.
"""

import json
import os

_PROFILE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "candidate_profile.json"
)

_UNSET = object()
_cache = _UNSET


def _load_from_disk() -> dict:
    with open(_PROFILE_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_candidate_profile() -> dict:
    """Return the candidate profile, loaded once and cached thereafter.

    Loads exactly once: a second call returns the cached dict without re-opening
    the file, so no mid-job call site can ever raise from profile I/O.
    """
    global _cache
    if _cache is _UNSET:
        _cache = _load_from_disk()
    return _cache


def find_sentinels(context: dict) -> list:
    """Return dotted paths of every NEEDS_REVIEW value in the profile.

    Pure function (no I/O). e.g. {"a": {"b": "NEEDS_REVIEW"}} -> ["a.b"].
    """
    found = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]" if path else f"[{i}]")
        elif node == "NEEDS_REVIEW":
            found.append(path)

    walk(context, "")
    return found