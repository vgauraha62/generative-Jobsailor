"""Centralized configuration loader.

Reads config.json. Structural problems (missing file, malformed JSON, or a
missing top-level section) fail fast with a clear error. Individual leaf
values fall back to safe defaults when absent, so a small edit to the config
file never bricks a run.
"""

import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# Sane defaults for every leaf key, keyed by section -> {key: default}.
DEFAULTS = {
    "search": {
        "slugs": ["python-jobs"],
        "per_type_jobs": 20,
        "max_jobs_global": 50,
        "max_pages_per_type": 5,
        "max_run_types": 3,
    },
    "browser": {
        "profile_path": "/home/vg/Profiles/naukrijobs",
        "binary": "/opt/firefox/firefox",
    },
    "timing": {
        "page_load_wait": 6,
        "nav_wait": 4,
        "apply_wait": 3,
        "click_delay": 1,
        "save_delay": 2,
        "submit_wait": 3,
        "apply_timeout": 6,
        "question_timeout": 3,
    },
    "apply": {
        "max_questions_per_job": 12,
        "gemini_timeout": 20,
        "form_gemini_timeout": 40,
        "dry_run": True,
    },
    "visited": {
        "max_retries": 2,
    },
    "gemini": {
        "model": "gemini-3.5-flash",
        "temperature": 1,
        "top_p": 0.95,
        "top_k": 64,
        "max_output_tokens": 1000,
        "daily_call_limit": 150,
    },
    "csv": {
        "path": "jobs.csv",
        "fallback_enabled": True,
    },
    "reports": {
        "dir": "reports",
        "capture_enabled": True,
        "visit_enabled": True,
        "manual_enabled": True,
    },
    "resume_curation": {
        "enabled": True,
        "match_threshold": 0.5,
        "gemini_daily_limit": 50,
        "gemini_timeout": 40,
        "upload_timeout": 15,
        "dir": "resumes",
        "active_resume": "resumes/active.json",
    },
    "rag": {
        "embedding_model": "text-embedding-004",
        "dim": 768,
        "chunk_size": 400,
        "overlap": 50,
        "rrf_k": 60,
        "cache_threshold": 0.82,
        "top_k": 10,
        "chat_retention_days": 90,
        "rag_require_api_key": True,
        "negative_cache_ttl": 3600,
        "daily_call_limit": 50,
    },
}

REQUIRED_SECTIONS = set(DEFAULTS.keys())


def load_config() -> dict:
    """Load config.json into a dict merged over DEFAULTS.

    Fails fast if the file is missing, malformed, or a required top-level
    section is absent. Missing leaf keys fall back to DEFAULTS.
    """
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(
            f"config.json not found at {CONFIG_PATH}. Copy config.example.json to config.json."
        )
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"config.json is malformed JSON: {e}")

    if not isinstance(raw, dict):
        raise ValueError("config.json must contain a top-level JSON object.")

    missing = REQUIRED_SECTIONS - set(raw.keys())
    if missing:
        raise ValueError(
            f"config.json is missing required section(s): {sorted(missing)}"
        )

    config = {}
    for section, defaults in DEFAULTS.items():
        config[section] = {}
        raw_section = raw.get(section, {})
        if not isinstance(raw_section, dict):
            raise ValueError(f"config.json section '{section}' must be an object.")
        for key, default in defaults.items():
            config[section][key] = raw_section.get(key, default)
    return config


if __name__ == "__main__":
    print(load_config())
